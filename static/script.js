const state = {
  sessionId: null,
  dish: null,
  display: null,
  rawDish: null,
  dishContext: null,
  rejectionPromise: null,
  rejectionContext: null,
  reviewFeedbackSent: false,
  candidates: [],
  custom: false,
  servings: 4,
  cart: { items: [], totals: {} },
  recipe: null,
  paused: false,
  maxStep: 1,
};

const el = (id) => document.getElementById(id);
const screens = { 1: el("screen-1"), 2: el("screen-2"), 3: el("screen-3"), 4: el("screen-4"), done: el("screen-done") };
const steps = Array.from(document.querySelectorAll(".step"));

let currentStep = null;
let bumpProductId = null;
let lastTotal = null;

/* ---------- utils ---------- */
async function api(path, options = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.message || data.detail || `Request failed (${res.status})`);
  return data;
}

async function captureFeedback(payload) {
  if (!state.sessionId) return null;
  try {
    return await api(`/api/feedback/${state.sessionId}`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  } catch (err) {
    console.warn("feedback:", err.message);
    return null;
  }
}

async function linkRejection(acceptedRaw, acceptedDish, acceptedDisplay) {
  const pending = state.rejectionPromise;
  if (!pending) return;
  const rejected = state.rejectionContext || {};
  state.rejectionPromise = null;
  state.rejectionContext = null;
  const res = await pending;
  if (!res?.stored || !res.id) return;
  await captureFeedback({
    kind: "dish_correction",
    parent_id: res.id,
    raw: rejected.raw,
    dish: rejected.dish,
    accepted_raw: acceptedRaw,
    accepted_dish: acceptedDish,
    accepted_display: acceptedDisplay,
  });
}

function resetReviewFeedback() {
  state.reviewFeedbackSent = false;
  const like = el("review-like");
  const dislike = el("review-dislike");
  like.disabled = false;
  dislike.disabled = false;
  like.classList.remove("selected");
  dislike.classList.remove("selected");
  el("review-feedback-status").textContent = "";
}

const inr = (n) => "₹" + Number(n).toFixed(0);
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function restartAnim(node, cls) {
  if (!node) return;
  node.classList.remove(cls);
  void node.offsetWidth;
  node.classList.add(cls);
}

function showStep(n) {
  const goingBack = typeof n === "number" && typeof currentStep === "number" && n < currentStep;
  Object.values(screens).forEach((s) => {
    s.classList.remove("active");
    s.classList.remove("dir-back");
  });
  const key = typeof n === "number" ? n : "done";
  const target = screens[key];
  if (goingBack) target.classList.add("dir-back");
  target.classList.add("active");
  if (typeof n === "number") {
    state.maxStep = Math.max(state.maxStep, n);
  }
  currentStep = n;
  steps.forEach((s) => {
    const sn = Number(s.dataset.step);
    const isActive = sn === n;
    s.classList.toggle("active", isActive);
    s.classList.toggle("done", typeof n === "number" ? sn < n : true);
    if (isActive) s.setAttribute("aria-current", "step");
    else s.removeAttribute("aria-current");
  });
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function setFeedback(node, html, kind = "") {
  node.className = "feedback" + (kind ? " " + kind : "");
  node.innerHTML = html;
}

/* ---------- session ---------- */
async function newSession() {
  const data = await api("/api/session", { method: "POST" });
  state.sessionId = data.session_id;
}

/* ---------- STEP 1 ---------- */
const dishInput = el("dish-input");
const customInput = el("custom-dish-input");
const suggestionsBox = el("dish-suggestions");
let suggestTimer = null;
let suggestToken = 0;
let activeSuggestion = -1;
let toastTimer = null;

function clearDishConfirm() {
  el("dish-confirm").classList.add("hidden");
  el("dc-candidate-list").innerHTML = "";
  el("dc-candidates").classList.add("hidden");
  state.candidates = [];
}

function showDishToast(message) {
  const toast = el("dish-toast");
  toast.textContent = message;
  toast.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.add("hidden"), 5200);
}

function hideSuggestions() {
  suggestionsBox.classList.add("hidden");
  suggestionsBox.innerHTML = "";
  dishInput.setAttribute("aria-expanded", "false");
  dishInput.removeAttribute("aria-activedescendant");
  activeSuggestion = -1;
}

function hideCustomDish() {
  state.custom = false;
  el("custom-dish-wrap").classList.add("hidden");
  customInput.value = "";
}

function setActiveSuggestion(index) {
  const options = Array.from(suggestionsBox.querySelectorAll(".dish-suggestion"));
  if (!options.length) return;
  activeSuggestion = (index + options.length) % options.length;
  options.forEach((option, i) => {
    const active = i === activeSuggestion;
    option.classList.toggle("active", active);
    if (active) {
      dishInput.setAttribute("aria-activedescendant", option.id);
      option.scrollIntoView({ block: "nearest" });
    }
  });
}

function chooseSuggestion(name) {
  dishInput.value = name;
  hideSuggestions();
  hideCustomDish();
  submitDish(name);
}

function openCustomDish() {
  hideSuggestions();
  clearDishConfirm();
  state.dish = null;
  state.display = null;
  state.rawDish = null;
  dishInput.value = "";
  el("dish-feedback").innerHTML = "";
  state.custom = true;
  el("custom-dish-wrap").classList.remove("hidden");
  customInput.value = "";
  customInput.focus();
}

function renderSuggestions(names) {
  suggestionsBox.innerHTML = "";
  names.forEach((name, index) => {
    const option = document.createElement("button");
    option.type = "button";
    option.className = "dish-suggestion";
    option.id = `dish-option-${index}`;
    option.setAttribute("role", "option");
    option.innerHTML = `<span>${esc(name)}</span><span class="suggestion-hint">Use this dish</span>`;
    option.addEventListener("mousedown", (event) => {
      event.preventDefault();
      chooseSuggestion(name);
    });
    suggestionsBox.appendChild(option);
  });

  const custom = document.createElement("button");
  custom.type = "button";
  custom.className = "dish-suggestion custom";
  custom.id = `dish-option-${names.length}`;
  custom.setAttribute("role", "option");
  custom.innerHTML = `<span><span class="plus">+</span> Something else / Add a different dish</span><span class="suggestion-hint">Not listed</span>`;
  custom.addEventListener("mousedown", (event) => {
    event.preventDefault();
    openCustomDish();
  });
  suggestionsBox.appendChild(custom);

  activeSuggestion = -1;
  suggestionsBox.classList.remove("hidden");
  dishInput.setAttribute("aria-expanded", "true");
}

async function loadSuggestions() {
  if (state.custom) return;
  const token = ++suggestToken;
  try {
    const data = await api(`/api/dish/suggest?q=${encodeURIComponent(dishInput.value.trim())}&limit=8`);
    if (token !== suggestToken) return;
    renderSuggestions((data.results || []).map((item) => item.name));
  } catch (err) {
    if (token !== suggestToken) return;
    console.warn("suggest:", err.message);
    hideSuggestions();
  }
}

function renderDishCandidates(candidates) {
  const list = el("dc-candidate-list");
  list.innerHTML = "";
  state.candidates = candidates || [];
  if (!state.candidates.length) {
    el("dc-candidates").classList.add("hidden");
    return;
  }
  el("dc-candidates").classList.remove("hidden");
  state.candidates.slice(0, 3).forEach((candidate) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "dc-candidate";
    button.innerHTML = `
      <span class="dc-candidate-name">${esc(candidate.name)}</span>
      ${candidate.description ? `<span class="dc-candidate-desc">${esc(candidate.description)}</span>` : ""}`;
    button.addEventListener("click", () => selectCandidate(candidate.name, button));
    list.appendChild(button);
  });
}

