# Software Requirements Specification (SRS)

**Project:** QuickChef — Recipe-to-Cart Shopping Agent
**Version:** 2.0
**Status:** Approved for implementation
**Standard:** IEEE 830-style
**Date:** 2026-10-21

---

## 1. Introduction

### 1.1 Purpose
This document specifies the functional and non-functional requirements for **QuickChef**, an
AI shopping agent for a quick-commerce grocery platform (modelled on Blinkit/Zepto/Instamart).
QuickChef lets a user describe a dish they want to cook and the number of people they are
cooking for; the agent then researches the recipe, converts it into purchasable grocery items,
and automatically fills the user's cart. The user reviews the cart (human-in-the-loop), may add
or remove items, and places the order.

### 1.2 Scope
QuickChef is a demonstration-grade system consisting of:
- A **4-step wizard UI**: (1) Dish → (2) Servings → (3) Review (recipe + cart + bill) → (4) Payment.
- A **live dish typeahead** over a curated catalogue, a custom-dish escape hatch, and a canonical
  confirmation card without photos.
- **Catalogue-only recipe generation** with explicit rejection of uncatalogued dishes.
- **Ambiguity handling** via catalogue candidates and a local learned-synonym store.
- A wizard-driven agent backend that collects the **dish** and **servings**.
- A recipe resolver that converts a dish + servings into a structured ingredient list, quantities, and **cooking steps**.
- A catalog matcher that maps ingredients to real SKUs (with pack sizes and prices).
- A cart service supporting add / update / remove / totals.
- A human-in-the-loop review step followed by **mock payment** and order placement.
- A web interface and a REST API.

**In scope:** recipe resolution via LLM, in-memory mock catalog, cart management, HITL review, mock payment (UPI/Card/COD), order placement, session management, multi-step wizard UI.

**Out of scope:** real payment gateways, real Blinkit/Zepto API integration, authentication/authorization, persistent order storage, delivery logistics, mobile apps.

### 1.3 Definitions, Acronyms and Abbreviations
| Term | Definition |
|------|------------|
| Agent | The LangGraph-based state machine that performs recipe research and cart building |
| Dish | The food item the user wants to cook (e.g. "Dal Makhani") |
| Servings | Number of people the user is cooking for |
| Ingredient | A recipe component (e.g. "Onion", 200 g) |
| SKU / Product | A purchasable catalog item (e.g. "Onion", 500 g pack, ₹35) |
| Pack | A unit of purchase for a SKU (size + unit + price) |
| Cart | The set of products the user intends to buy |
| HITL | Human-in-the-loop: a checkpoint where a human reviews/edits before continuing |
| Interrupt | LangGraph mechanism that pauses graph execution and persists state |
| LLM | Large Language Model (Groq-hosted) |
| Session | A single user conversation/order flow identified by `session_id` |

### 1.4 References
- IEEE Std 830-1998, Recommended Practice for Software Requirements Specifications.
- LangGraph documentation — https://langchain-ai.github.io/langgraph/
- FastAPI documentation — https://fastapi.tiangolo.com/
- Groq API — https://console.groq.com/docs
- Wikimedia Commons API — https://commons.wikimedia.org/w/api.php

### 1.5 Overview
Section 2 describes the product. Section 3 enumerates functional requirements. Section 4 covers
external interfaces. Section 5 covers non-functional requirements. Section 6 provides use cases
and Section 7 the acceptance criteria and traceability matrix.

---

## 2. Overall Description

### 2.1 Product Perspective
QuickChef is a standalone web application. It simulates the "recipe-aware cart building" layer of a
quick-commerce app. It may later be embedded behind the search bar of a real commerce app. It has
no dependency on any proprietary API: recipes come from an LLM (with an offline fallback corpus)
and the catalog is a bundled mock dataset.

