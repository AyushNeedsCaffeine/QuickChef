# Low-Level Design (LLD)

**Project:** QuickChef — Recipe-to-Cart Shopping Agent
**Version:** 1.0
**Companion documents:** [SRS](./SRS.md), [HLD](./HLD.md)

---

## 1. Module Map

```
QuickChef/
├── app/
│   ├── config.py            # environment-driven settings
│   ├── models.py            # Pydantic domain models
│   ├── main.py              # FastAPI app + REST endpoints
│   ├── agent/
│   │   ├── state.py         # AgentState TypedDict
│   │   ├── prompts.py       # LLM system prompts
│   │   ├── recipes.py       # offline fallback corpus
│   │   └── graph.py         # StateGraph, nodes, HITL interrupt
│   └── services/
│       ├── catalog.py       # Catalog + name resolution
│       ├── matcher.py       # ingredient → SKU matching
│       ├── pack_selector.py # quantity → pack selection
│       ├── cart.py          # CartService (cart + orders)
│       ├── synonyms.py      # learned user dish corrections
│       ├── photos.py        # Wikimedia Commons photo search/cache
│       └── feedback.py      # append-only feedback queue (JSONL)
├── data/catalog.json        # seed product catalog
├── data/synonyms.json       # learned corrections (runtime)
├── templates/index.html     # UI shell
├── static/{style.css,script.js,dish-placeholder.svg}
├── static/dish_photos/      # cached attributed photo files
├── evals/
│   ├── golden/              # cases.jsonl + manifest/schema + feedback queue
│   ├── baselines/           # offline/live results baselines
│   ├── golden.py            # loader/validation
│   ├── golden_feedback.py   # feedback queue loader
│   ├── evaluators.py        # rule-based checks
│   ├── run_golden.py        # golden CLI
│   ├── promote_feedback.py  # review/promote captured feedback
│   ├── run_feedback.py      # replay captured dish feedback
│   └── run_evals.py         # LangSmith dataset + evaluators
└── tests/                   # pytest suite
```

---

## 2. Data Models (`app/models.py`)

```python
class Pack(BaseModel):
    size: float
    unit: Literal["g","kg","ml","l","pc"]
    price: float
    stock: int = 500

class Product(BaseModel):
    id: str
    name: str
    category: str
    aliases: list[str] = []
    packs: list[Pack]

class Ingredient(BaseModel):
    name: str
    quantity: float
    unit: str
    category: str = "other"

class CartItem(BaseModel):
    product_id: str
    name: str            # display name incl. pack, e.g. "Onion (500g)"
    pack_size: float
    pack_unit: str
    quantity: int        # number of packs
    unit_price: float    # price per pack
    # property: line_total = unit_price * quantity

class Order(BaseModel):
    order_id: str
    items: list[CartItem]
    subtotal: float
    delivery_fee: float
    handling_fee: float
    total: float
    status: str = "placed"
    payment_method: str = "cod"   # upi | card | cod
    address: str = "Home"
```

Request bodies:
- `ChatRequest{message}` — legacy conversational entry.
- `CartAddRequest{product_id, quantity}`, `CartUpdateRequest{quantity}`, `ConfirmRequest{address}`.
- `DishRequest{dish}` — wizard step 1 (dish input).
- `ServingsRequest{dish, servings}` — wizard step 2; `servings` validated `1..100`.
- `PayRequest{method, address="Home"}` — wizard step 4; `method` ∈ `{upi, card, cod}`.

---

## 3. Configuration (`app/config.py`)

