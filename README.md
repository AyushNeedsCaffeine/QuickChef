# QuickChef 🛒🍳

**Recipe-to-cart shopping agent for quick-commerce platforms (à la Blinkit/Zepto).**

Tell QuickChef what you want to cook and how many people you're cooking for — it researches
the recipe, converts every ingredient into real grocery packs, fills your cart, then hands it
to you for review before a mock payment places the order. All in a clean 4-step wizard.

```
Step 1  Dish      → live typeahead: "Dal Makhani" → select → servings
Step 2  Servings  → slider/typed "4 people"
Step 3  Review    → full recipe + ingredient cards; add / remove / change quantity
Step 4  Payment   → pick UPI / Card / COD → order placed
```

---

## v2.1 release highlights

- Known suggestions, quick-pick chips, and exact catalogue names now advance straight to Servings.
- Ambiguous names still show candidate cards, then advance as soon as a candidate is chosen.
- Only custom dishes show a confirmation card; the AI chef can now invent a recipe for a genuinely
  new custom dish instead of forcing it into the catalogue.
- Custom confirmation shows a dish photo only when Wikimedia offers a sufficiently relevant,
  high-resolution image; otherwise the card stays text-only.
- `Rasgulla` added to the catalogue (with an offline fallback), so `rasgula` resolves cleanly.
- Logo supplied by the user, exported to responsive PNGs and favicon; clicking it starts a fresh dish.
- Golden dataset expanded to 77 cases with typo/typeahead coverage.

---

## Features

- **4-step wizard UI** (Dish → Servings → Review → Payment) with a progress stepper.
- **Live dish typeahead** backed by a curated catalogue: every keystroke returns relevant dishes,
  multi-word input uses AND semantics (`malai chaap` → only Malai Soy Chaap), and “Something else”
  reveals a custom-dish input.
- **Catalogue-first recipes**: regular input is validated against the curated catalogue; unknown
  dishes are rejected with a clear message. The explicit custom-dish path may use the LLM to create
  a genuinely new dish, while offline mode rejects custom dishes it cannot resolve.
- **Ambiguity handling without alias tables**: catalogue candidates are offered for names such as
  `Matar Kulcha` → “Did you mean Chole Kulche?”; specific corrections can be learned locally.
- **Photos only on custom confirmation** — a custom dish may show one attributed Wikimedia image
  when relevance and resolution gates pass. Normal catalogue dishes never request a photo, so the
  image path cannot delay the common flow.
- Recipe research via **Groq LLM** with structured extraction — ingredients, scaled quantities, **and cooking steps**.
- **Offline mode**: no API key? Common dishes still work via a built-in fallback corpus (recipes + steps).
- Strict catalog matching: aliases (`pyaz` → Onion, `haldi` → Turmeric), fuzzy names (`dal makhni` → Dal Makhani), and rejection of weak token overlaps (`Water` → Rose Water); pantry items are excluded from the cart.
- Cost-optimal **pack selection** (e.g. 400 g onion → 1 × 500 g pack) honoring whole-pack retail.
- **Human-in-the-loop** cart review using LangGraph `interrupt()` / `Command(resume=...)`.
- Review screen shows the **full recipe** (ingredients + ordered steps) beside editable ingredient cards, live totals and bill.
- Mock **payment methods** (UPI / Card / COD) with an order confirmation screen.
- **Free-text dish modifications** (`Rajma without onion garlic`, `Mix veg with mushrooms`).
- **LangSmith tracing** of every run/LLM call + a rule-based eval suite.
- **Feedback capture for golden-dataset growth**: “Not this dish” / accepted-correction pairs and an
  overall recipe + basket like/dislike bar on Review, written to a separate review queue.
- **Curated golden dataset** (77 cases) with offline and live modes, typeahead coverage, JSON
  baselines, and a pytest gate.
- **User-supplied QuickChef logo** exported to responsive PNGs and a favicon; clicking it starts a fresh dish.
- Faint **food-doodle background**, a **slow right-to-left dish marquee** (16 cuisines + sweets)
  and a floating steaming-bowl doodle; all motion honours `prefers-reduced-motion`.

---

## Architecture (one line)

`Browser (4-step wizard)` → `FastAPI` → `LangGraph agent` → `catalog · matcher · pack_selector · cart`.

See [`docs/HLD.md`](docs/HLD.md) and [`docs/LLD.md`](docs/LLD.md) for diagrams and design detail.

---

## Project Structure