### 2.2 Product Functions (summary)
1. Guide the user through a **4-step wizard**: Dish → Servings → Review → Payment.
2. Collect the dish name with **live catalogue suggestions**, then show a no-photo confirmation card once it is understood.
3. Collect the number of servings via a **slider** (1–20, default 4) or a typed value (up to 100).
4. Resolve the recipe (ingredients + scaled quantities + cooking steps).
5. Match each ingredient to a catalog SKU and choose pack sizes.
6. Populate the cart and display the recipe alongside editable ingredient cards.
7. Present the cart for human review (add / remove / change quantity) with a live bill.
8. Accept a mock payment method and place the order with a bill summary.

### 2.3 User Characteristics
- **End user (primary):** A home cook who knows what they want to cook but not what groceries to buy. Expects a fast, guided wizard (dish → servings → review → payment). No technical knowledge required.
- **Demo evaluator / developer:** Runs the app locally, may inspect API and logs.

### 2.4 Constraints
- CON-1: Blinkit/Zepto expose no public ordering API; the catalog is therefore a local mock.
- CON-2: Recipe quality and coverage depend on the LLM; an offline fallback corpus covers common dishes for keyless operation.
- CON-3: State is held in memory; restarting the server clears sessions.
- CON-4: Ordered quantities are always whole packs (retail constraint).
- CON-5: The optional backend photo service depends on Wikimedia Commons availability; the wizard itself must not depend on photos.

### 2.5 Assumptions and Dependencies
- ASM-1: The user provides a recognizable dish name; ambiguous names can be clarified by choosing a catalogue candidate, and custom dishes must still resolve to a catalogue entry.
- ASM-4: Wikimedia Commons can be reached when the optional backend photo service is used; the wizard does not call it.
- ASM-2: The LLM (when enabled) returns well-structured ingredient data.
- ASM-3: The mock catalog is representative enough for the dishes under evaluation.
- DEP-1: Python 3.11+ runtime; internet access only when an LLM is enabled.

---

## 3. Functional Requirements

Requirement IDs: **FR-<group>.<n>**. Priority: M = Mandatory, S = Should, C = Could.

### 3.1 Session, State & Navigation
| ID | Requirement | Priority |
|----|-------------|----------|
| FR-1.1 | The system SHALL create a unique session on demand and return a `session_id`. | M |
| FR-1.2 | The system SHALL maintain conversation state (dish, servings, stage, cart, steps) per session. | M |
| FR-1.3 | The system SHALL expose the current session state (dish, servings, cart, recipe, paused) for UI rendering. | M |
| FR-1.4 | The system SHALL handle a health/readiness check endpoint. | S |
| FR-1.5 | The UI SHALL present a linear 4-step wizard (Dish → Servings → Review → Payment) with a progress stepper. | M |
| FR-1.6 | The system SHALL reset any paused HITL state before rebuilding a cart so the user can go back and change servings. | M |

### 3.2 Dish & Servings Collection (Wizard Steps 1–2)
| ID | Requirement | Priority |
|----|-------------|----------|
| FR-2.1 | The system SHALL normalize the dish name from the user's input. | M |
| FR-2.2 | On the dish step the system SHALL confirm the understood dish with a no-photo card showing the canonical display name and explicit continue/change actions. | M |
| FR-2.7 | The system SHALL return up to three plausible catalog candidates for ambiguous names instead of silently remapping them. | M |
| FR-2.8 | The user SHALL be able to choose a candidate; the system SHALL learn the correction for future lookups. | M |
| FR-2.9 | The system SHALL NOT call the LLM when a learned correction already exists for the exact dish term. | S |
| FR-2.10 | The system SHALL retain an optional attributed photo API, but the wizard SHALL NOT request or display dish photos. | S |
| FR-2.11 | The system SHALL provide live dish suggestions from the curated catalogue as the user types, using AND semantics for multiple words. | M |
| FR-2.12 | The system SHALL allow a custom-dish path, but SHALL reject any dish that is not in the curated catalogue with HTTP 422 and SHALL NOT generate a recipe for it. | M |
| FR-2.3 | The servings step SHALL default to 4 and allow selection from 1–20 via a slider. | M |
| FR-2.4 | The servings step SHALL allow typing an exact value from 1–100. | S |
| FR-2.5 | The system SHALL accept the dish and servings together when entering the servings step. | M |
| FR-2.6 | If the dish is not in the catalogue at the servings step, the system SHALL return HTTP 422 and route the user back to the dish step before any recipe generation. | M |