| Variable | Default | Meaning |
|----------|---------|---------|
| `GROQ_API_KEY` | "" | Enables LLM when non-empty |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | Model id |
| `GROQ_REASONING_EFFORT` | `low` | Latency/quality trade-off for gpt-oss |
| `GROQ_TIMEOUT` | 30 | Per-request LLM timeout (seconds) |
| `GROQ_MAX_TOKENS` | 1200 | Completion token cap |
| `GROQ_MAX_RETRIES` | 1 | Retries for transient/rate-limit failures |
| `PHOTO_ENABLED` | true | Enable Wikimedia dish photos |
| `PHOTO_TIMEOUT` | 4 | Photo HTTP timeout (seconds) |
| `PHOTO_CACHE_TTL` | 3600 | Successful photo cache TTL (seconds) |
| `PHOTO_FAILURE_TTL` | 600 | Retry a missed photo after this window |
| `PHOTO_USER_AGENT` | QuickChef/1.0 + contact | Descriptive UA required by Wikimedia |
| `FEEDBACK_ENABLED` | true | Capture dish/review feedback for golden review |
| `FEEDBACK_PATH` | `evals/golden/feedback.jsonl` | Append-only feedback queue |
| `DELIVERY_FEE` | 25 | Flat delivery fee (₹) |
| `FREE_DELIVERY_ABOVE` | 199 | Free-delivery threshold (₹) |
| `HANDLING_FEE` | 9 | Handling fee (₹) |
| `LLM_ENABLED` | derived | `bool(GROQ_API_KEY)` |
| `LANGSMITH_TRACING` | false | Enable LangSmith tracing |
| `LANGSMITH_API_KEY` | "" | LangSmith key (tracing on when set) |
| `LANGSMITH_PROJECT` | `quickchef` | LangSmith project name |
| `LANGSMITH_ENDPOINT` | `https://api.smith.langchain.com` | LangSmith API endpoint (EU accounts: `https://eu.api.smith.langchain.com`) |
| `LANGSMITH_ENABLED` | derived | tracing flag **and** non-empty key |

`config.py` forces `os.environ["LANGSMITH_TRACING"]="false"` when the key is missing so the
LangSmith client never attempts (and fails) to authenticate.

---

## 4. Service: Catalog (`app/services/catalog.py`)

```python
class Catalog:
    products: list[Product]
    def all() -> list[Product]
    def get(product_id: str) -> Product | None
    def search(query: str, limit: int = 8) -> list[Product]
    def resolve(name: str) -> Product | None
```

**Resolution algorithm (`resolve`)**
1. Normalize the query (lowercase, drop parenthetical aliases, replace punctuation with spaces).
2. Exact/alias lookup in `_alias_index` (built from id, name and aliases).
3. Fallback to `search`, then accept the top hit only when every significant query
   token is covered (`_significant_tokens` / `_accept_ingredient_match`). Prep/generic
   words such as `dry`, `leaves`, `powder`, and `vegetable` do not establish a match,
   and a zero-overlap fallback is rejected. This prevents `Water` → Rose Water and
   `Kale leaves` → Coriander Leaves while still resolving abbreviations and plurals.

`data/catalog.json` includes 127 SKUs, including `kale`, `pumpkin`, and `kala_chana`. Product aliases may also ground an unknown dish when the product name is a known dish (e.g. `black chickpeas` → `Kala Chana`).

**Scoring (`_score`)** — for each candidate name/alias:
- Exact normalized match → `100`.
- Token Jaccard overlap: `overlap/union*10 + overlap`.
- Partial-token bonus: for each unmatched query token ≥ 4 chars with
  `difflib.SequenceMatcher.ratio ≥ 0.8` against a candidate token → `+2`.
- Return the best score; `search` keeps results with score > 0, sorted desc.

`get_catalog()` is an `lru_cache`d singleton that loads `data/catalog.json`.

---

## 5. Service: Pack Selector (`app/services/pack_selector.py`)

**Unit normalization (`to_base`)** maps every unit to a base dimension:

| Dimension | Base | Examples |
|-----------|------|----------|
| mass | g | g=1, kg=1000, pinch=0.4, handful=30 |
| volume | ml | ml=1, l=1000, cup=240, tbsp=15, tsp=5 |
| count | pc | pc, piece, clove, slice, bunch, sprig |