```
QuickChef/
├── app/
│   ├── config.py          # env-driven settings
│   ├── models.py          # Pydantic models
│   ├── main.py            # FastAPI app + REST endpoints
│   ├── agent/
│   │   ├── graph.py       # LangGraph state machine + HITL
│   │   ├── state.py       # AgentState
│   │   ├── prompts.py     # LLM prompts
│   │   └── recipes.py     # offline fallback recipes + cooking steps
│   └── services/
│       ├── catalog.py     # product catalog + resolution
│       ├── matcher.py     # ingredient → SKU
│       ├── pack_selector.py
│       ├── cart.py        # cart + orders
│       ├── photos.py      # optional custom-confirm photo gate + cache
│       ├── feedback.py    # append-only feedback queue (JSONL)
│       └── synonyms.py    # learned dish-name corrections
├── evals/
│   ├── golden/            # cases.jsonl + manifest/schema + feedback queue
│   ├── baselines/         # committed offline/live result baselines
│   ├── golden_feedback.py # feedback queue loader
│   ├── promote_feedback.py # review/promote feedback into golden cases
│   ├── run_feedback.py    # replay captured dish feedback
│   └── run_golden.py      # offline/live golden runner
├── data/catalog.json      # 128 mock SKUs, including soya_chaap
├── data/synonyms.json     # learned user corrections (created on first choice)
├── templates/index.html
├── static/{style.css,script.js,dish-placeholder.svg,logo*.png,favicon.png}
├── static/dish_photos/    # optional custom-photo cache (gitignored)
├── tests/                 # pytest suite
└── docs/{SRS,HLD,LLD}.md
```

---

## Requirements

- Python **3.11+** (tested on 3.14)
- (Optional) A **Groq API key** for live recipe research — get one at <https://console.groq.com>

---

## Setup

```bash
# from the QuickChef directory
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# optional: enable the LLM
cp .env.example .env
# then edit .env and set GROQ_API_KEY=...
```

Without a key the app runs in **offline recipe mode** (heuristic parsing + fallback corpus).

---

## Run

```bash
uvicorn app.main:app --reload --port 8000
```

Open <http://127.0.0.1:8000> and walk the wizard:

1. **Dish:** start typing `paneer` or `chaap` → pick a live suggestion (or choose
   “Something else”). Known suggestions advance immediately; ambiguous names show candidates.
   Only a custom dish opens a confirmation preview (with an optional photo). Regular unknown dishes
   are rejected.
2. **Servings:** set `4` on the slider → loads the recipe and builds the basket.
3. **Review:** read the full recipe (ingredients + steps); add `milk`, remove the cream, bump the urad dal quantity.
4. **Payment:** choose `UPI` and pay → confirmation with the order id.

---

## Test

```bash
pytest -q                       # unit/API tests + deterministic offline golden gate
python -m evals.run_golden      # deterministic offline golden cases
python -m evals.run_golden --live --suite dish --suite recipe --suite flow --suite photo
```

All unit/API tests run offline (the LLM is disabled in tests). Live golden cases need a Groq
key/network and are intentionally excluded from `pytest`.

---

## REST API (quick reference)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/session` | Create a session |
| GET | `/api/session/{session_id}` | Current session state (dish, servings, recipe, cart, paused) |
| GET | `/api/dish/suggest?q=&limit=` | Deterministic catalogue typeahead (AND semantics) |
| POST | `/api/dish/{session_id}` | Wizard step 1 — resolve `{dish, custom?}`; regular unknown dishes are rejected, custom dishes may use the LLM |
| GET | `/api/dish/photo?dish=` | Cached Wikimedia photo lookup; the UI uses it only on custom confirmation |
| POST | `/api/synonyms` | Learn a user correction `{term, canonical}` |
| POST | `/api/feedback/{session_id}` | Capture dish rejection/correction or review like/dislike (best-effort) |
| POST | `/api/servings/{session_id}` | Wizard step 2 — build recipe + cart from `{dish, servings, custom?}` |
| POST | `/api/chat/{session_id}` | Send a message; run the agent (legacy/conversational) |
| GET | `/api/cart/{session_id}` | Cart items + totals |
| POST | `/api/cart/{session_id}/items` | Add product `{product_id, quantity}` |
| PATCH | `/api/cart/{session_id}/items/{product_id}` | Set quantity `{quantity}` |
| DELETE | `/api/cart/{session_id}/items/{product_id}` | Remove item |
| POST | `/api/order/{session_id}/pay` | Wizard step 4 — pay `{method, address}` & place order |
| POST | `/api/cart/{session_id}/confirm` | Confirm & place order |
| POST | `/api/cart/{session_id}/cancel` | Cancel pending order |
| GET | `/api/orders/{session_id}` | Session orders |
| GET | `/api/catalog/search?q=` | Search catalog |
| GET | `/api/health` | Health + LLM status |