async function selectCandidate(name, button) {
  state.dish = name;
  state.display = name;
  dishInput.value = name;
  void linkRejection(state.rawDish, name, name);
  el("dc-name").textContent = name;
  el("dc-desc").textContent = "We'll use this dish for your recipe.";
  el("dc-eyebrow").textContent = "Confirm your dish";
  document.querySelectorAll(".dc-candidate").forEach((item) => item.classList.toggle("selected", item === button));
  el("servings-dish-label").innerHTML = `Cooking <b>${esc(name)}</b>`;
  if (state.rawDish) {
    try {
      await api("/api/synonyms", {
        method: "POST",
        body: JSON.stringify({ term: state.rawDish, canonical: name }),
      });
    } catch (err) {
      console.warn("synonym:", err.message);
    }
  }
}

function showDishConfirm(data) {
  state.rawDish = data.raw || state.rawDish;
  state.dishContext = {
    raw: data.raw || state.rawDish,
    dish: data.dish,
    display: data.display,
    candidates: data.candidates || [],
    needs_clarification: data.needs_clarification,
    modifiers: data.modifiers,
    source: data.source,
  };
  el("dc-eyebrow").textContent = data.candidates?.length ? "Did you mean…" : "Confirm your dish";
  el("dc-name").textContent = data.display || data.dish;
  el("dc-desc").textContent = data.candidates?.length
    ? "Pick the dish you meant, or continue with this one."
    : "We'll build a basket for this dish.";
  el("dish-confirm").classList.remove("hidden");
  renderDishCandidates(data.candidates || []);
}