**Selection (`select_packs`)** — for a required quantity in a product:
1. Convert requirement and each pack size to base; coerce mass↔volume 1:1.
2. For each candidate pack size compute `count = ceil(required/size)`,
   `cost = count * price`, `waste = count*size − required`.
3. Choose the pack minimizing `(cost, waste)` — i.e. cheapest cover, then least
   over-supply. Homogeneous packs only (keeps `CartItem` pricing exact).
4. If no compatible dimension (e.g. count vs mass), skip that pack.

**`build_cart_item`** converts the chosen `(pack, count)` into a `CartItem`.

> Invariant (NFR-5): `count * pack_size_base ≥ required` always holds.

---

## 6. Service: Matcher (`app/services/matcher.py`)

```python
def match_ingredients(ingredients, catalog=None) -> MatchResult
# MatchResult: { matched: list[CartItem], unmatched: list[Ingredient],
#               pantry: list[Ingredient] }
```
For each ingredient: skip pantry items (`Water`, `Ice` via `is_pantry`), otherwise
`catalog.resolve(name)` → `build_cart_item(...)`. Resolution or conversion failure →
`unmatched`. Pantry items are reported separately and never added to the cart. Display
name is rewritten to include the pack, e.g. `Onion (500g)`.

---

## 7. Service: Cart (`app/services/cart.py`)

```python
class CartService:
    def get_cart(session_id) -> list[CartItem]
    def clear(session_id) -> None
    def add_items(session_id, items) -> list[CartItem]      # merges by key
    def add_product(session_id, product_id, quantity=1) -> CartItem
    def update_quantity(session_id, product_id, quantity) -> list[CartItem]  # qty<=0 removes
    def remove_product(session_id, product_id) -> list[CartItem]
    def totals(session_id) -> dict   # subtotal, delivery_fee, handling_fee, total
    def place_order(session_id, address="Home", payment_method="cod") -> Order
    def get_order(order_id) -> Order | None
    def session_orders(session_id) -> list[Order]

cart_service = CartService()   # module-level singleton
```

**Cart key:** `"{product_id}:{pack_size}{pack_unit}"` — merging adds quantities.

**Totals:** `subtotal = Σ line_total`; `delivery = 0 if subtotal ≥ 199 or subtotal == 0 else 25`;
`handling = 9 if subtotal > 0 else 0`; `total = subtotal + delivery + handling`.

**Order id:** `"QC" + uuid4().hex[:8].upper()`.

---

## 8. Service: Synonyms (`app/services/synonyms.py`)

```python
STORE_PATH = BASE_DIR / "data" / "synonyms.json"
def lookup(term: str) -> str | None
def learn(term: str, canonical: str) -> str
def all_learned() -> dict[str, str]
```

Learned corrections back the “Did you mean…?” confirmation card. Keys/values are
whitespace-collapsed and case-insensitive (`_norm`); writes are serialized with a lock and
performed atomically (`tmp` + `os.replace`). The file is a plain `{term: canonical}` JSON map.
`POST /api/dish` checks `lookup(raw)` **before** `parse_input`, so a learned correction costs
zero LLM calls. Tests monkeypatch `STORE_PATH` to a temp file.

---

## 9. Service: Photos (`app/services/photos.py`)

```python
def find_photo(dish: str) -> dict
# success: {kind:"photo", dish, url, source, source_url, artist, license}
# miss:    {kind:"none", dish, reason}
```

- Uses the canonical `display_name` for the search query and cache key (`maggi` →
  `Maggi Noodles`, `pumpkin` → `Pumpkin Sabzi`).
- Queries the Wikimedia Commons API (`generator=search`, namespace 6, `imageinfo` with
  `url|extmetadata`, 480 px thumb) and falls back to the Wikipedia page image.
- Scores candidates against the dish's core tokens: full coverage, exact phrase, JPEG bonus;
  optional tails (`curry`, `sabzi`, `recipe`, …) may be absent. Rejects people/decorations
  (`_BAD_WORDS`) and titles that miss the core dish, rather than showing a wrong dish.