### 3.3 Recipe Resolution (Step 3a)
| ID | Requirement | Priority |
|----|-------------|----------|
| FR-3.1 | The system SHALL obtain the complete ingredient list for the dish. | M |
| FR-3.2 | The system SHALL scale ingredient quantities for the requested servings. | M |
| FR-3.3 | Ingredient quantities SHALL be numeric with a unit (g, kg, ml, l, pc, tsp, tbsp, cup, pinch). | M |
| FR-3.4 | If no recipe can be produced, the system SHALL inform the user and re-prompt for a dish without creating a cart. | M |
| FR-3.5 | The system SHALL operate without an LLM key using an offline recipe corpus for supported dishes. | S |
| FR-3.6 | The system SHALL resolve a complete recipe (ingredients + scaled quantities + ordered cooking steps) in a single call given dish and servings. | M |
| FR-3.7 | The recipe SHALL include 3–8 ordered cooking steps as text. | S |

### 3.4 Catalog Matching & Cart Building (Step 3b)
| ID | Requirement | Priority |
|----|-------------|----------|
| FR-4.1 | The system SHALL match each ingredient to a catalog product using exact names, aliases, and strict token coverage; weak or partial overlaps SHALL be rejected. | M |
| FR-4.2 | The system SHALL select whole pack(s) that satisfy the required quantity. | M |
| FR-4.3 | Pack selection SHALL minimize total cost, breaking ties by minimizing over-supply. | M |
| FR-4.4 | The system SHALL add matched items to the session cart. | M |
| FR-4.5 | The system SHALL report ingredients it could not match. | S |
| FR-4.6 | Unmatched ingredients SHALL NOT block cart creation. | M |
| FR-4.7 | Pantry items such as water and ice SHALL be reported separately and SHALL NOT be added to the cart. | S |

### 3.5 Human-in-the-Loop Cart Review (Wizard Step 3)
| ID | Requirement | Priority |
|----|-------------|----------|
| FR-5.1 | After building the cart the agent SHALL pause and present the cart for review. | M |
| FR-5.2 | The user SHALL be able to add a product (with quantity) to the cart. | M |
| FR-5.3 | The user SHALL be able to change the quantity of a cart item. | M |
| FR-5.4 | The user SHALL be able to remove a cart item. | M |
| FR-5.5 | The user SHALL be able to search the catalog to find items to add. | S |
| FR-5.6 | The system SHALL recompute totals after every cart change. | M |
| FR-5.7 | The agent SHALL remain paused (ignore new recipe requests) until the user confirms or cancels. | M |
| FR-5.8 | The user SHALL be able to cancel the pending order. | S |
| FR-5.9 | The review step SHALL display the full recipe (ingredient list and cooking steps) alongside the cart. | M |

### 3.6 Payment & Order Placement (Wizard Step 4)
| ID | Requirement | Priority |
|----|-------------|----------|
| FR-6.1 | On payment the system SHALL create an order with a unique order id. | M |
| FR-6.2 | The order SHALL include items, subtotal, delivery fee, handling fee and total. | M |
| FR-6.3 | The system SHALL empty the cart after successful placement. | M |
| FR-6.4 | The system SHALL reject order placement on an empty cart. | M |
| FR-6.5 | The system SHALL present a human-readable bill summary after placement. | M |
| FR-6.6 | The payment step SHALL offer mock methods (UPI, Card, Cash on Delivery). | M |
| FR-6.7 | The order SHALL record the selected payment method and a delivery address. | S |
| FR-6.8 | The system SHALL confirm success with the order id and total paid. | M |

### 3.7 Pricing Rules
| ID | Requirement | Priority |
|----|-------------|----------|
| FR-7.1 | Subtotal SHALL equal the sum of (unit pack price × pack count) for all items. | M |
| FR-7.2 | Delivery fee SHALL be ₹25, waived for subtotals ≥ ₹199. | M |
| FR-7.3 | A handling fee of ₹9 SHALL apply to non-empty carts. | M |

