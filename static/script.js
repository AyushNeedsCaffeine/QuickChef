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
  photo: null,
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
let photoToken = 0;

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
const PLACEHOLDER_PHOTO = "/static/dish-placeholder.svg";

function clearDishConfirm() {
  photoToken += 1;
  el("dish-confirm").classList.add("hidden");
  el("dc-candidate-list").innerHTML = "";
  el("dc-candidates").classList.add("hidden");
  el("dc-img").removeAttribute("src");
  el("dc-img").classList.add("hidden");
  el("dc-skeleton").classList.add("hidden");
  el("dc-credit").textContent = "";
  el("dc-credit").removeAttribute("href");
  el("dc-credit").title = "";
  el("recipe-photo").classList.add("hidden");
  state.candidates = [];
  state.photo = null;
}

async function loadDishPhoto(name, img, skeleton, credit) {
  const token = ++photoToken;
  img.classList.add("hidden");
  skeleton.classList.remove("hidden");
  credit.textContent = "";
  credit.removeAttribute("href");
  credit.title = "";
  try {
    const p = await api(`/api/dish/photo?dish=${encodeURIComponent(name)}`);
    if (token !== photoToken) return;
    const real = p.kind === "photo" && p.url;
    state.photo = real ? p.url : null;
    img.onload = () => {
      if (token !== photoToken) return;
      img.classList.remove("hidden");
      skeleton.classList.add("hidden");
    };
    img.onerror = () => {
      if (token !== photoToken) return;
      img.onerror = null;
      state.photo = null;
      img.src = PLACEHOLDER_PHOTO;
      img.classList.remove("hidden");
      skeleton.classList.add("hidden");
      credit.textContent = "";
      credit.removeAttribute("href");
      credit.title = "";
      el("recipe-photo").classList.add("hidden");
    };
    img.alt = real ? `${name} photo` : `${name} placeholder`;
    img.src = state.photo || PLACEHOLDER_PHOTO;
    if (real) {
      credit.textContent = [p.artist, p.license].filter(Boolean).join(" · ");
      credit.title = [p.source, p.artist, p.license].filter(Boolean).join(" · ");
      if (p.source_url) credit.href = p.source_url;
      el("recipe-photo").src = p.url;
      el("recipe-photo").alt = `${name} photo`;
      el("recipe-photo").classList.remove("hidden");
    } else {
      el("recipe-photo").classList.add("hidden");
    }
  } catch (err) {
    if (token !== photoToken) return;
    state.photo = null;
    img.onerror = null;
    img.src = PLACEHOLDER_PHOTO;
    img.alt = `${name} placeholder`;
    img.classList.remove("hidden");
    skeleton.classList.add("hidden");
    credit.removeAttribute("href");
    el("recipe-photo").classList.add("hidden");
  }
}

async function loadCandidatePhoto(name, img, placeholder) {
  try {
    const p = await api(`/api/dish/photo?dish=${encodeURIComponent(name)}`);
    if (p.kind !== "photo" || !p.url) return;
    img.loading = "lazy";
    img.onload = () => {
      img.classList.remove("hidden");
      placeholder.classList.add("hidden");
    };
    img.alt = `${name} photo`;
    img.src = p.url;
  } catch (err) {
    console.warn("photo:", err.message);
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
  state.candidates.slice(0, 3).forEach((c) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "dc-candidate";
    btn.innerHTML = `
      <span class="dc-candidate-media">
        <span class="dc-candidate-ph">?</span>
        <img class="hidden" alt="" />
      </span>
      <span class="dc-candidate-text">
        <span class="dc-candidate-name">${esc(c.name)}</span>
        ${c.description ? `<span class="dc-candidate-desc">${esc(c.description)}</span>` : ""}
      </span>`;
    btn.addEventListener("click", () => selectCandidate(c.name, btn));
    list.appendChild(btn);
    loadCandidatePhoto(c.name, btn.querySelector("img"), btn.querySelector(".dc-candidate-ph"));
  });
}