- Downloads only allowed hosts (`upload.wikimedia.org`, `commons.wikimedia.org`) into
  `static/dish_photos/<slug>.<ext>` (max 4 MB, retry on 403/429).
- Metadata cache: `data/photo_cache.json`; successful entries use `PHOTO_CACHE_TTL`, misses use
  the shorter `PHOTO_FAILURE_TTL`. `PHOTO_USER_AGENT` must include a contact URL/email or
  Wikimedia returns `403`.
- The UI displays artist/license and links the credit to `source_url`; failures return
  `kind="none"` and the placeholder SVG.

---

## 10. Service: Feedback (`app/services/feedback.py`)

```python
FEEDBACK_PATH = config.FEEDBACK_PATH  # default evals/golden/feedback.jsonl
FEEDBACK_ENABLED = config.FEEDBACK_ENABLED

def capture(event: dict) -> dict
# stored:   {ok: True, stored: True, id, status}
# skipped:  {ok: True, stored: False, reason: "feedback disabled" | "write failed"}

def load_events(path: Path | None = None) -> list[dict]
```

- Events are **append-only JSONL**, written under a lock with `O_APPEND|O_CREAT` (mode `0600`)
  and `fsync`; the parent directory is created on demand. A storage failure is logged and returned
  as `stored:false`, never raised into the wizard.
- `capture` fills `schema_version: 1`, `id: fb_<uuid12>`, UTC `captured_at`, and
  `status = pending_review` when `needs_review` is set, else `recorded`.
- Sanitization caps strings at 300 chars, keys at 80, lists at 50, nesting at 6; `_fit` trims large
  recipe/cart snapshots and sets `truncated:true` (hard cap 64 KB).
- Event shapes:
  - `dish_rejected`: `{needs_review:true, dish:{raw, suggested_dish, display, candidates,
    needs_clarification, modifiers, source}}`.
  - `dish_correction`: `{needs_review:true, correction:{parent_id, rejected_raw, rejected_dish,
    accepted_raw, accepted_dish, accepted_display}}`.
  - `review_liked` / `review_disliked`: server-side snapshots `{dish:{raw, dish, display, servings},
    recipe:{...}, cart:{items, totals}}`; dislikes set `needs_review:true`.
- `evals/golden_feedback.py` loads/validates the queue (`FeedbackEvent`, `summarize`), and
  `evals/promote_feedback.py` appends selected events to `cases.jsonl` (updating manifest counts).
  `evals/run_feedback.py` replays captured dish feedback against the current resolver.

---

## 11. Agent (`app/agent/`)

### 10.1 State (`state.py`)

```python
class AgentState(TypedDict, total=False):
    session_id: str
    messages: Annotated[list, add_messages]
    dish: str | None
    servings: int | None
    preparsed: bool             # wizard already resolved dish + servings
    candidates: list[dict]      # possible dishes for the confirmation card
    needs_clarification: bool
    ingredients: list[dict]
    steps: list[str]            # ordered cooking steps
    cart: list[dict]
    unmatched: list[str]
    recipe_source: str          # "llm" | "offline"
    error: str | None
    payment_method: str | None
    address: str | None
    stage: str
    reply: str
    order: dict | None
```

`messages` uses the `add_messages` reducer to append conversation turns.
`stage` values: `await_dish`, `await_servings`, `matching`, `cart_review`,
`placing`, `cancelled`, `done`.

### 10.2 Structured LLM Schemas (`graph.py`)

```python
class DishCandidate(BaseModel):
    name: str; description: str = ""; confidence: float = 0.0
class ParsedInput(BaseModel):   # intent extraction
    dish: str | None; canonical_dish: str | None; servings: int | None
    candidates: list[DishCandidate] = []
    needs_clarification: bool = False
    source: str = "heuristic"   # "llm" | "heuristic"
class MatchCandidate(BaseModel):
    name: str; description: str = ""; confidence: float = 0.0
class MatchSuggestions(BaseModel):
    candidates: list[MatchCandidate] = []
class RecipeItem(BaseModel):    # one ingredient
    name: str; quantity: float; unit: str; category: str = "other"
class RecipeDraft(BaseModel):
    ingredients: list[RecipeItem]
    steps: list[str] = []

@dataclass
class ResolvedRecipe:
    ingredients: list[RecipeItem]
    steps: list[str]
    source: str                 # "llm" | "offline"
```

