/* QuickInvoice — frontend SPA (vanilla JS, no dependencies) */

// ---------------- State & helpers ----------------
// Safe storage wrapper — sandboxed iframes & private-mode browsers can throw
// on localStorage access, so we degrade gracefully to in-memory storage.
const store = {
  _m: {},
  get(k) { try { return window.localStorage.getItem(k); } catch (e) { return this._m[k] ?? null; } },
  set(k, v) { try { window.localStorage.setItem(k, v); } catch (e) { this._m[k] = v; } },
  remove(k) { try { window.localStorage.removeItem(k); } catch (e) { delete this._m[k]; } },
};

const state = {
  token: store.get("qi_token") || null,
  user: null,
  company: null,
  customers: [],
  products: [],
  invoices: [],
  quotes: [],
};

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function fmtMoney(n, cur) {
  const c = cur || state.company?.currency || "AED";
  return new Intl.NumberFormat("en-AE", { style: "currency", currency: c, minimumFractionDigits: 2 }).format(Number(n || 0));
}
function fmtNum(n) { return new Intl.NumberFormat("en-AE").format(Number(n || 0)); }

function toast(msg, type = "success") {
  const el = $("#toast");
  el.textContent = msg;
  el.className = "toast " + type;
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.add("hidden"), 3200);
}

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  if (state.token) headers["Authorization"] = "Bearer " + state.token;
  let res;
  try {
    res = await fetch("/api" + path, { ...opts, headers });
  } catch (e) {
    // Network failure — server unreachable (not an auth problem)
    throw new Error("Cannot reach the server. Please refresh the page and try again.");
  }
  const data = await res.json().catch(() => ({}));
  // Only treat 401 as "session expired" for authenticated requests.
  // A failed LOGIN (also 401) should show "invalid email or password".
  if (res.status === 401 && path !== "/login") {
    logout();
    throw new Error("Session expired — please sign in again.");
  }
  if (!res.ok) throw new Error(data.error || "Request failed");
  return data;
}

// ---------------- Auth ----------------
function showLogin() {
  $("#app").classList.add("hidden");
  $("#login-screen").classList.remove("hidden");
}
function showApp() {
  $("#login-screen").classList.add("hidden");
  $("#app").classList.remove("hidden");
}
function logout() {
  state.token = null; state.user = null;
  store.remove("qi_token");
  api("/logout", { method: "POST" }).catch(() => {});
  showLogin();
}

$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const email = $("#login-email").value.trim();
  const password = $("#login-password").value;
  $("#login-error").classList.add("hidden");
  try {
    const r = await api("/login", { method: "POST", body: JSON.stringify({ email, password }) });
    state.token = r.token; state.user = r.user;
    store.set("qi_token", r.token);
    boot();
  } catch (err) {
    const el = $("#login-error");
    el.textContent = err.message; el.classList.remove("hidden");
  }
});
$("#logout-btn").addEventListener("click", logout);

// ---------------- Router ----------------
const routes = {
  dashboard: renderDashboard,
  invoices: renderInvoices,
  "invoice/new": renderInvoiceForm,
  "invoice/edit": renderInvoiceForm,
  "invoice/view": renderInvoiceView,
  quotes: renderQuotes,
  "quote/new": renderQuoteForm,
  "quote/edit": renderQuoteForm,
  "quote/view": renderQuoteView,
  customers: renderCustomers,
  products: renderProducts,
  payments: renderPayments,
  expenses: renderExpenses,
  statement: renderStatement,
  reports: renderReports,
  settings: renderSettings,
  users: renderUsers,
};