async function submitDish(raw, custom = false) {
  const feedback = el("dish-feedback");
  const button = el("dish-btn");
  if (button.disabled) return;
  button.disabled = true;
  hideSuggestions();
  clearDishConfirm();
  state.dishContext = null;
  state.rawDish = raw;
  setFeedback(feedback, `<span class="spinner"></span> Finding that dish…`);
  try {
    const data = await api(`/api/dish/${state.sessionId}`, {
      method: "POST",
      body: JSON.stringify({ dish: raw, custom }),
    });
    state.dish = data.dish;
    state.display = data.display;
    state.custom = false;
    hideCustomDish();
    setFeedback(feedback, `<span class="understood"><span class="tick">✓</span> ${esc(data.display)}</span>`);
    showDishConfirm(data);
  } catch (err) {
    setFeedback(feedback, esc(err.message), "error");
    showDishToast(err.message);
  } finally {
    button.disabled = false;
  }
}

el("dc-yes").addEventListener("click", () => {
  if (!state.dish) return;
  void linkRejection(state.rawDish, state.dish, state.display || state.dish);
  state.dishContext = null;
  el("servings-dish-label").innerHTML = `Cooking <b>${esc(state.display || state.dish)}</b>`;
  el("dish-confirm").classList.add("hidden");
  setFeedback(el("dish-feedback"), "");
  showStep(2);
});

el("dc-no").addEventListener("click", () => {
  const rejected = state.dishContext;
  if (rejected) {
    state.rejectionContext = rejected;
    state.rejectionPromise = captureFeedback({ kind: "dish_rejected", ...rejected });
  }
  state.dishContext = null;
  state.dish = null;
  state.display = null;
  state.rawDish = null;
  clearDishConfirm();
  setFeedback(el("dish-feedback"), "No problem — tell me the right dish.");
  dishInput.focus();
  dishInput.select();
  loadSuggestions();
});

el("dish-form").addEventListener("submit", (event) => {
  event.preventDefault();
  if (state.custom) {
    const customValue = customInput.value.trim();
    if (customValue) submitDish(customValue, true);
    return;
  }
  const value = dishInput.value.trim();
  if (value) submitDish(value);
});

dishInput.addEventListener("input", () => {
  if (state.custom) hideCustomDish();
  clearDishConfirm();
  state.dish = null;
  state.display = null;
  state.rawDish = null;
  setFeedback(el("dish-feedback"), "");
  clearTimeout(suggestTimer);
  suggestTimer = setTimeout(loadSuggestions, 160);
});

dishInput.addEventListener("focus", () => {
  if (!state.custom) loadSuggestions();
});

dishInput.addEventListener("keydown", (event) => {
  if (suggestionsBox.classList.contains("hidden")) {
    if (event.key === "ArrowDown") {
      loadSuggestions();
      event.preventDefault();
    }
    return;
  }
  if (event.key === "ArrowDown") {
    event.preventDefault();
    setActiveSuggestion(activeSuggestion + 1);
  } else if (event.key === "ArrowUp") {
    event.preventDefault();
    setActiveSuggestion(activeSuggestion - 1);
  } else if (event.key === "Enter" && activeSuggestion >= 0) {
    event.preventDefault();
    const option = suggestionsBox.querySelectorAll(".dish-suggestion")[activeSuggestion];
    if (option) option.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
  } else if (event.key === "Escape") {
    hideSuggestions();
  }
});

customInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    const value = customInput.value.trim();
    if (value) submitDish(value, true);
  }
});

el("custom-dish-btn").addEventListener("click", () => {
  const value = customInput.value.trim();
  if (value) submitDish(value, true);
});
el("custom-dish-cancel").addEventListener("click", () => {
  hideCustomDish();
  dishInput.value = "";
  dishInput.focus();
  loadSuggestions();
});

document.addEventListener("click", (event) => {
  if (!event.target.closest(".dish-search")) hideSuggestions();
});

document.querySelectorAll(".chip-btn").forEach((button) =>
  button.addEventListener("click", () => {
    dishInput.value = button.dataset.dish;
    hideCustomDish();
    submitDish(button.dataset.dish);
  })
);

/* ---------- popular dish marquee ---------- */
const FOOD_CARDS = [
  { dish: "Garlic Naan", tag: "Breads", art: "naan" },
  { dish: "Paneer Butter Masala", tag: "North Indian", art: "paneer-butter-masala" },
  { dish: "Dal Makhani", tag: "North Indian", art: "dal-makhani" },
  { dish: "Chole Kulche", tag: "Street food", art: "chole-kulche" },
  { dish: "Rajma Chawal", tag: "North Indian", art: "rajma-chawal" },
  { dish: "Aloo Gobi", tag: "North Indian", art: "aloo-gobi" },
  { dish: "Palak Paneer", tag: "North Indian", art: "palak-paneer" },
  { dish: "Veg Biryani", tag: "Rice", art: "veg-biryani" },
  { dish: "Veg Pulao", tag: "Rice", art: "veg-pulao" },
  { dish: "Idli Sambar", tag: "South Indian", art: "idli-sambar" },
  { dish: "Masala Dosa", tag: "South Indian", art: "masala-dosa" },
  { dish: "Pav Bhaji", tag: "Street food", art: "pav-bhaji" },
  { dish: "Pasta", tag: "Italian", art: "pasta" },
  { dish: "Veg Hakka Noodles", tag: "Indo-Chinese", art: "hakka-noodles" },
  { dish: "Rasmalai", tag: "Sweet", art: "rasmalai" },
  { dish: "Gulab Jamun", tag: "Sweet", art: "gulab-jamun" },
];

function foodCardHTML(c, hidden) {
  return `<button type="button" class="food-card" data-dish="${c.dish}"${hidden ? ' aria-hidden="true" tabindex="-1"' : ""}>
    <span class="fthumb"><img src="/static/foods/${c.art}.svg" alt="" loading="lazy" /></span>
    <span class="fname">${c.dish}</span>
    <span class="ftag">${c.tag}</span>
  </button>`;
}

function renderFoodStrip() {
  const track = el("food-track");
  if (!track) return;
  track.innerHTML =
    FOOD_CARDS.map((c) => foodCardHTML(c, false)).join("") +
    FOOD_CARDS.map((c) => foodCardHTML(c, true)).join("");
}

el("food-track").addEventListener("click", async (e) => {
  const card = e.target.closest(".food-card");
  if (!card || card.tabIndex === -1) return;
  if (!state.sessionId) await newSession();
  el("dish-input").value = card.dataset.dish;
  submitDish(card.dataset.dish);
});

/* ---------- STEP 2 ---------- */
const slider = el("servings-slider");
const numberInput = el("servings-number");
const servingsValue = el("servings-value");

function paintSlider() {
  const pct = ((slider.value - slider.min) / (slider.max - slider.min)) * 100;
  slider.style.setProperty("--pct", pct + "%");
}
function setServings(n) {
  n = Math.max(1, Math.min(100, Number(n) || 1));
  const changed = n !== state.servings;
  state.servings = n;
  slider.value = Math.min(20, n);
  numberInput.value = n;
  servingsValue.textContent = n;
  slider.setAttribute("aria-valuetext", `${n} ${n === 1 ? "person" : "people"}`);
  paintSlider();
  if (changed) restartAnim(servingsValue, "pop");
}
slider.addEventListener("input", () => setServings(slider.value));
numberInput.addEventListener("input", () => setServings(numberInput.value));
el("custom-toggle").addEventListener("change", (e) => {
  el("custom-wrap").classList.toggle("hidden", !e.target.checked);
  if (e.target.checked) numberInput.focus();
});