`get_llm()` returns a cached `ChatGroq(temperature=0, reasoning_effort=...)` or `None` when no
key is set. `parse_input()` extracts intent; for unknown names
`suggest_catalog_matches()` asks the LLM for up to three plausible catalog dishes; if the LLM
returns none, a conservative head-noun spelling fallback can still offer a close catalogue name
(`Matar Kulcha` → `Chole Kulche`, never `Matar Paneer`). Both use
`_structured(schema, messages)`, which calls `with_structured_output(..., method="json_schema")`
with a small retry — gpt-oss is unreliable at function-calling but solid with JSON-schema mode —
and falls back to heuristics / no candidates on failure. `resolve_recipe(dish, servings, label)`
returns a `ResolvedRecipe` (ingredients already scaled, plus steps), caches successful and
failed results in a lock-protected TTL cache keyed by normalized dish + servings, and returns a
defensive copy so graph state cannot mutate the cache.

`PARSE_SYSTEM` keeps dish phrases **verbatim, including modifiers** and asks for a canonical name
only for clearly known dishes. `MATCH_SYSTEM` is a separate, stricter prompt used only for unknown
names; it must return `[]` rather than guessing when nothing is plausible. `EXTRACT_SYSTEM`
honours exclusions (omit the ingredient and any step using it) and additions.

### 10.3 Node Contracts

| Node | Reads | Writes | Notes |
|------|-------|--------|-------|
| `understand` | last `HumanMessage`, `preparsed` | `dish`, `servings`, `candidates`, `needs_clarification` | Merge-only; `preparsed` skips LLM parsing |
| `ask_dish` | — | `stage=await_dish`, `reply`, AI msg | |
| `clarify` | `candidates` | `stage=await_dish`, `reply`, AI msg | presents up to 3 “Did you mean…” options |
| `ask_servings` | `dish` | `stage=await_servings`, `reply`, AI msg | |
| `extract` | `dish`, `servings` | `ingredients`, `steps`, `recipe_source`, `stage=matching` **or** `dish=None`,`stage=await_dish`,`error` | failure re-prompts |
| `match` | `session_id`, `ingredients`, `dish`, `servings` | `cart`, `unmatched`, `stage=cart_review`, `reply` | fills cart |
| `cart_review` | `session_id`, `cart` | `stage=placing` + `payment_method` + `address` (confirm) or `stage=cancelled` | calls `interrupt()`; resume value carries `action` + `method` + `address` |
| `place_order` | `session_id`, `dish`, `payment_method`, `address` | `order`, `stage=done`, `reply` | calls `CartService.place_order(address, payment_method)` |

### 10.4 Heuristic Parser (`heuristic_parse`)

- Servings: first integer in the message.
- Dish: remove digits and filler words (`i want to cook`, `for`, `people`, …),
  strip punctuation; `None` if empty or the message is just a number.

### 10.5 Routers

```python
route_after_understand: dish missing→ask_dish; candidates need clarification→clarify;
                        servings missing→ask_servings; else extract
route_after_extract:    stage=="matching" → match; else END
route_after_review:     stage=="placing"  → place_order; else END
```

### 10.6 Human-in-the-Loop

`cart_review` calls `interrupt({stage, session_id, cart})`. The compiled graph
(checkpointer `MemorySaver`) persists state and returns control to the API with the
thread paused (`state.next` non-empty). Resuming:

```python
graph.invoke(Command(resume={"action": "confirm"|"cancel"}), config={"configurable": {"thread_id": sid}})
```