function currentRoute() {
  const h = location.hash.replace(/^#\/?/, "") || "dashboard";
  return h.split("/");
}

function navigate() {
  const parts = currentRoute();
  const key = parts[0];
  const fn = routes[key] || routes[parts.slice(0, 2).join("/")] || renderDashboard;
  // highlight nav
  $$(".nav-link").forEach((a) => a.classList.toggle("active", a.dataset.nav === key));
  // admin-only visibility
  const isAdmin = state.user?.role === "admin";
  $$(".admin-only").forEach((a) => a.classList.toggle("hidden", !isAdmin));
  try {
    const result = fn(parts.slice(1));
    // If the route returns a promise, surface any rejection clearly.
    if (result && typeof result.catch === "function") {
      result.catch((e) => showFatal(e));
    }
  } catch (e) {
    showFatal(e);
  }
}

function showFatal(e) {
  const msg = (e && (e.message || e)) || "Unknown error";
  const stack = (e && e.stack) || "";
  console.error("Route error:", e);
  const el = $("#view");
  if (el) {
    el.innerHTML = `<div class="card" style="margin:20px"><div class="empty">
      <div class="big">⚠️</div><h3>Something went wrong</h3>
      <p class="muted" style="word-break:break-word;max-width:640px;margin:0 auto">${esc(String(msg))}</p>
      <pre class="muted small" style="word-break:break-word;max-width:640px;margin:12px auto 0;text-align:left;white-space:pre-wrap;background:#f8fafc;padding:12px;border-radius:8px">${esc(stack.split("\n").slice(0, 4).join("\n"))}</pre>
      <button class="btn btn-primary" style="margin-top:14px" onclick="location.reload()">Reload</button>
    </div></div>`;
  }
}

window.addEventListener("hashchange", navigate);

// Surface any uncaught error instead of silently blanking the app
window.addEventListener("error", (e) => showFatal(e));
window.addEventListener("unhandledrejection", (e) => showFatal(e.reason));

// ---------------- Boot ----------------
async function boot() {
  if (!state.token) { showLogin(); return; }
  showApp();
  try {
    const me = await api("/me");
    state.user = me.user;
    $("#user-name").textContent = me.user.name;
    $("#user-role").textContent = me.user.role === "admin" ? "Administrator" : "Staff";
    $("#user-avatar").textContent = (me.user.name[0] || "?").toUpperCase();
    try {
      const c = await api("/settings");
      state.company = c.company;
      $("#sidebar-company").textContent = c.company.name || "QuickInvoice";
    } catch (e) {
      console.warn("settings load failed", e);
    }
    try {
      navigate();
    } catch (e) {
      console.error("navigate failed", e);
      $("#view").innerHTML = `<div class="card" style="margin:20px"><div class="empty"><div class="big">⚠️</div><h3>Could not load the dashboard</h3><p class="muted">${esc(e.message || "")}</p><button class="btn btn-primary" onclick="location.reload()">Reload</button></div></div>`;
    }
  } catch (e) {
    console.error("boot failed", e);
    // show a visible error rather than silently logging out
    $("#view").innerHTML = `<div class="card" style="margin:20px"><div class="empty"><div class="big">⚠️</div><h3>Sign-in error</h3><p class="muted">${esc(e.message || "Could not verify your session")}</p><button class="btn btn-primary" onclick="location.reload()">Try again</button></div></div>`;
  }
}

// ---------------- Modal ----------------
function openModal(title, bodyHtml, actions = "") {
  const root = $("#modal-root");
  root.innerHTML = `
    <div class="modal-backdrop">
      <div class="modal">
        <div class="modal-head"><h3>${title}</h3>
          <button class="icon-btn" onclick="closeModal()" style="color:#64748b">✕</button></div>
        <div class="modal-body">${bodyHtml}</div>
        ${actions ? `<div class="modal-body" style="padding-top:0">${actions}</div>` : ""}
      </div>
    </div>`;
  root.querySelector(".modal-backdrop").addEventListener("click", (e) => { if (e.target === e.currentTarget) closeModal(); });
}
function closeModal() { $("#modal-root").innerHTML = ""; }

// ================= DASHBOARD =================
async function renderDashboard() {
  const d = await api("/reports/dashboard");
  const view = $("#view");
  const overdueBadge = d.overdue_invoices > 0 ? `<div class="card" style="border-left:4px solid var(--red)"><div class="stat"><span class="label">Overdue invoices</span><span class="value" style="color:var(--red)">${d.overdue_invoices}</span><span class="delta muted">Action needed</span></div></div>` : "";
  const lowStockBadge = d.low_stock > 0 ? `<div class="card" style="border-left:4px solid var(--amber)"><div class="stat"><span class="label">Low stock items</span><span class="value" style="color:var(--amber)">${d.low_stock}</span><span class="delta muted">Reorder soon</span></div></div>` : "";

  const maxRev = Math.max(...d.monthly.map((m) => m.revenue), 1);
  const bars = d.monthly.map((m) => {
    const h = Math.max((m.revenue / maxRev) * 100, 2);
    return `<div class="chart-bar"><span class="bar-val">${m.revenue ? (m.revenue / 1000).toFixed(1) + "k" : ""}</span><div class="bar" style="height:${h}px;height:${h}%"></div><span class="bar-label">${monthLabel(m.month)}</span></div>`;
  }).join("");

  const topCust = d.top_customers.length ? d.top_customers.map((c, i) => `
    <tr><td>${i + 1}</td><td>${esc(c.name)}</td><td class="num">${fmtMoney(c.total)}</td></tr>`).join("")
    : `<tr><td colspan="3" class="muted">No sales yet</td></tr>`;

  const recent = d.recent.length ? d.recent.map((r) => `
    <tr class="clickable" onclick="location.hash='#/invoice/view/${r.id}'">
      <td class="mono">${esc(r.number)}</td><td>${esc(r.customer)}</td>
      <td class="num">${fmtMoney(r.total)}</td>
      <td><span class="badge ${r.status}">${r.status}</span></td>
      <td class="muted small">${esc(r.created_at.slice(0, 10))}</td>
    </tr>`).join("") : `<tr><td colspan="5" class="muted">No invoices yet</td></tr>`;

  view.innerHTML = `
    <div class="page-head">
      <div><h2>Dashboard</h2><div class="sub">Welcome back, ${esc(state.user.name)} — here's your business at a glance.</div></div>
      <div class="no-print" style="display:flex;gap:10px">
        <a class="btn" href="#/invoice/new">+ New Invoice</a>
        <a class="btn btn-primary" href="#/quote/new">+ New Quotation</a>
      </div>
    </div>
    <div class="grid grid-4" style="margin-bottom:16px">
      <div class="card"><div class="stat"><span class="label">Total invoiced</span><span class="value">${fmtMoney(d.total_invoiced)}</span><span class="delta muted">All time</span></div></div>
      <div class="card"><div class="stat"><span class="label">Collected</span><span class="value" style="color:var(--green)">${fmtMoney(d.total_paid)}</span><span class="delta muted">Payments received</span></div></div>
      <div class="card"><div class="stat"><span class="label">Outstanding</span><span class="value" style="color:${d.outstanding > 0 ? "var(--amber)" : "var(--text)"}">${fmtMoney(d.outstanding)}</span><span class="delta muted">To collect</span></div></div>
      <div class="card"><div class="stat"><span class="label">Sales this month</span><span class="value">${fmtMoney(d.sales_this_month)}</span><span class="delta muted">${d.open_invoices} open invoices</span></div></div>
    </div>
    <div class="grid grid-2" style="margin-bottom:16px">${overdueBadge}${lowStockBadge || `<div class="card"><div class="stat"><span class="label">Low stock items</span><span class="value">0</span><span class="delta muted">All good</span></div></div>`}</div>
    <div class="grid grid-2" style="margin-bottom:16px">
      <div class="card"><h3 style="margin-bottom:14px">Revenue — last 6 months</h3><div class="chart-bars">${bars}</div></div>
      <div class="card"><h3 style="margin-bottom:14px">Top customers</h3><table><thead><tr><th>#</th><th>Customer</th><th class="num">Revenue</th></tr></thead><tbody>${topCust}</tbody></table></div>
    </div>
    <div class="card"><h3 style="margin-bottom:14px">Recent invoices</h3><table><thead><tr><th>Number</th><th>Customer</th><th class="num">Total</th><th>Status</th><th>Date</th></tr></thead><tbody>${recent}</tbody></table></div>`;
}
function monthLabel(m) {
  const [y, mo] = m.split("-");
  return new Date(y, mo - 1, 1).toLocaleString("en", { month: "short" });
}

// ================= INVOICES =================
async function renderInvoices() {
  const inv = (await api("/invoices")).invoices;
  state.invoices = inv;
  const view = $("#view");
  const statusFilter = store.get("qi_inv_filter") || "all";

  const render = () => {
    const f = $("#inv-filter").value;
    store.set("qi_inv_filter", f);
    const q = ($("#inv-search").value || "").toLowerCase();
    const list = inv.filter((i) => {
      if (f !== "all" && i.status !== f) return false;
      if (q && !(i.number + " " + (i.customer?.name || "")).toLowerCase().includes(q)) return false;
      return true;
    });
    const rows = list.length ? list.map((i) => `
      <tr class="clickable" onclick="location.hash='#/invoice/view/${i.id}'">
        <td class="mono">${esc(i.number)}</td>
        <td>${esc(i.customer?.name || "—")}</td>
        <td class="small muted">${esc(i.issue_date)}</td>
        <td class="small muted">${esc(i.due_date)}</td>
        <td class="num">${fmtMoney(i.total)}</td>
        <td class="num small">${i.paid_amount > 0 ? fmtMoney(i.paid_amount) : "—"}</td>
        <td><span class="badge ${i.status}">${i.status}</span></td>
      </tr>`).join("") : `<tr><td colspan="7" class="empty"><div class="big">🗂️</div><h3>No invoices found</h3><p class="muted">Create your first invoice to get started.</p><a class="btn btn-primary" href="#/invoice/new" style="margin-top:12px">+ Create Invoice</a></td></tr>`;
    $("#inv-rows").innerHTML = rows;
  };

  view.innerHTML = `
    <div class="page-head">
      <div><h2>Invoices</h2><div class="sub">${inv.length} invoices</div></div>
      <a class="btn btn-primary" href="#/invoice/new">+ New Invoice</a>
    </div>
    <div class="card">
      <div class="toolbar">
        <div class="searchbar">
          <input id="inv-search" placeholder="Search number or customer…" oninput="window._invRender && window._invRender()" />
          <select id="inv-filter" onchange="window._invRender && window._invRender()">
            ${["all","draft","sent","partial","paid","overdue","cancelled"].map((s) => `<option value="${s}" ${s === statusFilter ? "selected" : ""}>${s === "all" ? "All statuses" : s[0].toUpperCase() + s.slice(1)}</option>`).join("")}
          </select>
        </div>
      </div>
      <div class="table-wrap"><table><thead><tr><th>Number</th><th>Customer</th><th>Issued</th><th>Due</th><th class="num">Total</th><th class="num">Paid</th><th>Status</th></tr></thead><tbody id="inv-rows"></tbody></table></div>
    </div>`;
  window._invRender = render;
  render();
}

// ---- Invoice form ----
async function renderInvoiceForm(args) {
  const id = args[0];
  let inv = null;
  if (id) {
    inv = (await api("/invoices/" + id)).invoice;
  }
  const customers = (await api("/customers")).customers;
  const products = (await api("/products")).products;
  state.customers = customers; state.products = products;

  const items = inv ? inv.items.map((it) => ({ product_id: it.product_id, description: it.description, qty: it.qty, unit_price: it.unit_price }))
    : [{ product_id: null, description: "", qty: 1, unit_price: 0 }];

  const view = $("#view");
  view.innerHTML = `
    <div class="page-head">
      <div><h2>${inv ? "Edit Invoice " + esc(inv.number) : "New Invoice"}</h2><div class="sub">${inv ? "Update the invoice details below" : "Create a new invoice"}</div></div>
      <div style="display:flex;gap:10px">
        <a class="btn" href="#/invoices">Cancel</a>
        <button class="btn btn-primary" onclick="saveInvoice(${id || "null"}, 'draft')">Save Draft</button>
        <button class="btn btn-primary" style="background:var(--green);border-color:var(--green)" onclick="saveInvoice(${id || "null"}, 'sent')">Save & Send</button>
      </div>
    </div>
    <div class="card">
      <div class="form-grid">
        <div class="field full"><label>Customer *</label>
          <select id="f-customer">${customers.map((c) => `<option value="${c.id}" ${inv && inv.customer_id == c.id ? "selected" : ""}>${esc(c.name)}${c.company_name ? " — " + esc(c.company_name) : ""}</option>`).join("")}</select>
        </div>
        <div class="field"><label>Issue date</label><input type="date" id="f-issue" value="${inv ? inv.issue_date : today()}"></div>
        <div class="field"><label>Due date</label><input type="date" id="f-due" value="${inv ? inv.due_date : addDays(14)}"></div>
        <div class="field"><label>Discount (${esc(state.company?.currency || "AED")})</label><input type="number" id="f-discount" step="0.01" min="0" value="${inv ? inv.discount : 0}"></div>
        <div class="field"><label>Status</label><select id="f-status">
          ${["draft","sent"].map((s) => `<option value="${s}" ${inv && inv.status === s ? "selected" : ""}>${s[0].toUpperCase() + s.slice(1)}</option>`).join("")}
        </select></div>
        <div class="field full"><label>Notes</label><textarea id="f-notes">${esc(inv?.notes || state.company?.invoice_notes || "")}</textarea></div>
        <div class="field full"><label>Terms</label><textarea id="f-terms">${esc(inv?.terms || state.company?.payment_terms || "")}</textarea></div>
      </div>
    </div>
    <div class="card" style="margin-top:16px">
      <div class="toolbar" style="margin-bottom:6px"><h3>Line items</h3><button class="btn btn-sm" onclick="addLineItem()">+ Add item</button></div>
      <div id="line-items">${items.map((it, idx) => lineItemHtml(it, idx)).join("")}</div>
      <div class="totals-box"><div class="totals" id="totals"></div></div>
    </div>`;
  window._items = items;
  attachLineEvents();
  recomputeTotals();
}

function lineItemHtml(it, idx) {
  const prodOpts = state.products.map((p) => `<option value="${p.id}" data-price="${p.sell_price}">${esc(p.name)}</option>`).join("");
  return `<div class="line-item" data-idx="${idx}">
    <div class="product-cell">
      <select onchange="lineProduct(${idx}, this)">
        <option value="">— Custom item —</option>${prodOpts}
      </select>
    </div>
    <input type="text" class="li-desc" placeholder="Description" value="${esc(it.description)}" oninput="lineEdit(${idx})">
    <input type="number" class="li-qty" placeholder="Qty" step="any" min="0" value="${it.qty}" oninput="lineEdit(${idx})">
    <input type="number" class="li-price" placeholder="Unit price" step="0.01" min="0" value="${it.unit_price}" oninput="lineEdit(${idx})">
    <button class="icon-btn del" style="color:var(--red)" onclick="removeLine(${idx})">✕</button>
  </div>`;
}

function addLineItem() {
  window._items.push({ product_id: null, description: "", qty: 1, unit_price: 0 });
  $("#line-items").insertAdjacentHTML("beforeend", lineItemHtml(window._items[window._items.length - 1], window._items.length - 1));
  recomputeTotals();
}
function removeLine(idx) {
  if (window._items.length <= 1) { toast("At least one line item is required", "error"); return; }
  window._items.splice(idx, 1);
  $$("#line-items .line-item").forEach((el, i) => el.dataset.idx = i);
  $("#line-items").innerHTML = window._items.map((it, i) => lineItemHtml(it, i)).join("");
  attachLineEvents();
  recomputeTotals();
}
function lineProduct(idx, sel) {
  const it = window._items[idx];
  if (sel.value) {
    const opt = sel.selectedOptions[0];
    it.product_id = Number(sel.value);
    it.description = sel.options[sel.selectedIndex].text;
    it.unit_price = Number(opt.dataset.price || 0);
  } else {
    it.product_id = null;
    it.description = "";
  }
  const el = $$("#line-items .line-item")[idx];
  el.querySelector(".li-desc").value = it.description;
  el.querySelector(".li-price").value = it.unit_price;
  recomputeTotals();
}
function lineEdit(idx) {
  const el = $$("#line-items .line-item")[idx];
  window._items[idx].description = el.querySelector(".li-desc").value;
  window._items[idx].qty = Number(el.querySelector(".li-qty").value || 0);
  window._items[idx].unit_price = Number(el.querySelector(".li-price").value || 0);
  recomputeTotals();
}
function attachLineEvents() {}

function recomputeTotals() {
  const rate = state.company?.vat_rate ?? 5;
  let subtotal = 0, tax = 0;
  for (const it of window._items) {
    const lt = (it.qty || 0) * (it.unit_price || 0);
    subtotal += lt;
    const prod = state.products.find((p) => p.id === it.product_id);
    const taxable = prod ? prod.is_taxable : true;
    if (taxable) tax += lt * rate / 100;
  }
  const disc = Number($("#f-discount").value || 0);
  let total = subtotal + tax - disc;
  if (total < 0) total = 0;
  $("#totals").innerHTML = `
    <div class="t-row"><span class="muted">Subtotal</span><span>${fmtMoney(subtotal)}</span></div>
    <div class="t-row"><span class="muted">VAT (${rate}%)</span><span>${fmtMoney(tax)}</span></div>
    ${disc ? `<div class="t-row"><span class="muted">Discount</span><span>− ${fmtMoney(disc)}</span></div>` : ""}
    <div class="t-row grand"><span>Total</span><span>${fmtMoney(total)}</span></div>`;
}

async function saveInvoice(id, statusOverride) {
  const customer_id = Number($("#f-customer").value);
  const body = {
    customer_id,
    issue_date: $("#f-issue").value,
    due_date: $("#f-due").value,
    discount: Number($("#f-discount").value || 0),
    notes: $("#f-notes").value,
    terms: $("#f-terms").value,
    status: statusOverride,
    items: window._items.filter((it) => it.description || it.qty > 0),
  };
  if (!body.customer_id) { toast("Please select a customer", "error"); return; }
  if (!body.items.length) { toast("Add at least one line item", "error"); return; }
  try {
    const r = id ? await api("/invoices/" + id, { method: "PUT", body: JSON.stringify(body) })
                 : await api("/invoices", { method: "POST", body: JSON.stringify(body) });
    toast(statusOverride === "sent" ? "Invoice sent" : "Invoice saved");
    location.hash = "#/invoice/view/" + r.id;
  } catch (e) { toast(e.message, "error"); }
}

// ---- Invoice view ----
async function renderInvoiceView(args) {
  const id = args[0];
  const inv = (await api("/invoices/" + id)).invoice;
  const c = inv.customer;
  const view = $("#view");
  const itemsHtml = inv.items.map((it, i) => `
    <tr><td class="sl-num">${String(i + 1).padStart(2, "0")}</td><td>${esc(it.description)}</td><td class="num">${fmtNum(it.qty)}</td><td class="num">${fmtMoney(it.unit_price)}</td><td class="num">${fmtMoney(it.unit_vat != null ? it.unit_vat : 0)}</td><td class="num">${fmtMoney(it.unit_total != null ? it.unit_total : it.unit_price)}</td></tr>`).join("");
  const paysHtml = inv.payments.length ? inv.payments.map((p) => `
    <tr><td class="small">${esc(p.date)}</td><td>${esc(p.method)}</td><td class="small">${esc(p.reference || "—")}</td><td class="num">${fmtMoney(p.amount)}</td>
    <td><button class="btn btn-sm btn-danger" onclick="deletePayment(${p.id}, ${inv.id})">✕</button></td></tr>`).join("")
    : `<tr><td colspan="5" class="muted">No payments recorded</td></tr>`;

  const statusActions = [];
  if (inv.status === "draft") statusActions.push(`<button class="btn btn-sm" onclick="setInvoiceStatus(${inv.id},'sent')">Mark as Sent</button>`);
  if (inv.status !== "cancelled") statusActions.push(`<button class="btn btn-sm btn-danger" onclick="setInvoiceStatus(${inv.id},'cancelled')">Cancel</button>`);

  view.innerHTML = `
    <div class="page-head">
      <div><h2>Invoice ${esc(inv.number)}</h2>
        <div class="sub">${esc(c?.name || "")} · <span class="badge ${inv.status}">${inv.status}</span></div></div>
      <div class="no-print" style="display:flex;gap:8px;flex-wrap:wrap">
        <a class="btn btn-sm" href="#/invoice/edit/${inv.id}">Edit</a>
        <button class="btn btn-sm" onclick="openTermsModal(${inv.id})">✎ Terms</button>
        <button class="btn btn-sm" onclick="printDoc('invoice', ${inv.id})">🖨 Print / PDF</button>
        <button class="btn btn-sm btn-primary" onclick="openPaymentModal(${inv.id})">+ Record Payment</button>
        ${statusActions.join("")}
      </div>
    </div>
    <div class="grid grid-3" style="margin-bottom:16px">
      <div class="card"><div class="stat"><span class="label">Total</span><span class="value">${fmtMoney(inv.total)}</span></div></div>
      <div class="card"><div class="stat"><span class="label">Paid</span><span class="value" style="color:var(--green)">${fmtMoney(inv.paid_amount)}</span></div></div>
      <div class="card"><div class="stat"><span class="label">Balance due</span><span class="value" style="color:${inv.balance > 0 ? "var(--amber)" : "var(--green)"}">${fmtMoney(inv.balance)}</span></div></div>
    </div>
    <div class="card" style="margin-bottom:16px">
      <h3 style="margin-bottom:12px">Line items</h3>
      <div class="table-wrap"><table><thead><tr><th>SL</th><th>Item Description</th><th class="num">Quantity</th><th class="num">Price Before VAT</th><th class="num">${state.company?.vat_rate ?? 5}% VAT</th><th class="num">Total Amount</th></tr></thead><tbody>${itemsHtml}</tbody></table></div>
      <div class="totals-box"><div class="totals">
        <div class="t-row"><span class="muted">Amount Before VAT</span><span>${fmtMoney(inv.subtotal)}</span></div>
        <div class="t-row"><span class="muted">VAT Amount (${state.company?.vat_rate ?? 5}%)</span><span>${fmtMoney(inv.tax_amount)}</span></div>
        <div class="t-row"><span class="muted">Amount With VAT</span><span>${fmtMoney(Number(inv.subtotal) + Number(inv.tax_amount))}</span></div>
        ${Number(inv.discount) ? `<div class="t-row"><span class="muted">Discount</span><span>− ${fmtMoney(inv.discount)}</span></div>` : ""}
        <div class="t-row grand"><span>Total</span><span>${fmtMoney(inv.total)}</span></div>
        <div class="t-row"><span class="muted">Amount Received</span><span style="color:var(--green)">${fmtMoney(inv.paid_amount)}</span></div>
        <div class="t-row"><span class="muted">Amount Balance</span><span style="color:${inv.balance > 0 ? "var(--amber)" : "var(--green)"}">${fmtMoney(inv.balance)}</span></div>
      </div></div>
    </div>
    <div class="card" style="margin-bottom:16px"><h3 style="margin-bottom:12px">Payments</h3>
      <div class="table-wrap"><table><thead><tr><th>Date</th><th>Method</th><th>Reference</th><th class="num">Amount</th><th></th></tr></thead><tbody>${paysHtml}</tbody></table></div>
    </div>
    <div class="card">
      <div class="grid grid-2">
        <div><h3 style="margin-bottom:10px">Terms</h3><div class="muted" style="white-space:pre-line">${esc(inv.terms || "—")}</div></div>
        <div><h3 style="margin-bottom:10px">Notes</h3><div class="muted" style="white-space:pre-line">${esc(inv.notes || "—")}</div></div>
      </div>
    </div>`;
}

async function setInvoiceStatus(id, status) {
  try {
    await api("/invoices/" + id + "/status", { method: "POST", body: JSON.stringify({ status }) });
    toast("Status updated");
    location.hash = "#/invoice/view/" + id;
  } catch (e) { toast(e.message, "error"); }
}

async function openTermsModal(invoiceId) {
  const inv = (await api("/invoices/" + invoiceId)).invoice;
  openModal("Edit terms & notes", `
    <div class="form-grid" style="grid-template-columns:1fr">
      <div class="field"><label>Terms &amp; Conditions</label><textarea id="t-terms" rows="5">${esc(inv.terms || "")}</textarea></div>
      <div class="field"><label>Notes</label><textarea id="t-notes" rows="4">${esc(inv.notes || "")}</textarea></div>
    </div>`,
    `<button class="btn btn-primary btn-block" onclick="saveTerms(${invoiceId})">Save</button>`);
}

async function saveTerms(invoiceId) {
  const inv = (await api("/invoices/" + invoiceId)).invoice;
  const body = {
    customer_id: inv.customer_id,
    issue_date: inv.issue_date,
    due_date: inv.due_date,
    discount: inv.discount,
    notes: $("#t-notes").value,
    terms: $("#t-terms").value,
    status: inv.status,
    items: inv.items.map((it) => ({ product_id: it.product_id, description: it.description, qty: it.qty, unit_price: it.unit_price })),
  };
  try {
    await api("/invoices/" + invoiceId, { method: "PUT", body: JSON.stringify(body) });
    closeModal(); toast("Terms saved");
    location.hash = "#/invoice/view/" + invoiceId;
  } catch (e) { toast(e.message, "error"); }
}

function openPaymentModal(invoiceId) {
  openModal("Record payment", `
    <div class="form-grid" style="grid-template-columns:1fr">
      <div class="field"><label>Amount *</label><input type="number" id="pay-amount" step="0.01" min="0.01" placeholder="0.00"></div>
      <div class="field"><label>Date</label><input type="date" id="pay-date" value="${today()}"></div>
      <div class="field"><label>Method</label><select id="pay-method">
        ${["cash","card","bank_transfer","cheque","other"].map((m) => `<option value="${m}">${m.replace("_", " ")}</option>`).join("")}</select></div>
      <div class="field"><label>Reference</label><input type="text" id="pay-ref" placeholder="e.g. Cheque #, transaction ID"></div>
      <div class="field"><label>Note</label><input type="text" id="pay-note" placeholder="Optional"></div>
    </div>`,
    `<button class="btn btn-primary btn-block" onclick="submitPayment(${invoiceId})">Record payment</button>`);
}

async function submitPayment(invoiceId) {
  const body = {
    amount: Number($("#pay-amount").value),
    date: $("#pay-date").value,
    method: $("#pay-method").value,
    reference: $("#pay-ref").value,
    note: $("#pay-note").value,
  };
  if (!body.amount || body.amount <= 0) { toast("Enter a valid amount", "error"); return; }
  try {
    await api("/invoices/" + invoiceId + "/payments", { method: "POST", body: JSON.stringify(body) });
    closeModal(); toast("Payment recorded"); location.hash = "#/invoice/view/" + invoiceId;
  } catch (e) { toast(e.message, "error"); }
}

async function deletePayment(paymentId, invoiceId) {
  if (!confirm("Delete this payment?")) return;
  await api("/payments/" + paymentId, { method: "DELETE" });
  toast("Payment deleted"); location.hash = "#/invoice/view/" + invoiceId;
}

// ================= QUOTES =================
async function renderQuotes() {
  const qs = (await api("/quotes")).quotes;
  state.quotes = qs;
  const view = $("#view");
  view.innerHTML = `
    <div class="page-head">
      <div><h2>Quotations</h2><div class="sub">${qs.length} quotations</div></div>
      <a class="btn btn-primary" href="#/quote/new">+ New Quotation</a>
    </div>
    <div class="card"><div class="table-wrap"><table><thead><tr><th>Number</th><th>Customer</th><th>Issued</th><th>Valid until</th><th class="num">Total</th><th>Status</th></tr></thead>
    <tbody>${qs.length ? qs.map((q) => `
      <tr class="clickable" onclick="location.hash='#/quote/view/${q.id}'">
        <td class="mono">${esc(q.number)}</td><td>${esc(q.customer?.name || "—")}</td>
        <td class="small muted">${esc(q.issue_date)}</td><td class="small muted">${esc(q.valid_until)}</td>
        <td class="num">${fmtMoney(q.total)}</td><td><span class="badge ${q.status}">${q.status}</span></td>
      </tr>`).join("") : `<tr><td colspan="6" class="empty"><div class="big">📄</div>No quotations yet</td></tr>`}</tbody></table></div></div>`;
}

async function renderQuoteForm(args) {
  const id = args[0];
  let q = null;
  if (id) q = (await api("/quotes/" + id)).quote;
  const customers = (await api("/customers")).customers;
  const products = (await api("/products")).products;
  state.customers = customers; state.products = products;
  const items = q ? q.items.map((it) => ({ product_id: it.product_id, description: it.description, qty: it.qty, unit_price: it.unit_price }))
    : [{ product_id: null, description: "", qty: 1, unit_price: 0 }];

  const view = $("#view");
  view.innerHTML = `
    <div class="page-head">
      <div><h2>${q ? "Edit Quotation " + esc(q.number) : "New Quotation"}</h2><div class="sub">Send a price quote to a customer</div></div>
      <div style="display:flex;gap:10px">
        <a class="btn" href="#/quotes">Cancel</a>
        <button class="btn btn-primary" onclick="saveQuote(${id || "null"}, 'draft')">Save Draft</button>
        <button class="btn btn-primary" style="background:var(--green);border-color:var(--green)" onclick="saveQuote(${id || "null"}, 'sent')">Save & Send</button>
      </div>
    </div>
    <div class="card">
      <div class="form-grid">
        <div class="field full"><label>Customer *</label>
          <select id="q-customer">${customers.map((c) => `<option value="${c.id}" ${q && q.customer_id == c.id ? "selected" : ""}>${esc(c.name)}${c.company_name ? " — " + esc(c.company_name) : ""}</option>`).join("")}</select>
        </div>
        <div class="field"><label>Issue date</label><input type="date" id="q-issue" value="${q ? q.issue_date : today()}"></div>
        <div class="field"><label>Valid until</label><input type="date" id="q-valid" value="${q ? q.valid_until : addDays(30)}"></div>
        <div class="field"><label>Discount (${esc(state.company?.currency || "AED")})</label><input type="number" id="q-discount" step="0.01" min="0" value="${q ? q.discount : 0}"></div>
        <div class="field"><label>Status</label><select id="q-status">
          ${["draft","sent","accepted","rejected","expired"].map((s) => `<option value="${s}" ${q && q.status === s ? "selected" : ""}>${s[0].toUpperCase() + s.slice(1)}</option>`).join("")}
        </select></div>
        <div class="field full"><label>Notes</label><textarea id="q-notes">${esc(q?.notes || "")}</textarea></div>
        <div class="field full"><label>Terms</label><textarea id="q-terms">${esc(q?.terms || state.company?.payment_terms || "")}</textarea></div>
      </div>
    </div>
    <div class="card" style="margin-top:16px">
      <div class="toolbar" style="margin-bottom:6px"><h3>Line items</h3><button class="btn btn-sm" onclick="addQuoteLine()">+ Add item</button></div>
      <div id="q-line-items">${items.map((it, idx) => quoteLineHtml(it, idx)).join("")}</div>
      <div class="totals-box"><div class="totals" id="q-totals"></div></div>
    </div>`;
  window._items = items;
  recomputeQuoteTotals();
}

function quoteLineHtml(it, idx) {
  const prodOpts = state.products.map((p) => `<option value="${p.id}" data-price="${p.sell_price}">${esc(p.name)}</option>`).join("");
  return `<div class="line-item" data-idx="${idx}">
    <div class="product-cell"><select onchange="quoteProduct(${idx}, this)">
      <option value="">— Custom item —</option>${prodOpts}</select></div>
    <input type="text" class="li-desc" placeholder="Description" value="${esc(it.description)}" oninput="quoteLineEdit(${idx})">
    <input type="number" class="li-qty" placeholder="Qty" step="any" min="0" value="${it.qty}" oninput="quoteLineEdit(${idx})">
    <input type="number" class="li-price" placeholder="Unit price" step="0.01" min="0" value="${it.unit_price}" oninput="quoteLineEdit(${idx})">
    <button class="icon-btn del" style="color:var(--red)" onclick="removeQuoteLine(${idx})">✕</button>
  </div>`;
}
function addQuoteLine() {
  window._items.push({ product_id: null, description: "", qty: 1, unit_price: 0 });
  $("#q-line-items").insertAdjacentHTML("beforeend", quoteLineHtml(window._items[window._items.length - 1], window._items.length - 1));
  recomputeQuoteTotals();
}
function removeQuoteLine(idx) {
  if (window._items.length <= 1) { toast("At least one line item is required", "error"); return; }
  window._items.splice(idx, 1);
  $("#q-line-items").innerHTML = window._items.map((it, i) => quoteLineHtml(it, i)).join("");
  recomputeQuoteTotals();
}
function quoteProduct(idx, sel) {
  const it = window._items[idx];
  if (sel.value) { it.product_id = Number(sel.value); it.description = sel.options[sel.selectedIndex].text; it.unit_price = Number(sel.selectedOptions[0].dataset.price || 0); }
  else { it.product_id = null; it.description = ""; }
  const el = $$("#q-line-items .line-item")[idx];
  el.querySelector(".li-desc").value = it.description;
  el.querySelector(".li-price").value = it.unit_price;
  recomputeQuoteTotals();
}
function quoteLineEdit(idx) {
  const el = $$("#q-line-items .line-item")[idx];
  window._items[idx].description = el.querySelector(".li-desc").value;
  window._items[idx].qty = Number(el.querySelector(".li-qty").value || 0);
  window._items[idx].unit_price = Number(el.querySelector(".li-price").value || 0);
  recomputeQuoteTotals();
}
function recomputeQuoteTotals() {
  const rate = state.company?.vat_rate ?? 5;
  let subtotal = 0, tax = 0;
  for (const it of window._items) {
    const lt = (it.qty || 0) * (it.unit_price || 0); subtotal += lt;
    const prod = state.products.find((p) => p.id === it.product_id);
    if (prod ? prod.is_taxable : true) tax += lt * rate / 100;
  }
  const disc = Number($("#q-discount").value || 0);
  let total = subtotal + tax - disc; if (total < 0) total = 0;
  $("#q-totals").innerHTML = `
    <div class="t-row"><span class="muted">Subtotal</span><span>${fmtMoney(subtotal)}</span></div>
    <div class="t-row"><span class="muted">VAT (${rate}%)</span><span>${fmtMoney(tax)}</span></div>
    ${disc ? `<div class="t-row"><span class="muted">Discount</span><span>− ${fmtMoney(disc)}</span></div>` : ""}
    <div class="t-row grand"><span>Total</span><span>${fmtMoney(total)}</span></div>`;
}

async function saveQuote(id, statusOverride) {
  const body = {
    customer_id: Number($("#q-customer").value),
    issue_date: $("#q-issue").value,
    valid_until: $("#q-valid").value,
    discount: Number($("#q-discount").value || 0),
    notes: $("#q-notes").value,
    terms: $("#q-terms").value,
    status: statusOverride,
    items: window._items.filter((it) => it.description || it.qty > 0),
  };
  if (!body.customer_id) { toast("Please select a customer", "error"); return; }
  if (!body.items.length) { toast("Add at least one line item", "error"); return; }
  try {
    const r = id ? await api("/quotes/" + id, { method: "PUT", body: JSON.stringify(body) })
                 : await api("/quotes", { method: "POST", body: JSON.stringify(body) });
    toast("Quotation saved"); location.hash = "#/quote/view/" + r.id;
  } catch (e) { toast(e.message, "error"); }
}

async function renderQuoteView(args) {
  const id = args[0];
  const q = (await api("/quotes/" + id)).quote;
  const view = $("#view");
  const itemsHtml = q.items.map((it, i) => `
    <tr><td class="sl-num">${String(i + 1).padStart(2, "0")}</td><td>${esc(it.description)}</td><td class="num">${fmtNum(it.qty)}</td><td class="num">${fmtMoney(it.unit_price)}</td><td class="num">${fmtMoney(it.unit_vat != null ? it.unit_vat : 0)}</td><td class="num">${fmtMoney(it.unit_total != null ? it.unit_total : it.unit_price)}</td></tr>`).join("");
  view.innerHTML = `
    <div class="page-head">
      <div><h2>Quotation ${esc(q.number)}</h2><div class="sub">${esc(q.customer?.name || "")} · <span class="badge ${q.status}">${q.status}</span></div></div>
      <div class="no-print" style="display:flex;gap:8px;flex-wrap:wrap">
        <a class="btn btn-sm" href="#/quote/edit/${q.id}">Edit</a>
        <button class="btn btn-sm" onclick="printDoc('quote', ${q.id})">🖨 Print / PDF</button>
        ${q.status === "converted" ? `<span class="badge converted">Converted to invoice</span>` :
          `<button class="btn btn-sm btn-primary" onclick="convertQuote(${q.id})">→ Convert to Invoice</button>`}
      </div>
    </div>
    <div class="card" style="margin-bottom:16px">
      <div class="grid grid-3">
        <div class="stat"><span class="label">Issued</span><span class="value" style="font-size:17px">${esc(q.issue_date)}</span></div>
        <div class="stat"><span class="label">Valid until</span><span class="value" style="font-size:17px">${esc(q.valid_until)}</span></div>
        <div class="stat"><span class="label">Total</span><span class="value" style="font-size:17px">${fmtMoney(q.total)}</span></div>
      </div>
    </div>
    <div class="card">
      <h3 style="margin-bottom:12px">Line items</h3>
      <div class="table-wrap"><table><thead><tr><th>SL</th><th>Item Description</th><th class="num">Quantity</th><th class="num">Price Before VAT</th><th class="num">${state.company?.vat_rate ?? 5}% VAT</th><th class="num">Total Amount</th></tr></thead><tbody>${itemsHtml}</tbody></table></div>
      <div class="totals-box"><div class="totals">
        <div class="t-row"><span class="muted">Amount Before VAT</span><span>${fmtMoney(q.subtotal)}</span></div>
        <div class="t-row"><span class="muted">VAT Amount (${state.company?.vat_rate ?? 5}%)</span><span>${fmtMoney(q.tax_amount)}</span></div>
        <div class="t-row"><span class="muted">Amount With VAT</span><span>${fmtMoney(Number(q.subtotal) + Number(q.tax_amount))}</span></div>
        ${Number(q.discount) ? `<div class="t-row"><span class="muted">Discount</span><span>− ${fmtMoney(q.discount)}</span></div>` : ""}
        <div class="t-row grand"><span>Total</span><span>${fmtMoney(q.total)}</span></div>
      </div></div>
    </div>`;
}

async function convertQuote(id) {
  if (!confirm("Convert this quotation to an invoice? Stock will be deducted when the invoice is sent.")) return;
  try {
    const r = await api("/quotes/" + id + "/convert", { method: "POST" });
    toast("Converted to invoice " + r.number);
    location.hash = "#/invoice/view/" + r.id;
  } catch (e) { toast(e.message, "error"); }
}

// ================= CUSTOMERS =================
async function renderCustomers() {
  const cs = (await api("/customers")).customers;
  const view = $("#view");
  view.innerHTML = `
    <div class="page-head"><div><h2>Customers</h2><div class="sub">${cs.length} customers</div></div>
      <button class="btn btn-primary" onclick="openCustomerModal()">+ New Customer</button></div>
    <div class="card"><div class="table-wrap"><table><thead><tr><th>Name</th><th>Company</th><th>Contact</th><th>TRN</th><th class="num">Balance</th><th></th></tr></thead>
    <tbody>${cs.length ? cs.map((c) => `
      <tr><td>${esc(c.name)}</td><td>${esc(c.company_name || "—")}</td>
        <td class="small">${esc(c.email || "")}${c.phone ? "<br>" + esc(c.phone) : ""}</td>
        <td class="small mono">${esc(c.trn || "—")}</td>
        <td class="num" style="color:${c.balance > 0 ? "var(--amber)" : "var(--green)"}">${c.balance > 0 ? fmtMoney(c.balance) : "—"}</td>
        <td><div class="row-actions"><button class="btn btn-sm" onclick="openCustomerModal(${c.id})">Edit</button>
        <button class="btn btn-sm" onclick="location.hash='#/statement/${c.id}'">Statement</button>
        <button class="btn btn-sm btn-danger" onclick="deleteCustomer(${c.id})">Del</button></div></td></tr>`).join("")
      : `<tr><td colspan="6" class="empty"><div class="big">👥</div>No customers yet</td></tr>`}</tbody></table></div></div>`;
}

async function openCustomerModal(id) {
  let c = { name: "", company_name: "", email: "", phone: "", address: "", trn: "", credit_limit: 0 };
  if (id) c = (await api("/customers/" + id)).customer;
  openModal(id ? "Edit customer" : "New customer", `
    <div class="form-grid">
      <div class="field"><label>Name *</label><input id="c-name" value="${esc(c.name)}"></div>
      <div class="field"><label>Company</label><input id="c-company" value="${esc(c.company_name)}"></div>
      <div class="field"><label>Email</label><input id="c-email" type="email" value="${esc(c.email)}"></div>
      <div class="field"><label>Phone</label><input id="c-phone" value="${esc(c.phone)}"></div>
      <div class="field full"><label>Address</label><input id="c-address" value="${esc(c.address)}"></div>
      <div class="field"><label>TRN (VAT number)</label><input id="c-trn" value="${esc(c.trn)}"></div>
      <div class="field"><label>Credit limit</label><input id="c-limit" type="number" step="0.01" value="${c.credit_limit}"></div>
    </div>`,
    `<button class="btn btn-primary btn-block" onclick="saveCustomer(${id || "null"})">Save customer</button>`);
}

async function saveCustomer(id) {
  const body = {
    name: $("#c-name").value, company_name: $("#c-company").value, email: $("#c-email").value,
    phone: $("#c-phone").value, address: $("#c-address").value, trn: $("#c-trn").value,
    credit_limit: Number($("#c-limit").value || 0),
  };
  if (!body.name) { toast("Name is required", "error"); return; }
  try {
    if (id) await api("/customers/" + id, { method: "PUT", body: JSON.stringify(body) });
    else await api("/customers", { method: "POST", body: JSON.stringify(body) });
    closeModal(); toast("Customer saved"); renderCustomers();
  } catch (e) { toast(e.message, "error"); }
}
async function deleteCustomer(id) {
  if (!confirm("Delete this customer?")) return;
  try { await api("/customers/" + id, { method: "DELETE" }); toast("Customer deleted"); renderCustomers(); }
  catch (e) { toast(e.message, "error"); }
}

// ================= PRODUCTS =================
async function renderProducts() {
  const ps = (await api("/products")).products;
  const view = $("#view");
  view.innerHTML = `
    <div class="page-head"><div><h2>Products &amp; Stock</h2><div class="sub">${ps.length} products</div></div>
      <button class="btn btn-primary" onclick="openProductModal()">+ New Product</button></div>
    <div class="card"><div class="table-wrap"><table><thead><tr><th>Product</th><th>SKU</th><th class="num">Cost</th><th class="num">Price</th><th class="num">Stock</th><th>Status</th><th></th></tr></thead>
    <tbody>${ps.length ? ps.map((p) => `
      <tr><td>${esc(p.name)}<div class="muted small">${esc(p.description || "")}</div></td>
        <td class="mono small">${esc(p.sku || "—")}</td>
        <td class="num">${fmtMoney(p.cost_price)}</td><td class="num">${fmtMoney(p.sell_price)}</td>
        <td class="num">${fmtNum(p.stock)} ${esc(p.unit)}</td>
        <td>${p.low_stock ? `<span class="badge low">Low stock</span>` : `<span class="badge ok">In stock</span>`}</td>
        <td><div class="row-actions">
          <button class="btn btn-sm" onclick="openProductModal(${p.id})">Edit</button>
          <button class="btn btn-sm" onclick="openStockModal(${p.id}, ${p.stock})">Adjust</button>
          <button class="btn btn-sm" onclick="openMovements(${p.id})">History</button>
          <button class="btn btn-sm btn-danger" onclick="deleteProduct(${p.id})">Del</button>
        </div></td></tr>`).join("")
      : `<tr><td colspan="7" class="empty"><div class="big">📦</div>No products yet</td></tr>`}</tbody></table></div></div>`;
}

async function openProductModal(id) {
  let p = { name: "", sku: "", description: "", unit: "pcs", cost_price: 0, sell_price: 0, stock: 0, low_stock_threshold: 0, is_taxable: true };
  if (id) p = (await api("/products/" + id)).product;
  openModal(id ? "Edit product" : "New product", `
    <div class="form-grid">
      <div class="field full"><label>Name *</label><input id="p-name" value="${esc(p.name)}"></div>
      <div class="field"><label>SKU</label><input id="p-sku" value="${esc(p.sku)}"></div>
      <div class="field"><label>Unit</label><input id="p-unit" value="${esc(p.unit)}"></div>
      <div class="field full"><label>Description</label><input id="p-desc" value="${esc(p.description)}"></div>
      <div class="field"><label>Cost price</label><input id="p-cost" type="number" step="0.01" value="${p.cost_price}"></div>
      <div class="field"><label>Selling price</label><input id="p-sell" type="number" step="0.01" value="${p.sell_price}"></div>
      <div class="field"><label>Initial stock</label><input id="p-stock" type="number" step="any" value="${p.stock}"></div>
      <div class="field"><label>Low-stock alert at</label><input id="p-low" type="number" step="any" value="${p.low_stock_threshold}"></div>
      <div class="field"><label>VAT</label><select id="p-tax"><option value="1" ${p.is_taxable ? "selected" : ""}>Taxable</option><option value="0" ${!p.is_taxable ? "selected" : ""}>Exempt</option></select></div>
    </div>`,
    `<button class="btn btn-primary btn-block" onclick="saveProduct(${id || "null"})">Save product</button>`);
}

async function saveProduct(id) {
  const body = {
    name: $("#p-name").value, sku: $("#p-sku").value, description: $("#p-desc").value,
    unit: $("#p-unit").value, cost_price: Number($("#p-cost").value || 0), sell_price: Number($("#p-sell").value || 0),
    stock: Number($("#p-stock").value || 0), low_stock_threshold: Number($("#p-low").value || 0),
    is_taxable: $("#p-tax").value === "1",
  };
  if (!body.name) { toast("Name is required", "error"); return; }
  try {
    if (id) await api("/products/" + id, { method: "PUT", body: JSON.stringify(body) });
    else await api("/products", { method: "POST", body: JSON.stringify(body) });
    closeModal(); toast("Product saved"); renderProducts();
  } catch (e) { toast(e.message, "error"); }
}
async function deleteProduct(id) {
  if (!confirm("Delete this product?")) return;
  try { await api("/products/" + id, { method: "DELETE" }); toast("Product deleted"); renderProducts(); }
  catch (e) { toast(e.message, "error"); }
}

function openStockModal(id, current) {
  openModal("Adjust stock", `
    <p class="muted" style="margin-bottom:14px">Current stock: <strong>${fmtNum(current)}</strong>. Enter a positive or negative change (e.g. +5 to receive, −2 to remove).</p>
    <div class="form-grid" style="grid-template-columns:1fr">
      <div class="field"><label>Change (+/−) *</label><input type="number" id="s-change" step="any" placeholder="+5 or -2"></div>
      <div class="field"><label>Reason</label><input type="text" id="s-reason" placeholder="e.g. Purchase, damage, correction"></div>
    </div>`,
    `<button class="btn btn-primary btn-block" onclick="submitStockAdjust(${id})">Apply adjustment</button>`);
}
async function submitStockAdjust(id) {
  const body = { change: Number($("#s-change").value), reason: $("#s-reason").value };
  if (!body.change) { toast("Enter a change amount", "error"); return; }
  try { await api("/stock/" + id + "/adjust", { method: "POST", body: JSON.stringify(body) }); closeModal(); toast("Stock updated"); renderProducts(); }
  catch (e) { toast(e.message, "error"); }
}

async function openMovements(id) {
  const m = (await api("/stock/" + id + "/movements")).movements;
  openModal("Stock history", `
    <div class="table-wrap"><table><thead><tr><th>Date</th><th class="num">Change</th><th>Reason</th><th>Ref</th></tr></thead>
    <tbody>${m.length ? m.map((x) => `<tr><td class="small">${esc(x.created_at)}</td>
      <td class="num" style="color:${x.change >= 0 ? "var(--green)" : "var(--red)"}">${x.change >= 0 ? "+" : ""}${fmtNum(x.change)}</td>
      <td>${esc(x.reason)}</td><td class="small mono">${esc(x.reference_type || "")}</td></tr>`).join("")
      : `<tr><td colspan="4" class="muted">No movements</td></tr>`}</tbody></table></div>`, "");
}

// ================= PAYMENTS =================
async function renderPayments() {
  const ps = (await api("/payments")).payments;
  const view = $("#view");
  const total = ps.reduce((s, p) => s + Number(p.amount), 0);
  view.innerHTML = `
    <div class="page-head"><div><h2>Payments</h2><div class="sub">${ps.length} payments · total ${fmtMoney(total)}</div></div></div>
    <div class="card"><div class="table-wrap"><table><thead><tr><th>Date</th><th>Invoice</th><th>Customer</th><th>Method</th><th>Reference</th><th class="num">Amount</th></tr></thead>
    <tbody>${ps.length ? ps.map((p) => `
      <tr><td class="small">${esc(p.date)}</td><td class="mono link" onclick="location.hash='#/invoice/view/${p.invoice_id}'">${esc(p.invoice_number)}</td>
        <td>${esc(p.customer_name || "—")}</td><td>${esc(p.method.replace("_", " "))}</td>
        <td class="small mono">${esc(p.reference || "—")}</td><td class="num" style="color:var(--green)">${fmtMoney(p.amount)}</td></tr>`).join("")
      : `<tr><td colspan="6" class="empty"><div class="big">💵</div>No payments recorded yet</td></tr>`}</tbody></table></div></div>`;
}

// ================= EXPENSES =================
const EXPENSE_CATEGORIES = [
  "Utilities (Electricity & Water)", "Rent", "Salaries & Wages", "Supplies & Materials",
  "Telephone & Internet", "Transport & Fuel", "Maintenance & Repairs", "Marketing & Advertising",
  "Insurance", "Government Fees & Licences", "Other",
];

async function renderExpenses() {
  const ex = (await api("/expenses")).expenses;
  const view = $("#view");
  const total = ex.reduce((s, e) => s + Number(e.amount), 0);
  // group totals by category for summary
  const byCat = {};
  ex.forEach((e) => { byCat[e.category] = (byCat[e.category] || 0) + Number(e.amount); });

  view.innerHTML = `
    <div class="page-head"><div><h2>Expenses</h2><div class="sub">${ex.length} expense entries · total ${fmtMoney(total)}</div></div>
      <button class="btn btn-primary" onclick="openExpenseModal()">+ Add Expense</button></div>
    <div class="card"><div class="table-wrap"><table><thead><tr><th>Date</th><th>Category</th><th>Description</th><th class="num">Amount</th><th></th></tr></thead>
    <tbody>${ex.length ? ex.map((e) => `
      <tr><td class="small">${esc(e.date)}</td><td>${esc(e.category)}</td><td>${esc(e.description || "—")}</td>
        <td class="num" style="color:var(--red)">${fmtMoney(e.amount)}</td>
        <td><div class="row-actions">
          <button class="btn btn-sm" onclick="openExpenseModal(${e.id})">Edit</button>
          <button class="btn btn-sm btn-danger" onclick="deleteExpense(${e.id})">Del</button>
        </div></td></tr>`).join("")
      : `<tr><td colspan="5" class="empty"><div class="big">🧾</div>No expenses recorded yet</td></tr>`}</tbody></table></div></div>`;
}

async function openExpenseModal(id) {
  let e = { date: today(), category: EXPENSE_CATEGORIES[0], description: "", amount: 0 };
  if (id) {
    const all = (await api("/expenses")).expenses;
    const found = all.find((x) => x.id === id);
    if (found) e = found;
  }
  openModal(id ? "Edit expense" : "Add expense", `
    <div class="form-grid">
      <div class="field"><label>Date</label><input type="date" id="e-date" value="${esc(e.date)}"></div>
      <div class="field"><label>Amount *</label><input type="number" id="e-amount" step="0.01" min="0.01" value="${e.amount}"></div>
      <div class="field full"><label>Category</label>
        <select id="e-category">${EXPENSE_CATEGORIES.map((c) => `<option ${e.category === c ? "selected" : ""}>${esc(c)}</option>`).join("")}</select>
      </div>
      <div class="field full"><label>Description</label><input id="e-desc" value="${esc(e.description)}" placeholder="e.g. DEWA bill, rent for shop, staff salary"></div>
    </div>`,
    `<button class="btn btn-primary btn-block" onclick="saveExpense(${id || "null"})">Save expense</button>`);
}

async function saveExpense(id) {
  const body = {
    date: $("#e-date").value,
    amount: Number($("#e-amount").value || 0),
    category: $("#e-category").value,
    description: $("#e-desc").value,
  };
  if (!body.amount || body.amount <= 0) { toast("Enter a valid amount", "error"); return; }
  try {
    if (id) await api("/expenses/" + id, { method: "PUT", body: JSON.stringify(body) });
    else await api("/expenses", { method: "POST", body: JSON.stringify(body) });
    closeModal(); toast("Expense saved"); renderExpenses();
  } catch (e) { toast(e.message, "error"); }
}

async function deleteExpense(id) {
  if (!confirm("Delete this expense?")) return;
  try { await api("/expenses/" + id, { method: "DELETE" }); toast("Expense deleted"); renderExpenses(); }
  catch (e) { toast(e.message, "error"); }
}

// ================= STATEMENTS =================
async function renderStatement(args) {
  const preselected = args[0] ? Number(args[0]) : null;
  const customers = (await api("/customers")).customers;
  const view = $("#view");
  view.innerHTML = `
    <div class="page-head">
      <div><h2>Customer Statements</h2><div class="sub">Generate a statement of account to send to a customer</div></div>
    </div>
    <div class="card" style="max-width:900px">
      <div class="toolbar">
        <div class="searchbar">
          <label class="small">Customer</label>
          <select id="st-customer">${customers.map((c) => `<option value="${c.id}" ${preselected === c.id ? "selected" : ""}>${esc(c.name)}${c.company_name ? " — " + esc(c.company_name) : ""}</option>`).join("")}</select>
          <label class="small">From</label><input type="date" id="st-from" value="${firstOfYear()}">
          <label class="small">To</label><input type="date" id="st-to" value="${today()}">
          <button class="btn btn-sm btn-primary" onclick="loadStatement()">Generate</button>
          <button class="btn btn-sm" onclick="printStatement()">🖨 Print / PDF</button>
        </div>
      </div>
      <div id="statement-body"></div>
    </div>`;
  window._stmt = { from: $("#st-from").value, to: $("#st-to").value };
  loadStatement();
}

async function loadStatement() {
  const customer_id = $("#st-customer").value;
  const from = $("#st-from").value, to = $("#st-to").value;
  window._stmt = { customer_id, from, to };
  const d = await api(`/reports/statement?customer_id=${customer_id}&from=${from}&to=${to}`);
  const cust = d.customer;
  const rows = d.transactions.map((t) => `
    <tr>
      <td class="small">${esc(t.date)}</td>
      <td>${esc(t.desc)}<div class="muted small mono">${esc(t.ref || "")}</div></td>
      <td class="num">${t.debit ? fmtMoney(t.debit) : ""}</td>
      <td class="num">${t.credit ? fmtMoney(t.credit) : ""}</td>
      <td class="num" style="font-weight:600">${fmtMoney(t.balance)}</td>
    </tr>`).join("");
  $("#statement-body").innerHTML = `
    <div class="grid grid-3" style="margin:12px 0 16px">
      <div class="stat"><span class="label">Customer</span><span class="value" style="font-size:16px">${esc(cust.name)}</span><span class="delta muted">${esc(cust.company_name || "")}</span></div>
      <div class="stat"><span class="label">Opening Balance</span><span class="value" style="font-size:16px">${fmtMoney(d.opening_balance)}</span></div>
      <div class="stat"><span class="label">Closing Balance</span><span class="value" style="font-size:16px;color:${d.closing_balance > 0 ? "var(--amber)" : "var(--green)"}">${fmtMoney(d.closing_balance)}</span></div>
    </div>
    <div class="table-wrap"><table><thead><tr><th>Date</th><th>Description</th><th class="num">Debit</th><th class="num">Credit</th><th class="num">Balance</th></tr></thead>
    <tbody>${rows || `<tr><td colspan="5" class="muted">No transactions in this period</td></tr>`}</tbody></table></div>`;
}

async function printStatement() {
  const { customer_id, from, to } = window._stmt || {};
  if (!customer_id) { toast("Select a customer first", "error"); return; }
  const d = await api(`/reports/statement?customer_id=${customer_id}&from=${from}&to=${to}`);
  const comp = (await api("/settings")).company;
  const cust = d.customer;
  const brand = comp?.name || "My Company LLC";
  const tagline = comp?.tagline || "";
  const rows = d.transactions.map((t) => `
    <tr>
      <td>${esc(t.date)}</td>
      <td>${esc(t.desc)}${t.ref ? ' <span class="ref">' + esc(t.ref) + "</span>" : ""}</td>
      <td class="num">${t.debit ? fmtMoney(t.debit) : ""}</td>
      <td class="num">${t.credit ? fmtMoney(t.credit) : ""}</td>
      <td class="num">${fmtMoney(t.balance)}</td>
    </tr>`).join("");
  const html = '<!DOCTYPE html><html><head><meta charset="utf-8"><title>Statement - ' + esc(cust.name) + '</title><style>' +
    '*{margin:0;padding:0;box-sizing:border-box}' +
    'body{font-family:"Segoe UI",-apple-system,Arial,sans-serif;color:#1a202c;font-size:13px;background:#fff}' +
    '.page{max-width:820px;margin:0 auto}' +
    '.header{background:linear-gradient(135deg,#0c3740 0%,#0a4a54 45%,#037c84 100%);color:#fff;padding:24px 40px;position:relative;overflow:hidden}' +
    '.header-top{display:flex;align-items:center;gap:18px}' +
    '.logo-box{background:#fff;border-radius:10px;padding:8px 12px;flex-shrink:0;box-shadow:0 2px 8px rgba(0,0,0,.15)}' +
    '.logo-box img{height:52px;width:auto;display:block}' +
    '.doc-type{font-size:30px;font-weight:800;letter-spacing:2px;line-height:1}' +
    '.brand{font-size:16px;font-weight:700;margin-top:6px}' +
    '.tagline{font-size:11px;opacity:.9;margin-top:2px;letter-spacing:1.5px;text-transform:uppercase}' +
    '.trn-chip{display:inline-block;margin-top:10px;font-size:10px;letter-spacing:.5px;background:rgba(255,255,255,.14);padding:4px 10px;border-radius:20px}' +
    '.body{padding:30px 40px}' +
    '.label{font-size:11px;text-transform:uppercase;letter-spacing:1.5px;color:#037c84;font-weight:800;margin-bottom:6px}' +
    '.info-row{display:flex;justify-content:space-between;gap:30px;margin-bottom:24px}' +
    '.bill-to .name{font-size:16px;font-weight:700}' +
    '.bill-to .dim{color:#64748b;margin-top:2px}' +
    '.meta{text-align:right}' +
    '.m-row{display:flex;justify-content:space-between;gap:16px;padding:3px 0;border-bottom:1px dashed #e2e8f0;min-width:220px}' +
    '.m-row .k{color:#64748b}' +
    '.m-row .v{font-weight:700}' +
    'table{width:100%;border-collapse:collapse;margin-top:8px}' +
    'table thead th{background:#0c3740;color:#fff;padding:10px 14px;font-size:11px;text-transform:uppercase;letter-spacing:.7px;text-align:left}' +
    'table thead th.num,table td.num{text-align:right}' +
    'table td{padding:10px 14px;border-bottom:1px solid #e2e8f0}' +
    'table tbody tr:nth-child(even){background:#f8fafc}' +
    '.ref{color:#64748b;font-size:11px}' +
    '.summary{display:flex;justify-content:flex-end;margin-top:18px}' +
    '.summary-box{width:280px;border:1px solid #e2e8f0;border-radius:10px;overflow:hidden}' +
    '.sb-head{background:#037c84;color:#fff;font-size:11px;font-weight:800;letter-spacing:1.5px;padding:9px 16px;text-transform:uppercase}' +
    '.s-row{display:flex;justify-content:space-between;padding:9px 16px;font-size:13px;border-top:1px solid #f1f5f9}' +
    '.s-row span:first-child{color:#475569}' +
    '.s-row.big{font-size:16px;font-weight:800;color:#0c3740;border-top:2px solid #0c3740}' +
    '.s-row.big span:last-child{color:#037c84}' +
    '.footer{background:#0c3740;color:#d7f0f2;text-align:center;padding:16px 40px;font-size:11px;letter-spacing:.4px;margin-top:36px}' +
    '.footer strong{color:#fff}' +
    '@media print{.page{max-width:none}}' +
    '</style></head><body><div class="page">' +
    '<div class="header"><div class="header-top"><div class="logo-box"><img src="/logo.png"></div>' +
    '<div><div class="doc-type">STATEMENT OF ACCOUNT</div><div class="brand">' + esc(brand) + '</div>' +
    (tagline ? '<div class="tagline">' + esc(tagline) + '</div>' : "") +
    (comp?.trn ? '<div class="trn-chip">TRN: ' + esc(comp.trn) + '</div>' : "") + '</div></div></div>' +
    '<div class="body">' +
    '<div class="info-row"><div class="bill-to"><div class="label">Customer</div>' +
    '<div class="name">' + esc(cust.name) + '</div>' +
    (cust.company_name ? '<div class="dim">' + esc(cust.company_name) + '</div>' : "") +
    (cust.address ? '<div class="dim">' + esc(cust.address) + '</div>' : "") +
    (cust.trn ? '<div class="dim">TRN: ' + esc(cust.trn) + '</div>' : "") +
    '</div><div class="meta"><div class="label">Statement Details</div>' +
    '<div class="m-row"><span class="k">Period</span><span class="v">' + from + ' → ' + to + '</span></div>' +
    '<div class="m-row"><span class="k">Statement Date</span><span class="v">' + today() + '</span></div>' +
    '<div class="m-row"><span class="k">Currency</span><span class="v">' + esc(d.currency) + '</span></div>' +
    '</div></div>' +
    '<table><thead><tr><th>Date</th><th>Description</th><th class="num">Debit</th><th class="num">Credit</th><th class="num">Balance</th></tr></thead>' +
    '<tbody>' + (rows || '<tr><td colspan="5">No transactions</td></tr>') + '</tbody></table>' +
    '<div class="summary"><div class="summary-box"><div class="sb-head">Summary</div>' +
    '<div class="s-row"><span>Opening Balance</span><span>' + fmtMoney(d.opening_balance) + '</span></div>' +
    '<div class="s-row big"><span>Closing Balance</span><span>' + fmtMoney(d.closing_balance) + '</span></div>' +
    '</div></div></div>' +
    '<div class="footer"><strong>' + esc(brand) + '</strong> · Thank you for your business!</div>' +
    '</div><script>window.onload=function(){window.print();}</script></body></html>';
  const w = window.open("", "_blank");
  w.document.write(html);
  w.document.close();
}

// ================= REPORTS =================
async function renderReports() {
  const view = $("#view");
  view.innerHTML = `
    <div class="page-head"><div><h2>Reports</h2><div class="sub">Insights into your business</div></div></div>
    <div class="tabs" style="margin-bottom:16px">
      <button class="tab active" onclick="showReport('sales', this)">Sales</button>
      <button class="tab" onclick="showReport('vat', this)">VAT / Tax</button>
      <button class="tab" onclick="showReport('pl', this)">Profit &amp; Loss</button>
      <button class="tab" onclick="showReport('profit', this)">Profit</button>
    </div>
    <div id="report-body"></div>`;
  showReport("sales", $(".tab"));
}

async function showReport(type, btn) {
  $$(".tab").forEach((t) => t.classList.remove("active"));
  btn.classList.add("active");
  const body = $("#report-body");
  if (type === "sales") {
    body.innerHTML = `<div class="card"><div class="toolbar">
      <div class="searchbar"><label class="small">From</label><input type="date" id="rep-from" value="${firstOfMonth()}">
      <label class="small">To</label><input type="date" id="rep-to" value="${today()}">
      <button class="btn btn-sm btn-primary" onclick="loadSalesReport()">Apply</button></div></div>
      <div id="sales-report"></div></div>`;
    loadSalesReport();
  } else if (type === "vat") {
    const v = (await api("/reports/vat"));
    body.innerHTML = `<div class="card"><h3 style="margin-bottom:14px">VAT report (rate ${v.vat_rate}%)</h3>
      <div class="stat" style="margin-bottom:16px"><span class="label">Total VAT collected (sales)</span><span class="value" style="color:var(--primary)">${fmtMoney(v.sales_tax)}</span></div>
      <div class="table-wrap"><table><thead><tr><th>Invoice</th><th>Date</th><th class="num">Total</th><th class="num">VAT</th></tr></thead>
      <tbody>${v.invoices.map((i) => `<tr><td class="mono">${esc(i.number)}</td><td class="small">${esc(i.date)}</td><td class="num">${fmtMoney(i.total)}</td><td class="num">${fmtMoney(i.tax)}</td></tr>`).join("")}</tbody></table></div></div>`;
  } else if (type === "pl") {
    body.innerHTML = `<div class="card"><div class="toolbar">
      <div class="searchbar"><label class="small">From</label><input type="date" id="pl-from" value="${firstOfYear()}">
      <label class="small">To</label><input type="date" id="pl-to" value="${today()}">
      <button class="btn btn-sm btn-primary" onclick="loadPLReport()">Calculate</button>
      <button class="btn btn-sm" onclick="printPL()">🖨 Print / PDF</button></div></div>
      <div id="pl-report"></div></div>`;
    window._plRange = { from: $("#pl-from").value, to: $("#pl-to").value };
    loadPLReport();
  } else if (type === "profit") {
    const p = (await api("/reports/profit"));
    const margin = p.revenue ? ((p.profit / p.revenue) * 100).toFixed(1) : "0";
    body.innerHTML = `<div class="card" style="margin-bottom:16px"><div class="grid grid-3">
      <div class="stat"><span class="label">Revenue</span><span class="value">${fmtMoney(p.revenue)}</span></div>
      <div class="stat"><span class="label">Cost of goods</span><span class="value">${fmtMoney(p.cost)}</span></div>
      <div class="stat"><span class="label">Gross profit</span><span class="value" style="color:${p.profit >= 0 ? "var(--green)" : "var(--red)"}">${fmtMoney(p.profit)} <span class="small">(${margin}%)</span></span></div>
    </div></div>
    <div class="card"><div class="table-wrap"><table><thead><tr><th>Invoice</th><th>Item</th><th class="num">Qty</th><th class="num">Revenue</th><th class="num">Cost</th><th class="num">Profit</th></tr></thead>
    <tbody>${p.detail.map((d) => `<tr><td class="mono small">${esc(d.invoice)}</td><td>${esc(d.description)}</td><td class="num">${fmtNum(d.qty)}</td><td class="num">${fmtMoney(d.revenue)}</td><td class="num">${fmtMoney(d.cost)}</td><td class="num" style="color:${d.profit >= 0 ? "var(--green)" : "var(--red)"}">${fmtMoney(d.profit)}</td></tr>`).join("")}</tbody></table></div></div>`;
  }
}

async function loadPLReport() {
  const from = $("#pl-from").value, to = $("#pl-to").value;
  window._plRange = { from, to };
  const d = await api(`/reports/pl?from=${from}&to=${to}`);
  const expRows = d.expenses_by_cat.length
    ? d.expenses_by_cat.map((e) => `<tr><td>${esc(e.category)}</td><td class="num">${e.count}</td><td class="num" style="color:var(--red)">${fmtMoney(e.total)}</td></tr>`).join("")
    : `<tr><td colspan="3" class="muted">No expenses in this period</td></tr>`;
  const netColor = d.net_profit >= 0 ? "var(--green)" : "var(--red)";
  const grossColor = d.gross_profit >= 0 ? "var(--green)" : "var(--red)";
  $("#pl-report").innerHTML = `
    <div class="grid grid-3" style="margin-bottom:16px">
      <div class="card"><div class="stat"><span class="label">Revenue (Sales)</span><span class="value">${fmtMoney(d.revenue)}</span></div></div>
      <div class="card"><div class="stat"><span class="label">Cost of Goods Sold</span><span class="value" style="color:var(--red)">${fmtMoney(d.cogs)}</span></div></div>
      <div class="card"><div class="stat"><span class="label">Gross Profit</span><span class="value" style="color:${grossColor}">${fmtMoney(d.gross_profit)}</span></div></div>
    </div>
    <div class="card" style="margin-bottom:16px">
      <h3 style="margin-bottom:12px">Expenses (${from} → ${to})</h3>
      <div class="table-wrap"><table><thead><tr><th>Category</th><th class="num">Entries</th><th class="num">Amount</th></tr></thead><tbody>${expRows}</tbody></table></div>
      <div class="totals-box"><div class="totals">
        <div class="t-row grand"><span>Total Expenses</span><span style="color:var(--red)">${fmtMoney(d.total_expenses)}</span></div>
      </div></div>
    </div>
    <div class="card" style="border-left:4px solid ${d.net_profit >= 0 ? "var(--green)" : "var(--red)"}">
      <div class="stat"><span class="label">Net Profit / (Loss)</span>
        <span class="value" style="font-size:28px;color:${netColor}">${fmtMoney(d.net_profit)}</span>
        <span class="delta muted">${d.gross_profit} − ${d.total_expenses} = ${d.net_profit}</span></div>
    </div>`;
}

async function printPL() {
  const { from, to } = window._plRange || {};
  if (!from || !to) { toast("Select a date range first", "error"); return; }
  const d = await api(`/reports/pl?from=${from}&to=${to}`);
  const comp = (await api("/settings")).company;
  const brand = comp?.name || "My Company LLC";
  const expRows = d.expenses_by_cat.map((e) => `<tr><td>${esc(e.category)}</td><td class="num">${e.count}</td><td class="num">${fmtMoney(e.total)}</td></tr>`).join("");
  const netColor = d.net_profit >= 0 ? "#16a34a" : "#dc2626";
  const html = '<!DOCTYPE html><html><head><meta charset="utf-8"><title>Profit &amp; Loss Statement</title><style>' +
    '*{margin:0;padding:0;box-sizing:border-box}' +
    'body{font-family:"Segoe UI",-apple-system,Arial,sans-serif;color:#1a202c;font-size:13px;background:#fff}' +
    '.page{max-width:820px;margin:0 auto;padding:40px}' +
    '.header{background:linear-gradient(135deg,#0c3740 0%,#0a4a54 45%,#037c84 100%);color:#fff;padding:28px 34px;border-radius:12px;margin-bottom:28px}' +
    '.doc-type{font-size:30px;font-weight:800;letter-spacing:1.5px}' +
    '.brand{font-size:16px;font-weight:700;margin-top:6px}' +
    '.range{font-size:12px;opacity:.9;margin-top:8px}' +
    '.label{font-size:11px;text-transform:uppercase;letter-spacing:1.5px;color:#037c84;font-weight:800;margin-bottom:10px}' +
    'table{width:100%;border-collapse:collapse}' +
    'table.pl th{background:#0c3740;color:#fff;padding:10px 14px;font-size:11px;text-transform:uppercase;text-align:left}' +
    'table.pl td{padding:11px 14px;border-bottom:1px solid #e2e8f0}' +
    'table.pl td.num{text-align:right}' +
    '.section{margin-top:26px}' +
    '.line{display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px dashed #e2e8f0}' +
    '.line span:first-child{color:#475569}' +
    '.line.bold{font-weight:800;font-size:15px;border-bottom:2px solid #0c3740;padding-top:12px}' +
    '.line.net{font-size:18px;font-weight:800;padding-top:14px;border-bottom:none}' +
    '.footer{background:#0c3740;color:#d7f0f2;text-align:center;padding:16px;font-size:11px;margin-top:36px;border-radius:10px}' +
    '.footer strong{color:#fff}' +
    '@media print{.page{max-width:none}}' +
    '</style></head><body><div class="page">' +
    '<div class="header"><div class="doc-type">PROFIT &amp; LOSS STATEMENT</div>' +
    '<div class="brand">' + esc(brand) + '</div>' +
    '<div class="range">Period: ' + from + ' to ' + to + '</div></div>' +
    '<div class="label">Income</div>' +
    '<div class="line"><span>Revenue (Sales)</span><span>' + fmtMoney(d.revenue) + '</span></div>' +
    '<div class="line"><span>Cost of Goods Sold</span><span>− ' + fmtMoney(d.cogs) + '</span></div>' +
    '<div class="line bold"><span>Gross Profit</span><span>' + fmtMoney(d.gross_profit) + '</span></div>' +
    '<div class="section"><div class="label">Expenses</div>' +
    '<table class="pl"><thead><tr><th>Category</th><th class="num">Entries</th><th class="num">Amount</th></tr></thead><tbody>' + expRows + '</tbody></table>' +
    '<div class="line bold"><span>Total Expenses</span><span>− ' + fmtMoney(d.total_expenses) + '</span></div></div>' +
    '<div class="line net"><span>Net Profit / (Loss)</span><span style="color:' + netColor + '">' + fmtMoney(d.net_profit) + '</span></div>' +
    '<div class="footer"><strong>' + esc(brand) + '</strong> · Generated on ' + today() + '</div>' +
    '</div><script>window.onload=function(){window.print();}</script></body></html>';
  const w = window.open("", "_blank");
  w.document.write(html);
  w.document.close();
}

async function loadSalesReport() {
  const from = $("#rep-from").value, to = $("#rep-to").value;
  const r = await api(`/reports/sales?from=${from}&to=${to}`);
  $("#sales-report").innerHTML = `
    <div class="stat" style="margin:8px 0 16px"><span class="label">Total sales (${from} → ${to})</span><span class="value">${fmtMoney(r.total)}</span><span class="delta muted">VAT included: ${fmtMoney(r.tax_total)}</span></div>
    <div class="table-wrap"><table><thead><tr><th>Number</th><th>Customer</th><th>Date</th><th class="num">Total</th><th>Status</th></tr></thead>
    <tbody>${r.invoices.length ? r.invoices.map((i) => `<tr class="clickable" onclick="location.hash='#/invoice/view/${i.id}'"><td class="mono">${esc(i.number)}</td><td>${esc(i.customer?.name || "—")}</td><td class="small">${esc(i.issue_date)}</td><td class="num">${fmtMoney(i.total)}</td><td><span class="badge ${i.status}">${i.status}</span></td></tr>`).join("") : `<tr><td colspan="5" class="empty">No sales in this period</td></tr>`}</tbody></table></div>`;
}

// ================= SETTINGS =================
async function renderSettings() {
  const c = state.company || (await api("/settings")).company;
  const view = $("#view");
  view.innerHTML = `
    <div class="page-head"><div><h2>Company Settings</h2><div class="sub">Your business details appear on invoices &amp; quotations</div></div></div>
    <div class="card" style="max-width:720px">
      <div class="form-grid">
        <div class="field"><label>Company name *</label><input id="s-name" value="${esc(c.name)}"></div>
        <div class="field"><label>Tagline (on documents)</label><input id="s-tagline" value="${esc(c.tagline || "")}" placeholder="e.g. Uniforms Made With Care"></div>
        <div class="field"><label>Legal name</label><input id="s-legal" value="${esc(c.legal_name)}"></div>
        <div class="field"><label>TRN (VAT registration number)</label><input id="s-trn" value="${esc(c.trn)}"></div>
        <div class="field"><label>Phone</label><input id="s-phone" value="${esc(c.phone)}"></div>
        <div class="field"><label>Email</label><input id="s-email" value="${esc(c.email)}"></div>
        <div class="field"><label>Currency</label><select id="s-currency">${["AED","USD","EUR","GBP","SAR","INR"].map((x) => `<option ${c.currency === x ? "selected" : ""}>${x}</option>`).join("")}</select></div>
        <div class="field"><label>VAT rate (%)</label><input id="s-vat" type="number" step="0.1" value="${c.vat_rate}"></div>
        <div class="field"><label>Invoice prefix</label><input id="s-invpre" value="${esc(c.invoice_prefix)}"></div>
        <div class="field"><label>Quote prefix</label><input id="s-quopre" value="${esc(c.quote_prefix)}"></div>
        <div class="field full"><label>Address</label><input id="s-address" value="${esc(c.address)}"></div>
        <div class="field full"><label>Default payment terms</label><input id="s-terms" value="${esc(c.payment_terms)}"></div>
        <div class="field full"><label>Default invoice notes</label><textarea id="s-notes">${esc(c.invoice_notes)}</textarea></div>
      </div>
      <div class="form-actions"><button class="btn btn-primary" onclick="saveSettings()">Save settings</button></div>
    </div>`;
}

async function saveSettings() {
  const body = {
    name: $("#s-name").value, tagline: $("#s-tagline").value, legal_name: $("#s-legal").value, trn: $("#s-trn").value,
    phone: $("#s-phone").value, email: $("#s-email").value, currency: $("#s-currency").value,
    vat_rate: Number($("#s-vat").value || 0), invoice_prefix: $("#s-invpre").value,
    quote_prefix: $("#s-quopre").value, address: $("#s-address").value,
    payment_terms: $("#s-terms").value, invoice_notes: $("#s-notes").value,
  };
  if (!body.name) { toast("Company name is required", "error"); return; }
  try {
    await api("/settings", { method: "PUT", body: JSON.stringify(body) });
    state.company = body;
    $("#sidebar-company").textContent = body.name;
    toast("Settings saved");
  } catch (e) { toast(e.message, "error"); }
}

// ================= USERS =================
async function renderUsers() {
  const us = (await api("/users")).users;
  const view = $("#view");
  view.innerHTML = `
    <div class="page-head"><div><h2>Users</h2><div class="sub">Team members with access to this system</div></div>
      <button class="btn btn-primary" onclick="openUserModal()">+ New User</button></div>
    <div class="card"><div class="table-wrap"><table><thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th><th></th></tr></thead>
    <tbody>${us.map((u) => `
      <tr><td>${esc(u.name)}</td><td>${esc(u.email)}</td>
        <td><span class="badge ${u.role}">${u.role}</span></td>
        <td>${u.active ? `<span class="badge ok">Active</span>` : `<span class="badge expired">Disabled</span>`}</td>
        <td><div class="row-actions">
          <button class="btn btn-sm" onclick="openUserModal(${u.id})">Edit</button>
          ${u.id !== state.user.id ? `<button class="btn btn-sm btn-danger" onclick="deleteUser(${u.id})">Del</button>` : ""}
        </div></td></tr>`).join("")}</tbody></table></div></div>`;
}

async function openUserModal(id) {
  let u = { name: "", email: "", role: "staff", active: true };
  if (id) { const r = (await api("/users")).users.find((x) => x.id === id); if (r) u = r; }
  openModal(id ? "Edit user" : "New user", `
    <div class="form-grid" style="grid-template-columns:1fr">
      <div class="field"><label>Name</label><input id="u-name" value="${esc(u.name)}"></div>
      <div class="field"><label>Email</label><input id="u-email" type="email" value="${esc(u.email)}"></div>
      <div class="field"><label>Password ${id ? "(leave blank to keep)" : ""}</label><input id="u-pass" type="password" placeholder="${id ? "••••••••" : "Set a password"}"></div>
      <div class="field"><label>Role</label><select id="u-role"><option value="staff" ${u.role === "staff" ? "selected" : ""}>Staff</option><option value="admin" ${u.role === "admin" ? "selected" : ""}>Admin</option></select></div>
      ${id ? `<div class="field"><label>Status</label><select id="u-active"><option value="1" ${u.active ? "selected" : ""}>Active</option><option value="0" ${!u.active ? "selected" : ""}>Disabled</option></select></div>` : ""}
    </div>`,
    `<button class="btn btn-primary btn-block" onclick="saveUser(${id || "null"})">Save user</button>`);
}

async function saveUser(id) {
  const body = { name: $("#u-name").value, email: $("#u-email").value, role: $("#u-role").value };
  if ($("#u-pass").value) body.password = $("#u-pass").value;
  if (id) body.active = $("#u-active")?.value === "1";
  try {
    if (id) await api("/users/" + id, { method: "PUT", body: JSON.stringify(body) });
    else await api("/users", { method: "POST", body: JSON.stringify(body) });
    closeModal(); toast("User saved"); renderUsers();
  } catch (e) { toast(e.message, "error"); }
}
async function deleteUser(id) {
  if (!confirm("Delete this user?")) return;
  try { await api("/users/" + id, { method: "DELETE" }); toast("User deleted"); renderUsers(); }
  catch (e) { toast(e.message, "error"); }
}

// ================= PRINT / PDF =================
async function printDoc(type, id) {
  let doc, comp;
  try { comp = (await api("/settings")).company; } catch {}
  if (type === "invoice") doc = (await api("/invoices/" + id)).invoice;
  else doc = (await api("/quotes/" + id)).quote;
  const isQuote = type === "quote";
  const docType = isQuote ? "QUOTATION" : "INVOICE";
  const cust = doc.customer || {};
  const brand = comp?.name || "My Company LLC";
  const tagline = comp?.tagline || "";
  const vatRate = comp?.vat_rate ?? 5;

  const items = doc.items.map((it, i) => {
    const sl = String(i + 1).padStart(2, "0");
    const qty = Number(it.qty);
    const unitVat = Number(it.unit_vat != null ? it.unit_vat : 0);
    const unitTotal = Number(it.unit_total != null ? it.unit_total : it.unit_price);
    return '<tr><td class="sl">' + sl + '</td><td>' + esc(it.description) + '</td><td class="num">' + fmtNum(qty) +
      '</td><td class="num">' + fmtMoney(it.unit_price) + '</td><td class="num">' + fmtMoney(unitVat) +
      '</td><td class="num">' + fmtMoney(unitTotal) + '</td></tr>';
  }).join("");

  const metaRows = isQuote
    ? '<div class="m-row"><span class="k">Quotation No.</span><span class="v">' + esc(doc.number) + '</span></div>' +
      '<div class="m-row"><span class="k">Date</span><span class="v">' + esc(doc.issue_date) + '</span></div>' +
      '<div class="m-row"><span class="k">Valid Until</span><span class="v">' + esc(doc.valid_until) + '</span></div>'
    : '<div class="m-row"><span class="k">Invoice No.</span><span class="v">' + esc(doc.number) + '</span></div>' +
      '<div class="m-row"><span class="k">Date</span><span class="v">' + esc(doc.issue_date) + '</span></div>' +
      '<div class="m-row"><span class="k">Due Date</span><span class="v">' + esc(doc.due_date) + '</span></div>';

  const custLines = [
    cust.name ? '<div class="name">' + esc(cust.name) + '</div>' : "",
    cust.company_name ? "<div>" + esc(cust.company_name) + "</div>" : "",
    cust.address ? '<div class="dim">' + esc(cust.address) + "</div>" : "",
    cust.phone ? '<div class="dim">Tel: ' + esc(cust.phone) + "</div>" : "",
    cust.trn ? '<div class="dim">TRN: ' + esc(cust.trn) + "</div>" : "",
  ].join("");

  const amountWithVat = Number(doc.subtotal) + Number(doc.tax_amount);
  let totalRows = '<div class="t-row"><span>Amount Before VAT</span><span>' + fmtMoney(doc.subtotal) + "</span></div>";
  totalRows += '<div class="t-row"><span>VAT Amount (' + vatRate + '%)</span><span>' + fmtMoney(doc.tax_amount) + "</span></div>";
  totalRows += '<div class="t-row"><span>Amount With VAT</span><span>' + fmtMoney(amountWithVat) + "</span></div>";
  if (Number(doc.discount)) totalRows += '<div class="t-row"><span>Discount</span><span>− ' + fmtMoney(doc.discount) + "</span></div>";
  totalRows += '<div class="t-row grand"><span>Grand Total</span><span>' + fmtMoney(doc.total) + "</span></div>";
  if (!isQuote) {
    totalRows += '<div class="t-row"><span>Amount Received</span><span>' + fmtMoney(doc.paid_amount) + "</span></div>";
    totalRows += '<div class="t-row due"><span>Amount Balance</span><span>' + fmtMoney(doc.balance) + "</span></div>";
  }

  let contact = "";
  if (comp?.phone) contact += '<div><strong>Call:</strong> ' + esc(comp.phone) + "</div>";
  if (comp?.email) contact += '<div><strong>Email:</strong> ' + esc(comp.email) + "</div>";
  if (comp?.address) contact += '<div><strong>Address:</strong> ' + esc(comp.address) + "</div>";

  const html = '<!DOCTYPE html><html><head><meta charset="utf-8"><title>' + esc(doc.number) + '</title><style>' +
    '*{margin:0;padding:0;box-sizing:border-box}' +
    'body{font-family:"Segoe UI",-apple-system,Arial,sans-serif;color:#1a202c;font-size:13px;background:#fff}' +
    '.page{max-width:820px;margin:0 auto}' +
    '.header{background:linear-gradient(135deg,#0c3740 0%,#0a4a54 45%,#037c84 100%);color:#fff;padding:24px 40px;position:relative;overflow:hidden}' +
    '.header-top{display:flex;align-items:center;gap:18px;position:relative;z-index:1}' +
    '.logo-box{background:#fff;border-radius:10px;padding:8px 12px;flex-shrink:0;box-shadow:0 2px 8px rgba(0,0,0,.15)}' +
    '.logo-box img{height:52px;width:auto;display:block}' +
    '.header:after{content:"";position:absolute;right:-60px;top:-60px;width:220px;height:220px;border-radius:50%;background:rgba(255,255,255,.06)}' +
    '.header:before{content:"";position:absolute;right:60px;top:40px;width:120px;height:120px;border-radius:50%;background:rgba(255,255,255,.05)}' +
    '.doc-type{font-size:32px;font-weight:800;letter-spacing:2px;line-height:1}' +
    '.brand{font-size:16px;font-weight:700;margin-top:6px}' +
    '.tagline{font-size:11px;opacity:.9;margin-top:2px;letter-spacing:1.5px;text-transform:uppercase}' +
    '.trn-chip{display:inline-block;margin-top:10px;font-size:10px;letter-spacing:.5px;background:rgba(255,255,255,.14);padding:4px 10px;border-radius:20px}' +
    '.body{padding:30px 40px}' +
    '.info-row{display:flex;justify-content:space-between;gap:30px}' +
    '.bill-to{flex:1}' +
    '.label{font-size:11px;text-transform:uppercase;letter-spacing:1.5px;color:#037c84;font-weight:800;margin-bottom:8px}' +
    '.bill-to .name{font-size:16px;font-weight:700}' +
    '.bill-to .dim{color:#64748b;margin-top:2px}' +
    '.meta{min-width:210px;text-align:right}' +
    '.m-row{display:flex;justify-content:space-between;gap:16px;padding:4px 0;border-bottom:1px dashed #e2e8f0}' +
    '.m-row .k{color:#64748b}' +
    '.m-row .v{font-weight:700}' +
    'table.items{width:100%;border-collapse:collapse;margin-top:28px}' +
    'table.items thead th{background:#0c3740;color:#fff;padding:11px 14px;font-size:11px;text-transform:uppercase;letter-spacing:.7px;text-align:left}' +
    'table.items thead th.num,table.items td.num{text-align:right}' +
    'table.items td{padding:11px 14px;border-bottom:1px solid #e2e8f0}' +
    'table.items tbody tr:nth-child(even){background:#f8fafc}' +
    '.sl{width:44px;font-weight:700;color:#037c84}' +
    '.qty-note{color:#64748b;font-size:11px}' +
    '.totals-wrap{display:flex;justify-content:flex-end;margin-top:20px}' +
    '.totals{width:280px;border:1px solid #e2e8f0;border-radius:10px;overflow:hidden}' +
    '.totals .t-head{background:#037c84;color:#fff;font-size:11px;font-weight:800;letter-spacing:1.5px;padding:9px 16px;text-transform:uppercase}' +
    '.t-row{display:flex;justify-content:space-between;padding:8px 16px;font-size:13px}' +
    '.t-row span:first-child{color:#475569}' +
    '.t-row.grand{border-top:2px solid #0c3740;font-size:16px;font-weight:800;color:#0c3740;margin-top:2px;padding:11px 16px}' +
    '.t-row.grand span:last-child{color:#037c84}' +
    '.t-row.due{background:#fef3c7;font-weight:700;color:#b45309}' +
    '.bottom{display:flex;justify-content:space-between;gap:30px;margin-top:32px}' +
    '.terms{flex:1.2;font-size:11.5px;color:#475569;line-height:1.7}' +
    '.contact{flex:1;font-size:11.5px;line-height:1.8;color:#475569}' +
    '.signature{margin-top:44px;width:230px}' +
    '.signature .line{border-top:1.5px solid #94a3b8;padding-top:6px;font-size:11px;color:#64748b;text-align:center;letter-spacing:.5px}' +
    '.footer{background:#0c3740;color:#d7f0f2;text-align:center;padding:16px 40px;font-size:11px;letter-spacing:.4px}' +
    '.footer strong{color:#fff}' +
    '@media print{.page{max-width:none}}' +
    '</style></head><body><div class="page">' +
    '<div class="header"><div class="header-top"><div class="logo-box"><img src="/logo.png"></div>' +
    '<div><div class="doc-type">' + docType + '</div>' +
    '<div class="brand">' + esc(brand) + '</div>' +
    (tagline ? '<div class="tagline">' + esc(tagline) + '</div>' : "") +
    (comp?.trn ? '<div class="trn-chip">TRN: ' + esc(comp.trn) + '</div>' : "") +
    '</div></div></div>' +
    '<div class="body">' +
    '<div class="info-row"><div class="bill-to"><div class="label">Invoice To</div>' + custLines + '</div>' +
    '<div class="meta">' + metaRows + '</div></div>' +
    '<table class="items"><thead><tr><th class="sl">SL</th><th>Item Description</th><th class="num">Quantity</th><th class="num">Price Before VAT</th><th class="num">' + vatRate + '% VAT</th><th class="num">Total Amount</th></tr></thead>' +
    '<tbody>' + items + '</tbody></table>' +
    '<div class="totals-wrap"><div class="totals"><div class="t-head">Payment Info</div>' + totalRows + '</div></div>' +
    '<div class="bottom"><div class="terms"><div class="label">Terms &amp; Conditions</div>' +
    (doc.terms ? esc(doc.terms) : "") + (doc.notes ? '<br>' + esc(doc.notes) : "") +
    '</div><div class="contact"><div class="label">Get in Touch</div>' + contact + '</div></div>' +
    '<div class="signature"><div class="line">Authorised Signature</div></div>' +
    '</div>' +
    '<div class="footer"><strong>' + esc(brand) + '</strong> · Thank you for your business!</div>' +
    '</div><script>window.onload=function(){window.print();}</script></body></html>';

  const w = window.open("", "_blank");
  w.document.write(html);
  w.document.close();
}

// ---------------- Utils ----------------
function today() { return new Date().toISOString().slice(0, 10); }
function addDays(n) { const d = new Date(); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10); }
function firstOfMonth() { const d = new Date(); return d.toISOString().slice(0, 8) + "01"; }
function firstOfYear() { return new Date().getFullYear() + "-01-01"; }

// expose globals used by inline handlers
Object.assign(window, {
  closeModal, openModal, saveInvoice, addLineItem, removeLine, lineProduct, lineEdit,
  saveQuote, addQuoteLine, removeQuoteLine, quoteProduct, quoteLineEdit,
  openCustomerModal, saveCustomer, deleteCustomer, openProductModal, saveProduct, deleteProduct,
  openStockModal, submitStockAdjust, openMovements, openPaymentModal, submitPayment,
  setInvoiceStatus, deletePayment, convertQuote, openTermsModal, saveTerms, openUserModal, saveUser, deleteUser,
  openExpenseModal, saveExpense, deleteExpense,
  saveSettings, showReport, loadSalesReport, loadPLReport, printPL, printDoc,
  loadStatement, printStatement,
});

boot();