### Example (wizard flow)

```bash
BASE=http://127.0.0.1:8000
SID=$(curl -s -X POST $BASE/api/session | python3 -c "import sys,json;print(json.load(sys.stdin)['session_id'])")

# Step 1 — dish
curl -s -X POST $BASE/api/dish/$SID -H 'Content-Type: application/json' \
  -d '{"dish":"dal makhni"}'
# Step 2 — servings → recipe + cart
curl -s -X POST $BASE/api/servings/$SID -H 'Content-Type: application/json' \
  -d '{"dish":"dal makhni","servings":4}'
# Step 3 — cart (add / update / remove as you like)
curl -s $BASE/api/cart/$SID | python3 -m json.tool
# Step 4 — pay & place order
curl -s -X POST $BASE/api/order/$SID/pay -H 'Content-Type: application/json' \
  -d '{"method":"upi"}' | python3 -m json.tool
```

---

## Configuration

| Env var | Default | Description |
|---------|---------|-------------|
| `GROQ_API_KEY` | _(empty)_ | Enables LLM mode when set |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | Groq model id |
| `GROQ_REASONING_EFFORT` | `low` | `low` keeps dish/recipe extraction fast |
| `GROQ_TIMEOUT` | `30` | Per-request timeout in seconds |
| `GROQ_MAX_TOKENS` | `1200` | Max completion tokens |
| `GROQ_MAX_RETRIES` | `1` | Retries for transient/rate-limit errors |
| `PHOTO_ENABLED` | `true` | Enable Wikimedia dish photos |
| `PHOTO_TIMEOUT` | `4` | Photo network timeout in seconds |
| `PHOTO_CACHE_TTL` | `3600` | Successful photo cache TTL in seconds |
| `PHOTO_FAILURE_TTL` | `600` | Retry window after a failed photo lookup |
| `PHOTO_USER_AGENT` | QuickChef + contact | Required descriptive Wikimedia User-Agent |
| `FEEDBACK_ENABLED` | `true` | Capture feedback for golden-dataset review |
| `FEEDBACK_PATH` | `evals/golden/feedback.jsonl` | Append-only feedback queue path |
| `DELIVERY_FEE` | `25` | Delivery fee (₹) |
| `FREE_DELIVERY_ABOVE` | `199` | Free-delivery threshold (₹) |
| `HANDLING_FEE` | `9` | Handling fee (₹) |
| `LANGSMITH_TRACING` | `false` | Enable LangSmith tracing (`true`) |
| `LANGSMITH_API_KEY` | _(empty)_ | LangSmith key; tracing turns on when set |
| `LANGSMITH_PROJECT` | `quickchef` | LangSmith project name |
| `LANGSMITH_ENDPOINT` | `https://api.smith.langchain.com` | LangSmith API endpoint (EU: `https://eu.api.smith.langchain.com`) |

---

## Recipe modifications

The dish box accepts free-text modifications that the AI chef honours:

- Exclusions: `Rajma without onion garlic`, `Paneer butter masala no cream`
- Additions: `Mix veg with mushrooms`, `Chole extra paneer`

Modifications are preserved end-to-end and applied by the LLM. In **offline mode** (no Groq key)
the base recipe is built from the fallback corpus and the Review screen shows a notice that the
modification needs the AI chef.

---

## Observability & Evals (LangSmith)

Every graph run and LLM call is traced when tracing is enabled — each trace is named/tagged per
wizard stage and carries `session_id`, `dish`, `servings`, etc. in its metadata.

```bash
# enable in .env
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=ls__...
LANGSMITH_PROJECT=quickchef
# US accounts (default): https://api.smith.langchain.com
# EU accounts must add: LANGSMITH_ENDPOINT=https://eu.api.smith.langchain.com
```

`GET /api/health` reports `tracing: true/false`. Then run the evaluation suite, which creates a
LangSmith dataset of dish/servings cases (including modifications) and scores the resolver with
rule-based evaluators (must-include / must-exclude / min-steps):

```bash
python -m evals.run_evals
```

The experiment appears under the `quickchef` project in LangSmith.

### Golden dataset

`evals/golden/cases.jsonl` is the curated regression suite: **77 cases** across `dish`, `recipe`,
`suggest`, `cart`, `flow`, `photo`, and `edge`. Each case declares an `input`, rule-based `expect` checks,
and a `mode`:

```bash
# Deterministic gate (LLM disabled, no network); count comes from the manifest
python -m evals.run_golden

# Full live suite (Groq + Wikimedia; expect occasional 429 retries)
python -m evals.run_golden --live

# Focused runs / baselines
python -m evals.run_golden --suite dish --suite recipe --live
python -m evals.run_golden --write-baseline evals/baselines/offline.json
python -m evals.run_golden --suite dish --live --baseline evals/baselines/dish-live.json
```

The runner isolates synonym/photo state in a temp directory and clears the recipe cache before
each case, so live results cannot leak into offline cases and your local `data/` or
`static/dish_photos/` cache is never polluted. `pytest` includes the offline gate plus loader, manifest,
and evaluator checks. Committed baselines live in `evals/baselines/`:
`offline.json`, `dish-live.json`, `recipe-live.json`, `flow-live.json`, `photo-live.json`.

### Feedback queue → golden cases

The UI captures two kinds of signal without blocking the flow:

- **Not this dish** (`dish_rejected`) and the dish the user ultimately accepts
  (`dish_correction`, linked by `parent_id`).
- **Overall recipe + basket** like/dislike on Review; dislikes are marked `needs_review` and
  store the current recipe and cart snapshot.

Events append to `evals/golden/feedback.jsonl` (gitignored). The curated `cases.jsonl` is only
changed after review:

```bash
python -m evals.promote_feedback --summary   # counts by kind / pending review
python -m evals.promote_feedback --list      # inspect captured events
# promote a rejection as a dish case
python -m evals.promote_feedback --id fb_abc123 --expect-display "Chole Kulche" --out /tmp/case.json
# review a dislike and promote it as a recipe case (append updates manifest counts)
python -m evals.promote_feedback --id fb_def456 --suite recipe \
  --expect-json '{"must_include": [["rajma", "kidney"]], "min_steps": 3}' --append
# replay captured dish feedback against the current resolver
python -m evals.run_feedback --kind dish_rejected --offline
```

Do not commit the raw queue. Promotion is intentionally manual so bad LLM judgments never become
regression expectations automatically.

---

## How the agent works

1. **understand** — extract `dish` and `servings`; canonicalize catalogue dishes, and for unknown
   names ask the LLM for plausible catalogue candidates. Regular uncatalogued dishes are rejected
   before recipe generation; the explicit custom path may continue so the LLM can create a new dish.
   Learned user corrections short-circuit the LLM.
2. **confirm / ask_dish / ask_servings** — regular catalogue selections advance immediately; only a
   custom dish waits on a confirmation preview. Missing input is prompted as before.
3. **extract** — produce a scaled ingredient list **and cooking steps** (LLM structured output, or fallback corpus).
4. **match** — resolve each ingredient to a SKU and pick the cheapest covering pack.
5. **cart_review** — `interrupt()` pauses for human review; cart edited via REST (wizard step 3).
6. **place_order** — on payment, record the method, create the order, emit a bill, clear the cart.

---

## Scope & Limitations

- Mock in-memory catalog & state (no database; restart clears sessions).
- No real payment gateway (UPI/Card/COD are mock) and no Blinkit/Zepto integration.
- Recipe quality depends on the LLM; the offline corpus covers a limited set of dishes and cannot
  apply dish modifications (it builds the closest base recipe and shows a notice). New catalogue
  dishes such as Paneer Tikka and soy chaap need the LLM; they are rejected cleanly offline. Kala
  Chana, Pumpkin Sabzi, and Maggi Noodles are also LLM-only and have no offline fallback.
- A custom dish can be a genuinely new recipe only when the LLM is enabled. Without a key, custom
  dishes that are not in the catalogue are rejected cleanly.
- Custom photos are best-effort Wikimedia Commons matches, cached locally with attribution. Titles
  are scored against dish tokens and images are rejected for people/decorations, weak overlap, low
  resolution, or extreme aspect ratios. A missing photo leaves the confirmation text-only; normal
  catalogue dishes never request one.
- Learned synonyms live in the gitignored `data/synonyms.json`; there is no UI yet to review or delete them.
- Captured feedback is local JSONL with no review UI; use the promotion CLI. Events contain the
  dish text and recipe/cart snapshot but no account or payment data.
- Dish typeahead, custom-dish photo preview, and the logo reset are responsive but only manually
  tested in a browser.

---

## Documents

- [`docs/SRS.md`](docs/SRS.md) — Software Requirements Specification
- [`docs/HLD.md`](docs/HLD.md) — High-Level Design
- [`docs/LLD.md`](docs/LLD.md) — Low-Level Design