### 10.7 Fallback Recipes (`recipes.py`)

`FALLBACK_RECIPES` holds portions for 4 servings for popular dishes
(`dal makhani`, `paneer butter masala`, `rajma curry`, `chole`, `aloo gobi`,
`vegetable biryani`, `vegetable poha`). `get_fallback_recipe(dish)` matches by
normalized name, then strict token-subset matching (so a modified phrase like
`rajma without onion garlic` still maps to `rajma curry`). `scale(recipe, servings)`
linearly scales by `servings/4`.

`POPULAR_DISHES` also grounds `Kala Chana`, `Masala Chana`, `Pumpkin Sabzi`, and
`Maggi Noodles`, but these are **LLM-only**: there is intentionally no offline fallback
for them, so offline mode may report “recipe not found”.

`FALLBACK_STEPS` holds an ordered cooking method (4–8 steps) per dish, keyed by the
same canonical dish. Helpers:
- `_resolve_key(dish, keys)` — normalized exact match first, then strict token-subset matching;
  reverse subsets and generic trailing words (`curry`, `masala`, `dish`, …) are rejected.
- `catalog_name(dish)` / `display_name(dish)` — catalog-first display name that preserves
  modifiers (`chole kulcha` → `Chole Kulche`); unmatched names are title-cased.
- `POPULAR_DISHES` / `dish_catalog()` — UI chips and matcher catalog; deduped by token set.
- `get_fallback_steps(dish)` — return the ordered steps for a dish, or `None`.
- `has_modifiers(dish)` — `True` when the phrase contains a modifier keyword
  (`without`, `no`, `with`, `extra`, `less`, `more`, `add`, `only`, …), used to decide
  whether an offline build needs a "modification not applied" notice.

---

## 12. API Layer (`app/main.py`)

**Helpers**
- `_thread(session_id)` → `{"configurable": {"thread_id": session_id}}`
- `_snapshot(session_id)` → `graph.get_state(_thread(...))`
- `_session_view(session_id)` → session_id/stage/dish/servings/reply/paused
- `_recipe_view(values)` → dish/servings/ingredients/steps/**unmatched**/**modifiers**/**notice**/source
- `_cart_view(session_id)` → `{items, totals}` from `cart_service`
- `_reset_if_paused(session_id)` → resumes the graph with `cancel` if a review is pending
- `_run_config(session_id, run_name, **meta)` → LangGraph `RunnableConfig` for tracing
  (run name, `tags=["quickchef", run_name]`, metadata `{session_id, dish, servings, …}`); used by
  every `graph.invoke` call so each wizard stage is a named LangSmith trace

**Endpoint behaviours**

| Endpoint | Success | Failure |
|----------|---------|---------|
| `POST /api/session` | 200 new `session_id` | — |
| `GET /api/session/{sid}` | 200 `{...session, recipe, cart}` | — |
| `POST /api/dish/{sid}` | 200 `{understood, dish, display, raw, modifiers, candidates, needs_clarification}`; learned synonyms skip the LLM | 422 empty/unknown dish |
| `GET /api/dish/photo?dish=` | 200 `{kind, dish, url, source, source_url, artist, license}` or `{kind:"none", reason}` | 422 missing dish |
| `POST /api/synonyms` | 200 `{ok, learned}` after validating `{term, canonical}` | 422 empty term/canonical |
| `POST /api/feedback/{sid}` | 200 `{ok, stored, id, status}`; review likes/dislikes require a recipe + cart snapshot | 422 empty rejection raw / missing correction `parent_id`+`accepted_dish`; review without snapshot returns `stored:false` |
| `POST /api/servings/{sid}` | 200 `{recipe, cart, paused, stage}` after building; resolves the dish through learned synonyms and passes `preparsed=True` | 422 recipe not found → wizard returns to Step 1 |
| `POST /api/chat/{sid}` | 200 `{reply, stage, dish, servings, paused}`; if paused returns a review reminder | — |
| `GET /api/cart/{sid}` | 200 `{items, totals}` | — |
| `POST /api/cart/{sid}/items` | 200 updated cart | 404 unknown product |
| `PATCH /api/cart/{sid}/items/{pid}` | 200 updated cart (qty≤0 removes) | — |
| `DELETE /api/cart/{sid}/items/{pid}` | 200 updated cart | — |
| `POST /api/order/{sid}/pay` | 200 `{reply, stage, order, method}` (resume confirm) | 400 if not paused |
| `POST /api/cart/{sid}/confirm` | 200 `{reply, stage, order, orders}` | 400 if not paused |
| `POST /api/cart/{sid}/cancel` | 200 `{reply, stage}` | 400 if not paused |
| `GET /api/orders/{sid}` | 200 `{orders}` | — |
| `GET /api/catalog/search` | 200 `{results}` | — |