async function submitServings() {
  const fb = el("servings-feedback");
  const btn = el("servings-confirm");
  btn.disabled = true;
  setFeedback(fb, `<span class="spinner"></span> Loading the recipe and building your basket…`);
  try {
    const data = await api(`/api/servings/${state.sessionId}`, {
      method: "POST",
      body: JSON.stringify({ dish: state.dish, servings: state.servings }),
    });
    state.recipe = data.recipe;
    state.cart = data.cart;
    state.paused = data.paused;
    setFeedback(fb, "");
    renderReview();
    showStep(3);
  } catch (err) {
    setFeedback(fb, `⚠ ${err.message}`, "error");
    setTimeout(() => showStep(1), 1600);
  } finally {
    btn.disabled = false;
  }
}
el("servings-confirm").addEventListener("click", submitServings);
el("servings-back").addEventListener("click", () => showStep(1));

/* ---------- STEP 3: review ---------- */
function renderReview() {
  resetReviewFeedback();
  const r = state.recipe || {};
  el("recipe-dish").textContent = state.display || r.dish || "—";
  el("recipe-servings").textContent = `for ${r.servings || state.servings} people`;
  el("recipe-source").textContent = r.source === "offline" ? "Offline recipe" : "AI-generated recipe";

  const modNote = el("modifier-note");
  if (r.notice) {
    modNote.innerHTML = `ℹ ${r.notice}`;
    modNote.classList.remove("hidden");
  } else if (r.modifiers) {
    modNote.innerHTML = "ℹ Modification applied.";
    modNote.classList.remove("hidden");
  } else {
    modNote.classList.add("hidden");
  }

  const ing = el("recipe-ingredients");
  ing.innerHTML = "";
  (r.ingredients || []).forEach((i) => {
    const li = document.createElement("li");
    li.innerHTML = `<b>${i.quantity}${i.unit}</b> ${i.name}`;
    ing.appendChild(li);
  });

  const stepsOl = el("recipe-steps");
  stepsOl.innerHTML = "";
  (r.steps || []).forEach((s) => {
    const li = document.createElement("li");
    li.textContent = s;
    stepsOl.appendChild(li);
  });

  const unmatched = r.unmatched || [];
  const note = el("unmatched-note");
  if (unmatched.length) {
    note.innerHTML = `⚠ We couldn't match: <b>${unmatched.join(", ")}</b> — add them manually below.`;
    note.classList.remove("hidden");
  } else {
    note.classList.add("hidden");
  }

  renderCart();
}

function renderCart() {
  const items = state.cart.items || [];
  const totals = state.cart.totals || {};
  el("cart-count").textContent = `${items.length} item${items.length === 1 ? "" : "s"}`;

  const wrap = el("cart-cards");
  wrap.innerHTML = "";
  if (!items.length) {
    wrap.innerHTML = `<p class="muted">Your basket is empty — add something above.</p>`;
  }
  items.forEach((it) => {
    const card = document.createElement("div");
    card.className = "cart-card";
    if (it.product_id === bumpProductId) card.classList.add("bump");
    card.innerHTML = `
      <div>
        <div class="cname">${it.name}</div>
        <div class="cprice">${inr(it.unit_price)} each</div>
      </div>
      <div class="cfoot">
        <div class="qty">
          <button data-dec="${it.product_id}">−</button>
          <span>${it.quantity}</span>
          <button data-inc="${it.product_id}">+</button>
        </div>
        <span class="cprice">${inr(it.unit_price * it.quantity)}</span>
      </div>
      <button class="rm" data-remove="${it.product_id}">Remove</button>`;
    wrap.appendChild(card);
  });
  bumpProductId = null;

  el("b-subtotal").textContent = inr(totals.subtotal || 0);
  const delivery = totals.delivery_fee || 0;
  const dEl = el("b-delivery");
  dEl.textContent = delivery === 0 && (totals.subtotal || 0) > 0 ? "FREE" : inr(delivery);
  dEl.className = delivery === 0 && (totals.subtotal || 0) > 0 ? "free" : "";
  el("b-handling").textContent = inr(totals.handling_fee || 0);
  const totalEl = el("b-total");
  totalEl.textContent = inr(totals.total || 0);
  if (lastTotal !== null && lastTotal !== (totals.total || 0)) restartAnim(totalEl, "bump");
  lastTotal = totals.total || 0;

  el("to-payment").disabled = items.length === 0;
}