---

## 4. External Interface Requirements

### 4.1 User Interfaces
- **UI-1:** Browser-based single page implementing a 4-step wizard with a progress stepper: **Dish → Servings → Review → Payment**.
- **UI-2:** Step 1 (Dish) — text input with live catalogue suggestions, keyboard navigation, a final “Something else” custom-dish option, and quick-pick chips; shows a no-photo confirmation card with the canonical name, **Continue / Change dish**, candidate cards for ambiguous names, or an inline error plus toast for uncatalogued dishes.
- **UI-3:** Step 2 (Servings) — slider (1–20, default 4), an optional exact-number input (1–100), and a Confirm action.
- **UI-4:** Step 3 (Review) — a full recipe card (ingredients + cooking steps) beside the cart, with per-item quantity controls, a Remove action, and a catalog search to add items. Unmatched ingredients are shown as a notice.
- **UI-5:** Step 3 shows subtotal, delivery, handling and total with a live bill, plus **Cancel order** and **Proceed to Payment** actions.
- **UI-8:** Step 3 shows an overall **recipe + basket feedback** bar (like / dislike). Feedback is best-effort and never blocks cart editing or payment.
- **UI-6:** Step 4 (Payment) — mock method selection (UPI / Card / COD), a delivery **address** field (default "Home"), and an order summary; succeeds to a confirmation screen with the order id.
- **UI-7:** A post-order screen shows the order id, method, and bill summary with a "Start a new order" action.

### 4.2 Software Interfaces (REST API)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Serve the web UI |
| GET | `/api/health` | Health/readiness + LLM status |
| POST | `/api/session` | Create a session |
| GET | `/api/session/{session_id}` | Fetch current session state (dish, servings, stage, cart, recipe, paused) |
| GET | `/api/dish/suggest?q=&limit=` | Deterministic catalogue typeahead with AND semantics |
| POST | `/api/dish/{session_id}` | Resolve/confirm the dish `{dish, custom?}`; returns candidates or HTTP 422 when uncatalogued |
| GET | `/api/dish/photo?dish=` | Optional attributed photo backend; not used by the wizard |
| POST | `/api/synonyms` | Learn a user dish correction `{term, canonical}` |
| POST | `/api/feedback/{session_id}` | Capture `dish_rejected`, `dish_correction`, `review_liked`, or `review_disliked` (best-effort) |
| POST | `/api/servings/{session_id}` | Resolve recipe for dish + servings and build the cart (wizard step 2) |
| POST | `/api/chat/{session_id}` | Send a user message; run the agent (legacy/conversational) |
| GET | `/api/cart/{session_id}` | Fetch cart items + totals |
| POST | `/api/cart/{session_id}/items` | Add a product to the cart |
| PATCH | `/api/cart/{session_id}/items/{product_id}` | Update item quantity |
| DELETE | `/api/cart/{session_id}/items/{product_id}` | Remove an item |
| POST | `/api/order/{session_id}/pay` | Apply mock payment method and place the order |
| POST | `/api/cart/{session_id}/confirm` | Confirm and place the order |
| POST | `/api/cart/{session_id}/cancel` | Cancel the pending order |
| GET | `/api/orders/{session_id}` | List session orders |
| GET | `/api/catalog/search` | Search catalog products |

### 4.3 Communication Interfaces
- HTTP/1.1, JSON request/response bodies.
- Optional outbound HTTPS to the Groq API when an LLM key is configured.
- Optional outbound HTTPS to Wikimedia Commons for the retained backend photo API; the wizard does
  not call it.

---

## 5. Non-Functional Requirements