---

## 13. Frontend (`templates/index.html`, `static/`)

A single page with five screens and a progress stepper: `screen-1` (Dish),
`screen-2` (Servings), `screen-3` (Review), `screen-4` (Payment), `screen-done`.

Visual layer: a fixed, low-opacity green food-doodle tile (`static/doodles.png`) sits behind
the white page (`body::before`), with panels above it. Motion uses shared tokens
(`--ease`, `--dur-*`) for staged entrances, hover lifts, an animated slider fill (`@property --pct`),
cart bump/bill pop, a payment sheen and a success ripple; all are disabled under
`@media (prefers-reduced-motion: reduce)`.

Step 1 also renders a **slow right-to-left marquee** of 16 dish cards (`#food-track`, data in
`script.js`), illustrated by `static/foods/*.svg`. The set is duplicated for a seamless
`translateX(-50%)` loop, pauses on hover/focus, and each card fills the dish box and submits it.
A fixed, decorative **steaming-bowl** doodle (`.food-float`) floats bottom-right.

Client state: `{ sessionId, dish, display, rawDish, candidates, photo, servings, cart, recipe,
paused, maxStep }`; a monotonic `photoToken` discards stale photo responses.

Key flows:
- **Boot:** `newSession()` → `POST /api/session`; `setServings(4)`; show step 1.
- **Step 1:** `submitDish(raw)` → `POST /api/dish/{sid}` → `showDishConfirm()` renders
  `#dish-confirm` with the canonical name, a cached photo + attribution link, and up to three
  candidate cards (`renderDishCandidates`). Candidate click updates the dish and
  `POST /api/synonyms`; **Yes, cook this** advances to step 2 and links a pending rejection to
  the accepted dish (`dish_correction`); **Not this dish** clears the card, focuses the input,
  and captures `dish_rejected`. Photos load through `GET /api/dish/photo`; failures use
  `static/dish-placeholder.svg`, not a wrong image.
- **Step 2:** slider (1–20) / typed value (1–100) set `servings`; `submitServings()` →
  `POST /api/servings/{sid} {dish, servings}` → store `recipe`+`cart`, render review,
  advance to step 3. On 422, show the error and return to step 1.
- **Step 3:** `renderReview()` fills the recipe card (ingredients + steps), the
  **modifier notice** (`#modifier-note`, shown when the recipe was modified — and, offline,
  warns the base recipe was used) and an **unmatched notice** (`#unmatched-note`), then
  `renderCart()` draws editable ingredient cards and the live bill; cart clicks →
  `PATCH`/`DELETE` → `refreshCart()`. Debounced search → `POST .../items`.
  The overall feedback bar (`#review-feedback`) posts `review_liked` / `review_disliked`
  (best-effort, one per review session); dislikes queue a recipe + cart snapshot for review.
  **Cancel order** → `POST /api/cart/{sid}/cancel` → fresh Step 1.
- **Step 4:** `renderPayment()` builds the summary; the address input (`#address-input`,
  default "Home") is sent with `pay()` → `POST /api/order/{sid}/pay` `{method, address}` →
  `renderDone(order)` → `screen-done`.