async function refreshCart(changedId = null) {
  bumpProductId = changedId;
  state.cart = await api(`/api/cart/${state.sessionId}`);
  renderCart();
}

el("cart-cards").addEventListener("click", async (e) => {
  const inc = e.target.dataset.inc;
  const dec = e.target.dataset.dec;
  const remove = e.target.dataset.remove;
  const card = e.target.closest(".cart-card");
  const current = card ? parseInt(card.querySelector(".qty span").textContent, 10) : 0;
  try {
    if (inc) await api(`/api/cart/${state.sessionId}/items/${inc}`, { method: "PATCH", body: JSON.stringify({ quantity: current + 1 }) });
    if (dec) await api(`/api/cart/${state.sessionId}/items/${dec}`, { method: "PATCH", body: JSON.stringify({ quantity: current - 1 }) });
    if (remove) await api(`/api/cart/${state.sessionId}/items/${remove}`, { method: "DELETE" });
    await refreshCart(inc || dec || remove);
  } catch (err) {
    console.error(err);
  }
});

let searchTimer = null;
el("add-search").addEventListener("input", () => {
  clearTimeout(searchTimer);
  const q = el("add-search").value.trim();
  const results = el("add-results");
  if (!q) return (results.innerHTML = "");
  searchTimer = setTimeout(async () => {
    const data = await api(`/api/catalog/search?q=${encodeURIComponent(q)}&limit=6`);
    results.innerHTML = "";
    data.results.forEach((p) => {
      const li = document.createElement("li");
      li.innerHTML = `<span>${p.name}</span><span class="meta">${p.pack} · ${inr(p.price)} +</span>`;
      li.addEventListener("click", async () => {
        await api(`/api/cart/${state.sessionId}/items`, { method: "POST", body: JSON.stringify({ product_id: p.id, quantity: 1 }) });
        el("add-search").value = "";
        results.innerHTML = "";
        await refreshCart(p.id);
      });
      results.appendChild(li);
    });
  }, 200);
});

el("review-back").addEventListener("click", () => showStep(2));

async function cancelPendingOrder() {
  if (!state.paused) return;
  try {
    await api(`/api/cart/${state.sessionId}/cancel`, { method: "POST" });
  } catch (err) {
    console.warn("cancel:", err.message);
  }
}

async function resetWizard({ cancelPending = false, focus = false } = {}) {
  if (cancelPending) await cancelPendingOrder();
  state.dish = null;
  state.display = null;
  state.rawDish = null;
  state.recipe = null;
  state.cart = { items: [], totals: {} };
  state.paused = false;
  state.maxStep = 1;
  state.dishContext = null;
  state.rejectionPromise = null;
  state.rejectionContext = null;
  state.candidates = [];
  state.custom = false;
  clearTimeout(suggestTimer);
  hideSuggestions();
  hideCustomDish();
  clearDishConfirm();
  el("dish-input").value = "";
  el("dc-eyebrow").textContent = "Confirm your dish";
  el("dish-feedback").innerHTML = "";
  el("dish-toast").classList.add("hidden");
  el("servings-feedback").innerHTML = "";
  el("add-search").value = "";
  el("add-results").innerHTML = "";
  el("address-input").value = "Home";
  el("custom-toggle").checked = false;
  el("custom-wrap").classList.add("hidden");
  resetReviewFeedback();
  setServings(4);
  await newSession();
  showStep(1);
  if (focus) requestAnimationFrame(() => dishInput.focus());
}

el("cancel-order").addEventListener("click", () => resetWizard({ cancelPending: true, focus: true }));
el("brand-home").addEventListener("click", () => resetWizard({ cancelPending: true, focus: true }));