async function selectCandidate(name, btn) {
  state.dish = name;
  state.display = name;
  void linkRejection(state.rawDish, name, name);
  el("dc-name").textContent = name;
  el("dc-desc").textContent = "We'll use this dish for your recipe.";
  document.querySelectorAll(".dc-candidate").forEach((b) => b.classList.toggle("selected", b === btn));
  el("servings-dish-label").innerHTML = `Cooking <b>${esc(name)}</b>`;
  loadDishPhoto(name, el("dc-img"), el("dc-skeleton"), el("dc-credit"));
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
  el("dc-name").textContent = data.display || data.dish;
  el("dc-desc").textContent = data.candidates?.length
    ? "Pick the dish you meant, or confirm this one."
    : "We'll build a basket for this dish.";
  el("dish-confirm").classList.remove("hidden");
  renderDishCandidates(data.candidates || []);
  loadDishPhoto(data.dish, el("dc-img"), el("dc-skeleton"), el("dc-credit"));
}

async function submitDish(raw) {
  const fb = el("dish-feedback");
  const btn = el("dish-btn");
  if (btn.disabled) return;
  btn.disabled = true;
  clearDishConfirm();
  state.dishContext = null;
  state.rawDish = raw;
  setFeedback(fb, `<span class="spinner"></span> Understanding your dish…`);
  try {
    const data = await api(`/api/dish/${state.sessionId}`, { method: "POST", body: JSON.stringify({ dish: raw }) });
    state.dish = data.dish;
    state.display = data.display;
    setFeedback(fb, `<span class="understood"><span class="tick">✓</span> ${esc(data.display)}</span>`);
    showDishConfirm(data);
  } catch (err) {
    setFeedback(fb, esc(err.message), "error");
  } finally {
    btn.disabled = false;
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
  if (!rejected) return;
  state.rejectionContext = rejected;
  state.rejectionPromise = rejected
    ? captureFeedback({ kind: "dish_rejected", ...rejected })
    : null;
  state.dishContext = null;
  state.dish = null;
  state.display = null;
  state.rawDish = null;
  clearDishConfirm();
  setFeedback(el("dish-feedback"), "No problem — tell me the right dish.");
  el("dish-input").focus();
  el("dish-input").select();
});

el("dish-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const v = el("dish-input").value.trim();
  if (v) submitDish(v);
});
document.querySelectorAll(".chip-btn").forEach((b) =>
  b.addEventListener("click", () => {
    el("dish-input").value = b.dataset.dish;
    submitDish(b.dataset.dish);
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
  const photo = el("recipe-photo");
  if (state.photo) {
    photo.src = state.photo;
    photo.alt = `${state.display || r.dish || "Dish"} photo`;
    photo.classList.remove("hidden");
  } else {
    photo.classList.add("hidden");
  }
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

async function cancelOrder() {
  try {
    await api(`/api/cart/${state.sessionId}/cancel`, { method: "POST" });
  } catch (err) {
    console.warn("cancel:", err.message);
  }
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
  el("dish-input").value = "";
  el("servings-feedback").innerHTML = "";
  resetReviewFeedback();
  clearDishConfirm();
  await newSession();
  showStep(1);
}
el("cancel-order").addEventListener("click", cancelOrder);

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

el("start-over").addEventListener("click", async () => {
  if (state.paused) await cancelOrder();
  state.maxStep = 1;
  state.dish = null;
  state.display = null;
  state.rawDish = null;
  state.recipe = null;
  state.cart = { items: [], totals: {} };
  state.paused = false;
  state.dishContext = null;
  state.rejectionPromise = null;
  state.rejectionContext = null;
  el("dish-input").value = "";
  el("address-input").value = "Home";
  el("servings-feedback").innerHTML = "";
  resetReviewFeedback();
  clearDishConfirm();
  setServings(4);
  await newSession();
  showStep(1);
});

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