- **Start over:** reset client state, `newSession()`, show step 1.
- The stepper allows navigating back to already-completed steps.

---

## 14. Error Handling Summary

| Condition | Behaviour |
|-----------|-----------|
| LLM unavailable | Fall back to heuristics + offline corpus (NFR-3) |
| Recipe not found | `POST /api/servings` → 422; `dish` reset to `None`, `error` set; wizard returns to Step 1 |
| Empty dish (step 1) | `POST /api/dish` → 422 with a helpful message |
| Ambiguous dish | `POST /api/dish` returns `candidates` + `needs_clarification`; UI asks the user |
| Learned correction | `synonyms.lookup` returns the canonical name before `parse_input` (no LLM call) |
| Feedback write fails / disabled | `POST /api/feedback` returns `{ok:true, stored:false, reason}`; the UI ignores it and keeps shopping |
| Photo missing/blocked | `GET /api/dish/photo` → `{kind:"none"}`; UI shows the placeholder SVG |
| Groq 429 / transient error | `_structured` retries once, then falls back to heuristics/offline |
| Ingredient not in catalog | Added to `unmatched`, reported, non-fatal |
| Dish has a modifier in offline mode | Base recipe built from the corpus; `recipe.notice` warns the modification needs the AI chef |
| LangSmith key missing | `LANGSMITH_TRACING` forced to `false`; app runs normally |
| Payment/confirm while not paused | HTTP 400 |
| Cancel while not paused | HTTP 400 |
| Empty-cart confirm | HTTP 400 (`detail` message) |
| Unknown product add | HTTP 404 |
| Going back to change servings | `_reset_if_paused` cancels the pending review, then rebuilds |
| Unknown unit | Treated as mass with factor 1 |

---

## 15. Test Design (`tests/`)

| File | Coverage |
|------|----------|
| `test_catalog.py` | load, name/alias resolution, strict weak-overlap rejection, new SKUs, unknown→None, search ranking |
| `test_pack_selector.py` | unit conversion, single/multiple packs, cheapest pack, count units, pricing |
| `test_cart.py` | add, merge, update, remove, totals, free delivery, order + clear, errors |
| `test_agent.py` | heuristic parsing, happy path + confirm, cancel, unknown dish, servings-first |
| `test_recipes.py` | `canonical_name`, `get_fallback_steps`, `scale` linearity, `_resolve_key` (incl. modifier phrases), unknown→None, `has_modifiers` |
| `test_evals.py` | rule-based evaluators: must-include present/missing, must-exclude clean/violated, min-steps threshold |
| `test_dish_resolution.py` | canonical names, strict token matching, colloquial/candidate behavior, modifier preservation |
| `test_synonyms.py` | normalization, learn/lookup, persistence, atomic store, duplicate overwrite |
| `test_feedback.py` | rejection/correction capture, review snapshots, validation, disabled/write-failure best effort, text caps, frontend hooks |
| `test_photos.py` | canonical query/title scoring, people/decorations rejection, cache hits, allowlisted downloads, attribution, failure TTL |
| `test_golden.py` | 68-case loader, unique ids, manifest counts, evaluator checks, `display_not`/`matched_not`, feedback loader/promotion, cache-isolated offline subprocess gate |
| `test_wizard_api.py` | HTTP wizard flow via `TestClient`: session, dish normalize, candidate payload, learned synonym skips LLM, modifier notice, servings→recipe+cart, photo endpoint, unknown dish 422, cart mutation, pay, address, cancel, chat reminder, static assets |

The agent and wizard tests monkeypatch `get_llm → None` (via `app.agent.graph`) for
deterministic offline execution. Feedback tests also isolate `FEEDBACK_PATH` and `STORE_PATH` to
a temp directory. The golden runner clears the recipe cache before every case, so a live result cannot leak into an offline case. The golden subprocess test runs the full offline suite in isolation.

Run: `pytest -q`

---

*End of LLD.*