async function sendReviewFeedback(kind, btn) {
  if (state.reviewFeedbackSent) return;
  state.reviewFeedbackSent = true;
  const like = el("review-like");
  const dislike = el("review-dislike");
  const status = el("review-feedback-status");
  like.disabled = true;
  dislike.disabled = true;
  btn.classList.add("selected");
  status.textContent = "Saving feedback…";
  const res = await captureFeedback({
    kind,
    raw: state.rawDish,
    dish: state.dish,
    display: state.display,
  });
  if (res?.stored) {
    status.textContent = kind === "review_liked"
      ? "Thanks — feedback saved."
      : "Thanks — this will be reviewed.";
  } else {
    state.reviewFeedbackSent = false;
    like.disabled = false;
    dislike.disabled = false;
    btn.classList.remove("selected");
    status.textContent = "Couldn't save feedback right now.";
  }
}
el("review-like").addEventListener("click", (e) => sendReviewFeedback("review_liked", e.currentTarget));
el("review-dislike").addEventListener("click", (e) => sendReviewFeedback("review_disliked", e.currentTarget));

/* ---------- STEP 4: payment ---------- */
function renderPayment() {
  const totals = state.cart.totals || {};
  const summary = el("pay-summary");
  const rows = (state.cart.items || [])
    .map((it) => `<div class="s-item"><span>${it.name.split(" (")[0]} × ${it.quantity}</span><span>${inr(it.unit_price * it.quantity)}</span></div>`)
    .join("");
  summary.innerHTML = `
    <h3>Order summary</h3>
    ${rows}
    <div class="s-totals">
      <div><span>Item total</span><span>${inr(totals.subtotal || 0)}</span></div>
      <div><span>Delivery</span><span>${(totals.delivery_fee || 0) === 0 && (totals.subtotal || 0) > 0 ? "FREE" : inr(totals.delivery_fee || 0)}</span></div>
      <div><span>Handling</span><span>${inr(totals.handling_fee || 0)}</span></div>
      <div class="grand"><span>To pay</span><span>${inr(totals.total || 0)}</span></div>
    </div>`;
  el("pay-btn").textContent = `Pay ${inr(totals.total || 0)}`;
}

el("to-payment").addEventListener("click", () => {
  renderPayment();
  showStep(4);
});
el("payment-back").addEventListener("click", () => showStep(3));

el("pay-btn").addEventListener("click", async () => {
  const method = document.querySelector('input[name="method"]:checked').value;
  const address = (el("address-input").value || "Home").trim() || "Home";
  const btn = el("pay-btn");
  btn.disabled = true;
  btn.classList.add("is-processing");
  const original = btn.textContent;
  btn.textContent = "Processing payment…";
  try {
    const data = await api(`/api/order/${state.sessionId}/pay`, { method: "POST", body: JSON.stringify({ method, address }) });
    state.paused = false;
    renderDone(data.order);
    showStep("done");
  } catch (err) {
    alert(err.message);
    btn.disabled = false;
    btn.classList.remove("is-processing");
    btn.textContent = original;
  }
});

function renderDone(order) {
  el("done-order-id").textContent = order.order_id;
  const labels = { upi: "UPI", card: "Card", cod: "Cash on Delivery" };
  el("done-sub").textContent = `Paid via ${labels[order.payment_method] || order.payment_method} · arriving in ~10 minutes`;
  const items = (order.items || [])
    .map((it) => `<div class="s-item"><span>${it.name} × ${it.quantity}</span><span>${inr(it.unit_price * it.quantity)}</span></div>`)
    .join("");
  el("done-summary").innerHTML = `
    ${items}
    <div class="s-totals">
      <div><span>Item total</span><span>${inr(order.subtotal)}</span></div>
      <div><span>Delivery</span><span>${order.delivery_fee === 0 ? "FREE" : inr(order.delivery_fee)}</span></div>
      <div><span>Handling</span><span>${inr(order.handling_fee)}</span></div>
      <div class="grand"><span>Total paid</span><span>${inr(order.total)}</span></div>
    </div>`;
}

el("start-over").addEventListener("click", () => resetWizard({ cancelPending: true, focus: true }));

/* ---------- stepper navigation ---------- */
steps.forEach((s) =>
  s.addEventListener("click", () => {
    const sn = Number(s.dataset.step);
    if (sn < state.maxStep && sn <= 2) showStep(sn);
    else if (sn === 3 && state.maxStep >= 3) showStep(3);
  })
);

/* ---------- boot ---------- */
(async function boot() {
  renderFoodStrip();
  setServings(4);
  await newSession();
  showStep(1);
})();