| ID | Category | Requirement |
|----|----------|-------------|
| NFR-1 | Performance | Non-LLM operations (cart read/write, search) SHALL respond in < 200 ms locally. |
| NFR-2 | Performance | Recipe resolution with LLM SHOULD complete within ~10 s; learned corrections and cached recipes SHOULD return in < 1 s. |
| NFR-3 | Reliability | The system SHALL operate in offline mode (no LLM key) for supported dishes. |
| NFR-4 | Usability | The user SHALL be able to build a cart in ≤ 2 wizard steps (dish + servings). |
| NFR-5 | Correctness | Quantities SHALL always be satisfied; over-supply is permitted, under-supply is not. |
| NFR-6 | Maintainability | Catalog/product data SHALL be externalized (JSON), not hardcoded in logic. |
| NFR-7 | Portability | The system SHALL run on Python 3.11+ on Windows/Linux/macOS. |
| NFR-8 | Testability | Core logic SHALL be unit-testable without network access. |
| NFR-9 | Security | API keys SHALL be read from environment variables and never logged or committed. |
| NFR-10 | Observability | The system SHALL expose a health endpoint and process logs. |
| NFR-11 | Resilience | Optional backend photo lookup failures SHALL NOT block dish confirmation; failed lookups SHALL be retried after a short backoff window. The wizard does not depend on photos. |
| NFR-12 | Regression | The system SHALL include a deterministic offline golden dataset and a live suite for LLM/photo paths. |
| NFR-13 | Resilience | Feedback capture SHALL be best-effort; a disabled queue or storage failure SHALL NOT block dish confirmation, cart review, or payment. |

---

## 6. Use Cases

### UC-1: Build cart from a recipe via the wizard (primary success scenario)
**Actor:** Home cook · **Preconditions:** App running.
1. **Step 1 — Dish:** User types "Dal Makhani" (or picks a live suggestion/chip). System resolves it and shows the no-photo confirmation card. User taps **Continue**.
2. **Step 2 — Servings:** User sets servings to 4 (slider or typed). System resolves the recipe (ingredients + steps), scales to 4, matches each ingredient to a SKU, selects packs, and fills the cart.
3. **Step 3 — Review:** System shows the full recipe (ingredients + cooking steps) beside editable ingredient cards and a live bill (**HITL**). User optionally adds/removes/updates items.
4. **Step 4 — Payment:** User selects a mock method (UPI/Card/COD) and pays.
5. System places the order, shows a confirmation with the order id, and clears the cart.

**Postcondition:** An order exists for the session; cart is empty.

### UC-2: Add an extra item during review
Extends UC-1 step 3. User searches "milk", selects a product, quantity 2; totals update.

### UC-3: Remove an item during review
Extends UC-1 step 3. User removes a matched ingredient; totals update.

### UC-4: Go back and change servings
Extends UC-1. After the cart is built the user returns to Step 2 and changes servings; the system resets the pending review and rebuilds the cart for the new servings without duplication.

### UC-5: Unrecognized dish
1. User types "Unicorn stew." 2. The system rejects the uncatalogued dish immediately (HTTP 422) and shows a clear message; no recipe LLM call or cart is created.

### UC-6: Cancel the pending order
Extends UC-1 step 3. The user clicks **Cancel order**; the system resumes the paused agent with `cancel`, discards the review, and returns the user to Step 1 with a fresh session. No order is created.

### UC-7: Some ingredients cannot be matched
Extends UC-1 step 3. The recipe contains an ingredient not present in the catalog; the system surfaces it on the Review screen ("We couldn't match: …") and the user adds a substitute manually. Cart creation is not blocked.

### UC-8: Ambiguous dish is clarified
1. User enters "Matar Kulcha".
2. System keeps the canonical name and returns candidate "Chole Kulche" with `needs_clarification=true`.
3. The card asks "Did you mean…"; the user picks a candidate (the correction is learned) or rejects the card and retypes.
4. The wizard proceeds only after an explicit confirmation; no silent remapping occurs.

### UC-9: Optional backend photo unavailable
The wizard no longer displays dish photos. A direct call to `/api/dish/photo` may still return
`kind:none` for an uncached or unsafe match; this never blocks dish confirmation or cart building.

### UC-10: Capture dish feedback for golden-dataset review
1. On the confirmation card the user taps **Not this dish**; the system appends a `dish_rejected` event with the raw input, suggestion, candidates, and source.
2. If the user then picks a candidate or confirms a corrected dish, the system appends a linked `dish_correction` event (`parent_id`).
3. Reviewing the cart, the user taps like or dislike; the system appends an overall recipe + basket snapshot. Dislikes are marked for review.
4. Operators later inspect the queue and promote selected events into curated golden cases. Capture failures are surfaced only as `stored:false` and never interrupt shopping.

---

## 7. Acceptance Criteria & Traceability

| AC | Criterion | Traces to |
|----|-----------|-----------|
| AC-1 | Given dish "Dal Makhani" and 4 servings, the cart contains ≥ 10 items and the agent pauses for review. | FR-2.1, FR-3.1, FR-4.1, FR-5.1 |
| AC-2 | The cart total equals subtotal + applicable fees, and delivery is free when subtotal ≥ ₹199. | FR-6.2, FR-7.2 |
| AC-3 | Adding a product via UI/API increases item count and total. | FR-5.2, FR-5.6 |
| AC-4 | Changing quantity to 0 removes the item. | FR-5.3, FR-5.4 |
| AC-5 | Paying creates an order (id prefix `QC`), records the method, clears the cart, and returns a bill. | FR-6.1, FR-6.3, FR-6.7 |
| AC-6 | Placing an order on an empty cart returns an error. | FR-6.4 |
| AC-7 | An uncatalogued dish yields HTTP 422 at the dish step, no recipe LLM call, and no order. | FR-3.4, FR-2.6, FR-2.12, UC-5 |
| AC-8 | The system resolves aliases (e.g. "pyaz" → Onion) and fuzzy dish names ("dal makhni" → Dal Makhani). | FR-4.1, FR-3.5 |
| AC-9 | With no LLM key, supported dishes still produce a cart and recipe. | NFR-3, FR-3.5 |
| AC-10 | All unit tests pass without network access. | NFR-8 |
| AC-11 | The recipe returned includes ≥ 3 ordered cooking steps. | FR-3.6, FR-3.7 |
| AC-12 | After building a cart, changing servings and resubmitting rebuilds the cart for the new servings. | FR-1.6, UC-4 |
| AC-13 | The UI renders four wizard steps and advances 1→2 on a confirmed dish. | FR-1.5, FR-2.2 |
| AC-14 | Cancelling a pending order returns HTTP 200 (`stage=cancelled`); cancelling when not paused returns HTTP 400. | FR-5.8, UC-6 |
| AC-15 | The `/api/servings` response includes an `unmatched` list; unmatched ingredients are shown on the Review screen. | FR-4.5, UC-7 |
| AC-16 | Paying with an address records that address on the order. | FR-6.7 |
| AC-17 | An ambiguous dish returns candidates and requires explicit confirmation; learned choices are reused without an LLM call. | FR-2.7, FR-2.8, FR-2.9, UC-8 |
| AC-18 | The confirmation card shows no photo and never calls the photo API; the optional backend photo endpoint still works independently. | FR-2.10, NFR-11, UC-9 |
| AC-19 | The offline golden dataset passes deterministically with no network access; its count matches the manifest. | NFR-12, NFR-8 |
| AC-20 | A dish rejection/correction and a review dislike are appended to the feedback queue with the expected fields; a write failure returns `stored:false` without blocking the flow. | NFR-13, UC-10 |
| AC-21 | A recipe containing kale leaves, dry chickpeas, and water never matches coriander leaves, chana dal, or rose water; water is excluded from the cart. | FR-4.1, FR-4.7 |
| AC-22 | If the optional backend photo API is called, Maggi/Pumpkin resolve to relevant images (never a person or decorative item) and weak matches return `{kind:"none"}`. | FR-2.10, NFR-11 |
| AC-23 | Typing `malai chaap` returns only Malai Soy Chaap; `chaap` returns all chaap variants; `paneer` returns paneer dishes. | FR-2.11, UC-8 |
| AC-24 | A custom dish that is not in the catalogue yields HTTP 422, while a custom known dish resolves and proceeds. | FR-2.12, UC-5 |

---

*End of SRS.*
