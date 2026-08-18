#!/usr/bin/env python3
"""
QuickInvoice — a lightweight online invoicing, quotations, and stock
management system (QuickBooks-style), built with the Python standard
library + SQLite so it runs anywhere with zero external dependencies.

Run:  python3 server.py  (serves on 0.0.0.0:8000)
"""
import json
import os
import re
import sqlite3
import hashlib
import secrets
import base64
import datetime as dt
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# On Render (and other hosts), DB_PATH can point at the mounted persistent disk
# so your data survives restarts. Locally it defaults to the app folder.
DB_PATH = os.environ.get("DB_PATH", os.path.join(BASE_DIR, "quickinvoice.db"))
STATIC_DIR = os.path.join(BASE_DIR, "static")
PORT = int(os.environ.get("PORT", 8000))

# --- Embedded static assets (single-file deployment) ---
EMBEDDED_INDEX = '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="UTF-8" />\n<meta name="viewport" content="width=device-width, initial-scale=1.0" />\n<title>QuickInvoice</title>\n<link rel="stylesheet" href="/style.css" />\n<link rel="icon" href="data:image/svg+xml,<svg xmlns=\'http://www.w3.org/2000/svg\' viewBox=\'0 0 100 100\'><rect width=\'100\' height=\'100\' rx=\'20\' fill=\'%234f46e5\'/><text x=\'50\' y=\'68\' font-size=\'52\' text-anchor=\'middle\' fill=\'white\' font-family=\'Arial\'>Q</text></svg>" />\n</head>\n<body>\n<div id="login-screen" class="login-screen hidden">\n  <div class="login-card">\n    <div class="login-brand">\n      <div class="logo-mark">Q</div>\n      <div>\n        <h1>QuickInvoice</h1>\n        <p class="muted">Invoicing · Quotations · Stock</p>\n      </div>\n    </div>\n    <form id="login-form" class="login-form">\n      <label>Email</label>\n      <input type="email" id="login-email" placeholder="you@company.com" autocomplete="username" required />\n      <label>Password</label>\n      <input type="password" id="login-password" placeholder="••••••••" autocomplete="current-password" required />\n      <div id="login-error" class="error-msg hidden"></div>\n      <button type="submit" class="btn btn-primary btn-block">Sign in</button>\n    </form>\n    <div class="login-hint muted">\n      <strong>Sign in</strong> with your email and password.<br/>\n      Contact your administrator if you\'ve forgotten your credentials.\n    </div>\n  </div>\n</div>\n\n<div id="app" class="app hidden">\n  <aside class="sidebar">\n    <div class="sidebar-brand">\n      <div class="logo-mark">Q</div>\n      <div class="brand-text">\n        <strong>QuickInvoice</strong>\n        <span class="muted small" id="sidebar-company"></span>\n      </div>\n    </div>\n    <nav class="nav">\n      <a href="#/dashboard" data-nav="dashboard" class="nav-link"><span class="ico">▦</span> Dashboard</a>\n      <a href="#/invoices" data-nav="invoices" class="nav-link"><span class="ico">▤</span> Invoices</a>\n      <a href="#/quotes" data-nav="quotes" class="nav-link"><span class="ico">▥</span> Quotations</a>\n      <a href="#/customers" data-nav="customers" class="nav-link"><span class="ico">◉</span> Customers</a>\n      <a href="#/products" data-nav="products" class="nav-link"><span class="ico">▣</span> Products &amp; Stock</a>\n      <a href="#/payments" data-nav="payments" class="nav-link"><span class="ico">◈</span> Payments</a>\n      <a href="#/expenses" data-nav="expenses" class="nav-link"><span class="ico">◈</span> Expenses</a>\n      <a href="#/statement" data-nav="statement" class="nav-link"><span class="ico">▤</span> Statements</a>\n      <a href="#/reports" data-nav="reports" class="nav-link"><span class="ico">▦</span> Reports</a>\n      <a href="#/settings" data-nav="settings" class="nav-link admin-only"><span class="ico">⚙</span> Settings</a>\n      <a href="#/users" data-nav="users" class="nav-link admin-only"><span class="ico">◈</span> Users</a>\n    </nav>\n    <div class="sidebar-footer">\n      <div class="user-chip">\n        <div class="avatar" id="user-avatar">A</div>\n        <div class="user-meta">\n          <strong id="user-name">…</strong>\n          <span class="muted small" id="user-role">…</span>\n        </div>\n        <button class="icon-btn" id="logout-btn" title="Sign out">⏻</button>\n      </div>\n    </div>\n  </aside>\n\n  <main class="main">\n    <div id="toast" class="toast hidden"></div>\n    <div id="view"></div>\n  </main>\n</div>\n\n<div id="modal-root"></div>\n\n<script src="/app.js"></script>\n</body>\n</html>\n'

EMBEDDED_STYLE = ':root {\n  --primary: #4f46e5;\n  --primary-dark: #4338ca;\n  --primary-soft: #eef2ff;\n  --sidebar-bg: #0f172a;\n  --sidebar-fg: #cbd5e1;\n  --bg: #f1f5f9;\n  --card: #ffffff;\n  --border: #e2e8f0;\n  --text: #0f172a;\n  --muted: #64748b;\n  --green: #16a34a;\n  --green-soft: #dcfce7;\n  --red: #dc2626;\n  --red-soft: #fee2e2;\n  --amber: #d97706;\n  --amber-soft: #fef3c7;\n  --blue: #2563eb;\n  --blue-soft: #dbeafe;\n  --radius: 12px;\n  --shadow: 0 1px 3px rgba(15,23,42,.08), 0 1px 2px rgba(15,23,42,.04);\n  --shadow-lg: 0 10px 30px rgba(15,23,42,.12);\n}\n\n* { box-sizing: border-box; margin: 0; padding: 0; }\n\nbody {\n  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;\n  background: var(--bg);\n  color: var(--text);\n  font-size: 14px;\n  line-height: 1.5;\n}\n\n.hidden { display: none !important; }\n.muted { color: var(--muted); }\n.small { font-size: 12px; }\n.mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }\n\n/* ---------- Login ---------- */\n.login-screen {\n  min-height: 100vh;\n  display: flex;\n  align-items: center;\n  justify-content: center;\n  background: linear-gradient(135deg, #1e1b4b 0%, #312e81 40%, #4f46e5 100%);\n  padding: 20px;\n}\n.login-card {\n  background: #fff;\n  border-radius: 18px;\n  padding: 36px;\n  width: 100%;\n  max-width: 400px;\n  box-shadow: 0 25px 60px rgba(0,0,0,.35);\n}\n.login-brand { display: flex; align-items: center; gap: 14px; margin-bottom: 26px; }\n.login-brand h1 { font-size: 22px; }\n.logo-mark {\n  width: 46px; height: 46px; border-radius: 12px;\n  background: var(--primary); color: #fff;\n  display: flex; align-items: center; justify-content: center;\n  font-size: 24px; font-weight: 700; flex-shrink: 0;\n}\n.login-form { display: flex; flex-direction: column; gap: 8px; }\n.login-form label { font-weight: 600; font-size: 13px; margin-top: 6px; }\n.login-hint { margin-top: 20px; padding: 12px; background: var(--primary-soft); border-radius: 10px; font-size: 12px; line-height: 1.6; }\n\n/* ---------- Layout ---------- */\n.app { display: flex; min-height: 100vh; }\n.sidebar {\n  width: 240px; background: var(--sidebar-bg); color: var(--sidebar-fg);\n  display: flex; flex-direction: column; position: sticky; top: 0; height: 100vh;\n  flex-shrink: 0;\n}\n.sidebar-brand { display: flex; align-items: center; gap: 12px; padding: 18px 18px 16px; border-bottom: 1px solid rgba(255,255,255,.08); }\n.sidebar-brand .logo-mark { width: 38px; height: 38px; font-size: 20px; }\n.brand-text { display: flex; flex-direction: column; }\n.brand-text strong { color: #fff; font-size: 15px; }\n.nav { flex: 1; padding: 14px 10px; display: flex; flex-direction: column; gap: 2px; overflow-y: auto; }\n.nav-link {\n  display: flex; align-items: center; gap: 11px; padding: 10px 12px;\n  border-radius: 9px; color: var(--sidebar-fg); text-decoration: none;\n  font-weight: 500; transition: background .15s;\n}\n.nav-link:hover { background: rgba(255,255,255,.06); color: #fff; }\n.nav-link.active { background: var(--primary); color: #fff; }\n.nav-link .ico { width: 20px; text-align: center; font-size: 15px; }\n.sidebar-footer { padding: 12px; border-top: 1px solid rgba(255,255,255,.08); }\n.user-chip { display: flex; align-items: center; gap: 10px; }\n.avatar {\n  width: 34px; height: 34px; border-radius: 50%; background: var(--primary);\n  color: #fff; display: flex; align-items: center; justify-content: center;\n  font-weight: 700; flex-shrink: 0;\n}\n.user-meta { flex: 1; display: flex; flex-direction: column; min-width: 0; }\n.user-meta strong { color: #fff; font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }\n.icon-btn {\n  background: none; border: none; color: var(--sidebar-fg); cursor: pointer;\n  font-size: 16px; padding: 6px; border-radius: 8px;\n}\n.icon-btn:hover { background: rgba(255,255,255,.08); color: #fff; }\n\n.main { flex: 1; padding: 26px 30px; max-width: 1200px; min-width: 0; }\n\n/* ---------- Headings ---------- */\n.page-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; gap: 16px; flex-wrap: wrap; }\n.page-head h2 { font-size: 22px; }\n.page-head .sub { color: var(--muted); font-size: 13px; }\n\n/* ---------- Cards & grid ---------- */\n.card { background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow); padding: 20px; }\n.grid { display: grid; gap: 16px; }\n.grid-4 { grid-template-columns: repeat(4, 1fr); }\n.grid-3 { grid-template-columns: repeat(3, 1fr); }\n.grid-2 { grid-template-columns: repeat(2, 1fr); }\n@media (max-width: 900px) { .grid-4, .grid-3, .grid-2 { grid-template-columns: 1fr 1fr; } }\n@media (max-width: 600px) { .grid-4, .grid-3, .grid-2 { grid-template-columns: 1fr; } }\n\n.stat { display: flex; flex-direction: column; gap: 4px; }\n.stat .label { color: var(--muted); font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: .03em; }\n.stat .value { font-size: 24px; font-weight: 700; }\n.stat .delta { font-size: 12px; }\n\n/* ---------- Buttons ---------- */\n.btn {\n  display: inline-flex; align-items: center; gap: 7px; padding: 9px 15px;\n  border-radius: 9px; border: 1px solid var(--border); background: #fff;\n  color: var(--text); font-weight: 600; font-size: 13px; cursor: pointer;\n  transition: all .15s; text-decoration: none; white-space: nowrap;\n}\n.btn:hover { background: #f8fafc; border-color: #cbd5e1; }\n.btn-primary { background: var(--primary); border-color: var(--primary); color: #fff; }\n.btn-primary:hover { background: var(--primary-dark); border-color: var(--primary-dark); }\n.btn-danger { background: #fff; color: var(--red); border-color: #fecaca; }\n.btn-danger:hover { background: var(--red-soft); }\n.btn-sm { padding: 6px 11px; font-size: 12px; border-radius: 7px; }\n.btn-block { width: 100%; justify-content: center; }\n.btn-ghost { background: transparent; border-color: transparent; color: var(--muted); }\n.btn-ghost:hover { background: #f1f5f9; color: var(--text); }\n.btn:disabled { opacity: .5; cursor: not-allowed; }\n\n/* ---------- Table ---------- */\n.table-wrap { overflow-x: auto; }\ntable { width: 100%; border-collapse: collapse; }\nth {\n  text-align: left; padding: 10px 12px; font-size: 11px; text-transform: uppercase;\n  letter-spacing: .04em; color: var(--muted); border-bottom: 1px solid var(--border);\n  font-weight: 700; white-space: nowrap;\n}\ntd { padding: 12px; border-bottom: 1px solid var(--border); vertical-align: middle; }\ntr:last-child td { border-bottom: none; }\ntbody tr:hover { background: #f8fafc; }\ntd .row-actions { display: flex; gap: 4px; opacity: 0; transition: opacity .12s; }\ntr:hover td .row-actions { opacity: 1; }\n.num { text-align: right; font-variant-numeric: tabular-nums; }\n.sl-num { color: var(--primary); font-weight: 700; width: 44px; }\n\n/* ---------- Badges ---------- */\n.badge {\n  display: inline-flex; align-items: center; gap: 5px; padding: 3px 9px;\n  border-radius: 999px; font-size: 11px; font-weight: 700; white-space: nowrap;\n}\n.badge.paid { background: var(--green-soft); color: var(--green); }\n.badge.sent { background: var(--blue-soft); color: var(--blue); }\n.badge.partial { background: var(--amber-soft); color: var(--amber); }\n.badge.overdue, .badge.rejected { background: var(--red-soft); color: var(--red); }\n.badge.draft { background: #f1f5f9; color: var(--muted); }\n.badge.accepted, .badge.converted { background: var(--green-soft); color: var(--green); }\n.badge.expired, .badge.cancelled { background: #f1f5f9; color: var(--muted); }\n.badge.low { background: var(--amber-soft); color: var(--amber); }\n.badge.ok { background: var(--green-soft); color: var(--green); }\n.badge.admin { background: var(--primary-soft); color: var(--primary); }\n\n/* ---------- Forms ---------- */\n.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px 18px; }\n.form-grid .full { grid-column: 1 / -1; }\n@media (max-width: 640px) { .form-grid { grid-template-columns: 1fr; } }\n.field { display: flex; flex-direction: column; gap: 5px; }\n.field label { font-size: 12px; font-weight: 600; color: var(--muted); }\n.field input, .field select, .field textarea {\n  padding: 9px 12px; border: 1px solid var(--border); border-radius: 8px;\n  font-size: 14px; font-family: inherit; background: #fff; color: var(--text);\n  width: 100%;\n}\n.field input:focus, .field select:focus, .field textarea:focus {\n  outline: none; border-color: var(--primary); box-shadow: 0 0 0 3px var(--primary-soft);\n}\n.field textarea { resize: vertical; min-height: 70px; }\n.form-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 18px; }\n\n/* ---------- Line items editor ---------- */\n.line-items { margin-top: 4px; }\n.line-item {\n  display: grid; grid-template-columns: 1.6fr 0.8fr 1fr 1fr 36px; gap: 10px;\n  align-items: center; padding: 8px 0;\n}\n.line-item .product-cell input, .line-item .product-cell select { width: 100%; padding: 8px 10px; border: 1px solid var(--border); border-radius: 8px; }\n@media (max-width: 700px) { .line-item { grid-template-columns: 1fr 1fr; } .line-item .del { grid-column: 1/-1; } }\n\n.totals-box { margin-top: 16px; display: flex; justify-content: flex-end; }\n.totals { width: 280px; font-size: 14px; }\n.totals .t-row { display: flex; justify-content: space-between; padding: 6px 0; }\n.totals .t-row.grand { border-top: 2px solid var(--border); margin-top: 4px; padding-top: 10px; font-size: 17px; font-weight: 700; }\n\n/* ---------- Toast ---------- */\n.toast {\n  position: fixed; top: 20px; right: 20px; z-index: 1000;\n  background: var(--text); color: #fff; padding: 12px 18px; border-radius: 10px;\n  box-shadow: var(--shadow-lg); font-weight: 500; max-width: 340px;\n}\n.toast.error { background: var(--red); }\n.toast.success { background: var(--green); }\n\n/* ---------- Modal ---------- */\n.modal-backdrop {\n  position: fixed; inset: 0; background: rgba(15,23,42,.5); z-index: 500;\n  display: flex; align-items: center; justify-content: center; padding: 20px;\n  animation: fadeIn .15s ease;\n}\n.modal {\n  background: #fff; border-radius: 16px; box-shadow: var(--shadow-lg);\n  width: 100%; max-width: 520px; max-height: 90vh; overflow-y: auto;\n  animation: slideUp .18s ease;\n}\n.modal-head { display: flex; align-items: center; justify-content: space-between; padding: 18px 22px; border-bottom: 1px solid var(--border); }\n.modal-head h3 { font-size: 17px; }\n.modal-body { padding: 22px; }\n@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }\n@keyframes slideUp { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: translateY(0); } }\n\n/* ---------- Misc ---------- */\n.empty {\n  text-align: center; padding: 50px 20px; color: var(--muted);\n}\n.empty .big { font-size: 40px; margin-bottom: 10px; }\n.searchbar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }\n.searchbar input { padding: 9px 12px; border: 1px solid var(--border); border-radius: 9px; min-width: 220px; }\n.toolbar { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }\n.tabs { display: flex; gap: 4px; background: #e2e8f0; padding: 4px; border-radius: 10px; width: fit-content; }\n.tab { padding: 7px 14px; border-radius: 8px; border: none; background: none; cursor: pointer; font-weight: 600; font-size: 13px; color: var(--muted); }\n.tab.active { background: #fff; color: var(--text); box-shadow: var(--shadow); }\n\n.chart-bars { display: flex; align-items: flex-end; gap: 8px; height: 160px; padding-top: 10px; }\n.chart-bar { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 6px; min-width: 0; }\n.chart-bar .bar { width: 100%; max-width: 44px; background: var(--primary); border-radius: 6px 6px 0 0; min-height: 4px; transition: height .4s; }\n.chart-bar .bar-val { font-size: 10px; color: var(--muted); }\n.chart-bar .bar-label { font-size: 11px; color: var(--muted); font-weight: 600; }\n\n.clickable { cursor: pointer; }\n.link { color: var(--primary); cursor: pointer; font-weight: 600; }\n.link:hover { text-decoration: underline; }\n\n/* ---------- Print ---------- */\n@media print {\n  .sidebar, .page-head, .toolbar, .no-print { display: none !important; }\n  .main { padding: 0; max-width: none; }\n  body { background: #fff; }\n  .card { border: none; box-shadow: none; padding: 0; }\n}\n'

EMBEDDED_APPJS = '/* QuickInvoice — frontend SPA (vanilla JS, no dependencies) */\n\n// ---------------- State & helpers ----------------\n// Safe storage wrapper — sandboxed iframes & private-mode browsers can throw\n// on localStorage access, so we degrade gracefully to in-memory storage.\nconst store = {\n  _m: {},\n  get(k) { try { return window.localStorage.getItem(k); } catch (e) { return this._m[k] ?? null; } },\n  set(k, v) { try { window.localStorage.setItem(k, v); } catch (e) { this._m[k] = v; } },\n  remove(k) { try { window.localStorage.removeItem(k); } catch (e) { delete this._m[k]; } },\n};\n\nconst state = {\n  token: store.get("qi_token") || null,\n  user: null,\n  company: null,\n  customers: [],\n  products: [],\n  invoices: [],\n  quotes: [],\n};\n\nconst $ = (sel, root = document) => root.querySelector(sel);\nconst $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));\nconst esc = (s) => String(s ?? "").replace(/[&<>"\']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", \'"\': "&quot;", "\'": "&#39;" }[c]));\n\nfunction fmtMoney(n, cur) {\n  const c = cur || state.company?.currency || "AED";\n  return new Intl.NumberFormat("en-AE", { style: "currency", currency: c, minimumFractionDigits: 2 }).format(Number(n || 0));\n}\nfunction fmtNum(n) { return new Intl.NumberFormat("en-AE").format(Number(n || 0)); }\n\nfunction toast(msg, type = "success") {\n  const el = $("#toast");\n  el.textContent = msg;\n  el.className = "toast " + type;\n  clearTimeout(el._t);\n  el._t = setTimeout(() => el.classList.add("hidden"), 3200);\n}\n\nasync function api(path, opts = {}) {\n  const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };\n  if (state.token) headers["Authorization"] = "Bearer " + state.token;\n  let res;\n  try {\n    res = await fetch("/api" + path, { ...opts, headers });\n  } catch (e) {\n    // Network failure — server unreachable (not an auth problem)\n    throw new Error("Cannot reach the server. Please refresh the page and try again.");\n  }\n  const data = await res.json().catch(() => ({}));\n  // Only treat 401 as "session expired" for authenticated requests.\n  // A failed LOGIN (also 401) should show "invalid email or password".\n  if (res.status === 401 && path !== "/login") {\n    logout();\n    throw new Error("Session expired — please sign in again.");\n  }\n  if (!res.ok) throw new Error(data.error || "Request failed");\n  return data;\n}\n\n// ---------------- Auth ----------------\nfunction showLogin() {\n  $("#app").classList.add("hidden");\n  $("#login-screen").classList.remove("hidden");\n}\nfunction showApp() {\n  $("#login-screen").classList.add("hidden");\n  $("#app").classList.remove("hidden");\n}\nfunction logout() {\n  state.token = null; state.user = null;\n  store.remove("qi_token");\n  api("/logout", { method: "POST" }).catch(() => {});\n  showLogin();\n}\n\n$("#login-form").addEventListener("submit", async (e) => {\n  e.preventDefault();\n  const email = $("#login-email").value.trim();\n  const password = $("#login-password").value;\n  $("#login-error").classList.add("hidden");\n  try {\n    const r = await api("/login", { method: "POST", body: JSON.stringify({ email, password }) });\n    state.token = r.token; state.user = r.user;\n    store.set("qi_token", r.token);\n    boot();\n  } catch (err) {\n    const el = $("#login-error");\n    el.textContent = err.message; el.classList.remove("hidden");\n  }\n});\n$("#logout-btn").addEventListener("click", logout);\n\n// ---------------- Router ----------------\nconst routes = {\n  dashboard: renderDashboard,\n  invoices: renderInvoices,\n  "invoice/new": renderInvoiceForm,\n  "invoice/edit": renderInvoiceForm,\n  "invoice/view": renderInvoiceView,\n  quotes: renderQuotes,\n  "quote/new": renderQuoteForm,\n  "quote/edit": renderQuoteForm,\n  "quote/view": renderQuoteView,\n  customers: renderCustomers,\n  products: renderProducts,\n  payments: renderPayments,\n  expenses: renderExpenses,\n  statement: renderStatement,\n  reports: renderReports,\n  settings: renderSettings,\n  users: renderUsers,\n};\n\nfunction currentRoute() {\n  const h = location.hash.replace(/^#\\/?/, "") || "dashboard";\n  return h.split("/");\n}\n\nfunction navigate() {\n  const parts = currentRoute();\n  const key = parts[0];\n  const fn = routes[key] || routes[parts.slice(0, 2).join("/")] || renderDashboard;\n  // highlight nav\n  $$(".nav-link").forEach((a) => a.classList.toggle("active", a.dataset.nav === key));\n  // admin-only visibility\n  const isAdmin = state.user?.role === "admin";\n  $$(".admin-only").forEach((a) => a.classList.toggle("hidden", !isAdmin));\n  try {\n    const result = fn(parts.slice(1));\n    // If the route returns a promise, surface any rejection clearly.\n    if (result && typeof result.catch === "function") {\n      result.catch((e) => showFatal(e));\n    }\n  } catch (e) {\n    showFatal(e);\n  }\n}\n\nfunction showFatal(e) {\n  const msg = (e && (e.message || e)) || "Unknown error";\n  const stack = (e && e.stack) || "";\n  console.error("Route error:", e);\n  const el = $("#view");\n  if (el) {\n    el.innerHTML = `<div class="card" style="margin:20px"><div class="empty">\n      <div class="big">⚠️</div><h3>Something went wrong</h3>\n      <p class="muted" style="word-break:break-word;max-width:640px;margin:0 auto">${esc(String(msg))}</p>\n      <pre class="muted small" style="word-break:break-word;max-width:640px;margin:12px auto 0;text-align:left;white-space:pre-wrap;background:#f8fafc;padding:12px;border-radius:8px">${esc(stack.split("\\n").slice(0, 4).join("\\n"))}</pre>\n      <button class="btn btn-primary" style="margin-top:14px" onclick="location.reload()">Reload</button>\n    </div></div>`;\n  }\n}\n\nwindow.addEventListener("hashchange", navigate);\n\n// Surface any uncaught error instead of silently blanking the app\nwindow.addEventListener("error", (e) => showFatal(e));\nwindow.addEventListener("unhandledrejection", (e) => showFatal(e.reason));\n\n// ---------------- Boot ----------------\nasync function boot() {\n  if (!state.token) { showLogin(); return; }\n  showApp();\n  try {\n    const me = await api("/me");\n    state.user = me.user;\n    $("#user-name").textContent = me.user.name;\n    $("#user-role").textContent = me.user.role === "admin" ? "Administrator" : "Staff";\n    $("#user-avatar").textContent = (me.user.name[0] || "?").toUpperCase();\n    try {\n      const c = await api("/settings");\n      state.company = c.company;\n      $("#sidebar-company").textContent = c.company.name || "QuickInvoice";\n    } catch (e) {\n      console.warn("settings load failed", e);\n    }\n    try {\n      navigate();\n    } catch (e) {\n      console.error("navigate failed", e);\n      $("#view").innerHTML = `<div class="card" style="margin:20px"><div class="empty"><div class="big">⚠️</div><h3>Could not load the dashboard</h3><p class="muted">${esc(e.message || "")}</p><button class="btn btn-primary" onclick="location.reload()">Reload</button></div></div>`;\n    }\n  } catch (e) {\n    console.error("boot failed", e);\n    // show a visible error rather than silently logging out\n    $("#view").innerHTML = `<div class="card" style="margin:20px"><div class="empty"><div class="big">⚠️</div><h3>Sign-in error</h3><p class="muted">${esc(e.message || "Could not verify your session")}</p><button class="btn btn-primary" onclick="location.reload()">Try again</button></div></div>`;\n  }\n}\n\n// ---------------- Modal ----------------\nfunction openModal(title, bodyHtml, actions = "") {\n  const root = $("#modal-root");\n  root.innerHTML = `\n    <div class="modal-backdrop">\n      <div class="modal">\n        <div class="modal-head"><h3>${title}</h3>\n          <button class="icon-btn" onclick="closeModal()" style="color:#64748b">✕</button></div>\n        <div class="modal-body">${bodyHtml}</div>\n        ${actions ? `<div class="modal-body" style="padding-top:0">${actions}</div>` : ""}\n      </div>\n    </div>`;\n  root.querySelector(".modal-backdrop").addEventListener("click", (e) => { if (e.target === e.currentTarget) closeModal(); });\n}\nfunction closeModal() { $("#modal-root").innerHTML = ""; }\n\n// ================= DASHBOARD =================\nasync function renderDashboard() {\n  const d = await api("/reports/dashboard");\n  const view = $("#view");\n  const overdueBadge = d.overdue_invoices > 0 ? `<div class="card" style="border-left:4px solid var(--red)"><div class="stat"><span class="label">Overdue invoices</span><span class="value" style="color:var(--red)">${d.overdue_invoices}</span><span class="delta muted">Action needed</span></div></div>` : "";\n  const lowStockBadge = d.low_stock > 0 ? `<div class="card" style="border-left:4px solid var(--amber)"><div class="stat"><span class="label">Low stock items</span><span class="value" style="color:var(--amber)">${d.low_stock}</span><span class="delta muted">Reorder soon</span></div></div>` : "";\n\n  const maxRev = Math.max(...d.monthly.map((m) => m.revenue), 1);\n  const bars = d.monthly.map((m) => {\n    const h = Math.max((m.revenue / maxRev) * 100, 2);\n    return `<div class="chart-bar"><span class="bar-val">${m.revenue ? (m.revenue / 1000).toFixed(1) + "k" : ""}</span><div class="bar" style="height:${h}px;height:${h}%"></div><span class="bar-label">${monthLabel(m.month)}</span></div>`;\n  }).join("");\n\n  const topCust = d.top_customers.length ? d.top_customers.map((c, i) => `\n    <tr><td>${i + 1}</td><td>${esc(c.name)}</td><td class="num">${fmtMoney(c.total)}</td></tr>`).join("")\n    : `<tr><td colspan="3" class="muted">No sales yet</td></tr>`;\n\n  const recent = d.recent.length ? d.recent.map((r) => `\n    <tr class="clickable" onclick="location.hash=\'#/invoice/view/${r.id}\'">\n      <td class="mono">${esc(r.number)}</td><td>${esc(r.customer)}</td>\n      <td class="num">${fmtMoney(r.total)}</td>\n      <td><span class="badge ${r.status}">${r.status}</span></td>\n      <td class="muted small">${esc(r.created_at.slice(0, 10))}</td>\n    </tr>`).join("") : `<tr><td colspan="5" class="muted">No invoices yet</td></tr>`;\n\n  view.innerHTML = `\n    <div class="page-head">\n      <div><h2>Dashboard</h2><div class="sub">Welcome back, ${esc(state.user.name)} — here\'s your business at a glance.</div></div>\n      <div class="no-print" style="display:flex;gap:10px">\n        <a class="btn" href="#/invoice/new">+ New Invoice</a>\n        <a class="btn btn-primary" href="#/quote/new">+ New Quotation</a>\n      </div>\n    </div>\n    <div class="grid grid-4" style="margin-bottom:16px">\n      <div class="card"><div class="stat"><span class="label">Total invoiced</span><span class="value">${fmtMoney(d.total_invoiced)}</span><span class="delta muted">All time</span></div></div>\n      <div class="card"><div class="stat"><span class="label">Collected</span><span class="value" style="color:var(--green)">${fmtMoney(d.total_paid)}</span><span class="delta muted">Payments received</span></div></div>\n      <div class="card"><div class="stat"><span class="label">Outstanding</span><span class="value" style="color:${d.outstanding > 0 ? "var(--amber)" : "var(--text)"}">${fmtMoney(d.outstanding)}</span><span class="delta muted">To collect</span></div></div>\n      <div class="card"><div class="stat"><span class="label">Sales this month</span><span class="value">${fmtMoney(d.sales_this_month)}</span><span class="delta muted">${d.open_invoices} open invoices</span></div></div>\n    </div>\n    <div class="grid grid-2" style="margin-bottom:16px">${overdueBadge}${lowStockBadge || `<div class="card"><div class="stat"><span class="label">Low stock items</span><span class="value">0</span><span class="delta muted">All good</span></div></div>`}</div>\n    <div class="grid grid-2" style="margin-bottom:16px">\n      <div class="card"><h3 style="margin-bottom:14px">Revenue — last 6 months</h3><div class="chart-bars">${bars}</div></div>\n      <div class="card"><h3 style="margin-bottom:14px">Top customers</h3><table><thead><tr><th>#</th><th>Customer</th><th class="num">Revenue</th></tr></thead><tbody>${topCust}</tbody></table></div>\n    </div>\n    <div class="card"><h3 style="margin-bottom:14px">Recent invoices</h3><table><thead><tr><th>Number</th><th>Customer</th><th class="num">Total</th><th>Status</th><th>Date</th></tr></thead><tbody>${recent}</tbody></table></div>`;\n}\nfunction monthLabel(m) {\n  const [y, mo] = m.split("-");\n  return new Date(y, mo - 1, 1).toLocaleString("en", { month: "short" });\n}\n\n// ================= INVOICES =================\nasync function renderInvoices() {\n  const inv = (await api("/invoices")).invoices;\n  state.invoices = inv;\n  const view = $("#view");\n  const statusFilter = store.get("qi_inv_filter") || "all";\n\n  const render = () => {\n    const f = $("#inv-filter").value;\n    store.set("qi_inv_filter", f);\n    const q = ($("#inv-search").value || "").toLowerCase();\n    const list = inv.filter((i) => {\n      if (f !== "all" && i.status !== f) return false;\n      if (q && !(i.number + " " + (i.customer?.name || "")).toLowerCase().includes(q)) return false;\n      return true;\n    });\n    const rows = list.length ? list.map((i) => `\n      <tr class="clickable" onclick="location.hash=\'#/invoice/view/${i.id}\'">\n        <td class="mono">${esc(i.number)}</td>\n        <td>${esc(i.customer?.name || "—")}</td>\n        <td class="small muted">${esc(i.issue_date)}</td>\n        <td class="small muted">${esc(i.due_date)}</td>\n        <td class="num">${fmtMoney(i.total)}</td>\n        <td class="num small">${i.paid_amount > 0 ? fmtMoney(i.paid_amount) : "—"}</td>\n        <td><span class="badge ${i.status}">${i.status}</span></td>\n      </tr>`).join("") : `<tr><td colspan="7" class="empty"><div class="big">🗂️</div><h3>No invoices found</h3><p class="muted">Create your first invoice to get started.</p><a class="btn btn-primary" href="#/invoice/new" style="margin-top:12px">+ Create Invoice</a></td></tr>`;\n    $("#inv-rows").innerHTML = rows;\n  };\n\n  view.innerHTML = `\n    <div class="page-head">\n      <div><h2>Invoices</h2><div class="sub">${inv.length} invoices</div></div>\n      <a class="btn btn-primary" href="#/invoice/new">+ New Invoice</a>\n    </div>\n    <div class="card">\n      <div class="toolbar">\n        <div class="searchbar">\n          <input id="inv-search" placeholder="Search number or customer…" oninput="window._invRender && window._invRender()" />\n          <select id="inv-filter" onchange="window._invRender && window._invRender()">\n            ${["all","draft","sent","partial","paid","overdue","cancelled"].map((s) => `<option value="${s}" ${s === statusFilter ? "selected" : ""}>${s === "all" ? "All statuses" : s[0].toUpperCase() + s.slice(1)}</option>`).join("")}\n          </select>\n        </div>\n      </div>\n      <div class="table-wrap"><table><thead><tr><th>Number</th><th>Customer</th><th>Issued</th><th>Due</th><th class="num">Total</th><th class="num">Paid</th><th>Status</th></tr></thead><tbody id="inv-rows"></tbody></table></div>\n    </div>`;\n  window._invRender = render;\n  render();\n}\n\n// ---- Invoice form ----\nasync function renderInvoiceForm(args) {\n  const id = args[0];\n  let inv = null;\n  if (id) {\n    inv = (await api("/invoices/" + id)).invoice;\n  }\n  const customers = (await api("/customers")).customers;\n  const products = (await api("/products")).products;\n  state.customers = customers; state.products = products;\n\n  const items = inv ? inv.items.map((it) => ({ product_id: it.product_id, description: it.description, qty: it.qty, unit_price: it.unit_price }))\n    : [{ product_id: null, description: "", qty: 1, unit_price: 0 }];\n\n  const view = $("#view");\n  view.innerHTML = `\n    <div class="page-head">\n      <div><h2>${inv ? "Edit Invoice " + esc(inv.number) : "New Invoice"}</h2><div class="sub">${inv ? "Update the invoice details below" : "Create a new invoice"}</div></div>\n      <div style="display:flex;gap:10px">\n        <a class="btn" href="#/invoices">Cancel</a>\n        <button class="btn btn-primary" onclick="saveInvoice(${id || "null"}, \'draft\')">Save Draft</button>\n        <button class="btn btn-primary" style="background:var(--green);border-color:var(--green)" onclick="saveInvoice(${id || "null"}, \'sent\')">Save & Send</button>\n      </div>\n    </div>\n    <div class="card">\n      <div class="form-grid">\n        <div class="field full"><label>Customer *</label>\n          <select id="f-customer">${customers.map((c) => `<option value="${c.id}" ${inv && inv.customer_id == c.id ? "selected" : ""}>${esc(c.name)}${c.company_name ? " — " + esc(c.company_name) : ""}</option>`).join("")}</select>\n        </div>\n        <div class="field"><label>Issue date</label><input type="date" id="f-issue" value="${inv ? inv.issue_date : today()}"></div>\n        <div class="field"><label>Due date</label><input type="date" id="f-due" value="${inv ? inv.due_date : addDays(14)}"></div>\n        <div class="field"><label>Discount (${esc(state.company?.currency || "AED")})</label><input type="number" id="f-discount" step="0.01" min="0" value="${inv ? inv.discount : 0}"></div>\n        <div class="field"><label>Status</label><select id="f-status">\n          ${["draft","sent"].map((s) => `<option value="${s}" ${inv && inv.status === s ? "selected" : ""}>${s[0].toUpperCase() + s.slice(1)}</option>`).join("")}\n        </select></div>\n        <div class="field full"><label>Notes</label><textarea id="f-notes">${esc(inv?.notes || state.company?.invoice_notes || "")}</textarea></div>\n        <div class="field full"><label>Terms</label><textarea id="f-terms">${esc(inv?.terms || state.company?.payment_terms || "")}</textarea></div>\n      </div>\n    </div>\n    <div class="card" style="margin-top:16px">\n      <div class="toolbar" style="margin-bottom:6px"><h3>Line items</h3><button class="btn btn-sm" onclick="addLineItem()">+ Add item</button></div>\n      <div id="line-items">${items.map((it, idx) => lineItemHtml(it, idx)).join("")}</div>\n      <div class="totals-box"><div class="totals" id="totals"></div></div>\n    </div>`;\n  window._items = items;\n  attachLineEvents();\n  recomputeTotals();\n}\n\nfunction lineItemHtml(it, idx) {\n  const prodOpts = state.products.map((p) => `<option value="${p.id}" data-price="${p.sell_price}">${esc(p.name)}</option>`).join("");\n  return `<div class="line-item" data-idx="${idx}">\n    <div class="product-cell">\n      <select onchange="lineProduct(${idx}, this)">\n        <option value="">— Custom item —</option>${prodOpts}\n      </select>\n    </div>\n    <input type="text" class="li-desc" placeholder="Description" value="${esc(it.description)}" oninput="lineEdit(${idx})">\n    <input type="number" class="li-qty" placeholder="Qty" step="any" min="0" value="${it.qty}" oninput="lineEdit(${idx})">\n    <input type="number" class="li-price" placeholder="Unit price" step="0.01" min="0" value="${it.unit_price}" oninput="lineEdit(${idx})">\n    <button class="icon-btn del" style="color:var(--red)" onclick="removeLine(${idx})">✕</button>\n  </div>`;\n}\n\nfunction addLineItem() {\n  window._items.push({ product_id: null, description: "", qty: 1, unit_price: 0 });\n  $("#line-items").insertAdjacentHTML("beforeend", lineItemHtml(window._items[window._items.length - 1], window._items.length - 1));\n  recomputeTotals();\n}\nfunction removeLine(idx) {\n  if (window._items.length <= 1) { toast("At least one line item is required", "error"); return; }\n  window._items.splice(idx, 1);\n  $$("#line-items .line-item").forEach((el, i) => el.dataset.idx = i);\n  $("#line-items").innerHTML = window._items.map((it, i) => lineItemHtml(it, i)).join("");\n  attachLineEvents();\n  recomputeTotals();\n}\nfunction lineProduct(idx, sel) {\n  const it = window._items[idx];\n  if (sel.value) {\n    const opt = sel.selectedOptions[0];\n    it.product_id = Number(sel.value);\n    it.description = sel.options[sel.selectedIndex].text;\n    it.unit_price = Number(opt.dataset.price || 0);\n  } else {\n    it.product_id = null;\n    it.description = "";\n  }\n  const el = $$("#line-items .line-item")[idx];\n  el.querySelector(".li-desc").value = it.description;\n  el.querySelector(".li-price").value = it.unit_price;\n  recomputeTotals();\n}\nfunction lineEdit(idx) {\n  const el = $$("#line-items .line-item")[idx];\n  window._items[idx].description = el.querySelector(".li-desc").value;\n  window._items[idx].qty = Number(el.querySelector(".li-qty").value || 0);\n  window._items[idx].unit_price = Number(el.querySelector(".li-price").value || 0);\n  recomputeTotals();\n}\nfunction attachLineEvents() {}\n\nfunction recomputeTotals() {\n  const rate = state.company?.vat_rate ?? 5;\n  let subtotal = 0, tax = 0;\n  for (const it of window._items) {\n    const lt = (it.qty || 0) * (it.unit_price || 0);\n    subtotal += lt;\n    const prod = state.products.find((p) => p.id === it.product_id);\n    const taxable = prod ? prod.is_taxable : true;\n    if (taxable) tax += lt * rate / 100;\n  }\n  const disc = Number($("#f-discount").value || 0);\n  let total = subtotal + tax - disc;\n  if (total < 0) total = 0;\n  $("#totals").innerHTML = `\n    <div class="t-row"><span class="muted">Subtotal</span><span>${fmtMoney(subtotal)}</span></div>\n    <div class="t-row"><span class="muted">VAT (${rate}%)</span><span>${fmtMoney(tax)}</span></div>\n    ${disc ? `<div class="t-row"><span class="muted">Discount</span><span>− ${fmtMoney(disc)}</span></div>` : ""}\n    <div class="t-row grand"><span>Total</span><span>${fmtMoney(total)}</span></div>`;\n}\n\nasync function saveInvoice(id, statusOverride) {\n  const customer_id = Number($("#f-customer").value);\n  const body = {\n    customer_id,\n    issue_date: $("#f-issue").value,\n    due_date: $("#f-due").value,\n    discount: Number($("#f-discount").value || 0),\n    notes: $("#f-notes").value,\n    terms: $("#f-terms").value,\n    status: statusOverride,\n    items: window._items.filter((it) => it.description || it.qty > 0),\n  };\n  if (!body.customer_id) { toast("Please select a customer", "error"); return; }\n  if (!body.items.length) { toast("Add at least one line item", "error"); return; }\n  try {\n    const r = id ? await api("/invoices/" + id, { method: "PUT", body: JSON.stringify(body) })\n                 : await api("/invoices", { method: "POST", body: JSON.stringify(body) });\n    toast(statusOverride === "sent" ? "Invoice sent" : "Invoice saved");\n    location.hash = "#/invoice/view/" + r.id;\n  } catch (e) { toast(e.message, "error"); }\n}\n\n// ---- Invoice view ----\nasync function renderInvoiceView(args) {\n  const id = args[0];\n  const inv = (await api("/invoices/" + id)).invoice;\n  const c = inv.customer;\n  const view = $("#view");\n  const itemsHtml = inv.items.map((it, i) => `\n    <tr><td class="sl-num">${String(i + 1).padStart(2, "0")}</td><td>${esc(it.description)}</td><td class="num">${fmtNum(it.qty)}</td><td class="num">${fmtMoney(it.unit_price)}</td><td class="num">${fmtMoney(it.unit_vat != null ? it.unit_vat : 0)}</td><td class="num">${fmtMoney(it.unit_total != null ? it.unit_total : it.unit_price)}</td></tr>`).join("");\n  const paysHtml = inv.payments.length ? inv.payments.map((p) => `\n    <tr><td class="small">${esc(p.date)}</td><td>${esc(p.method)}</td><td class="small">${esc(p.reference || "—")}</td><td class="num">${fmtMoney(p.amount)}</td>\n    <td><button class="btn btn-sm btn-danger" onclick="deletePayment(${p.id}, ${inv.id})">✕</button></td></tr>`).join("")\n    : `<tr><td colspan="5" class="muted">No payments recorded</td></tr>`;\n\n  const statusActions = [];\n  if (inv.status === "draft") statusActions.push(`<button class="btn btn-sm" onclick="setInvoiceStatus(${inv.id},\'sent\')">Mark as Sent</button>`);\n  if (inv.status !== "cancelled") statusActions.push(`<button class="btn btn-sm btn-danger" onclick="setInvoiceStatus(${inv.id},\'cancelled\')">Cancel</button>`);\n\n  view.innerHTML = `\n    <div class="page-head">\n      <div><h2>Invoice ${esc(inv.number)}</h2>\n        <div class="sub">${esc(c?.name || "")} · <span class="badge ${inv.status}">${inv.status}</span></div></div>\n      <div class="no-print" style="display:flex;gap:8px;flex-wrap:wrap">\n        <a class="btn btn-sm" href="#/invoice/edit/${inv.id}">Edit</a>\n        <button class="btn btn-sm" onclick="openTermsModal(${inv.id})">✎ Terms</button>\n        <button class="btn btn-sm" onclick="printDoc(\'invoice\', ${inv.id})">🖨 Print / PDF</button>\n        <button class="btn btn-sm btn-primary" onclick="openPaymentModal(${inv.id})">+ Record Payment</button>\n        ${statusActions.join("")}\n      </div>\n    </div>\n    <div class="grid grid-3" style="margin-bottom:16px">\n      <div class="card"><div class="stat"><span class="label">Total</span><span class="value">${fmtMoney(inv.total)}</span></div></div>\n      <div class="card"><div class="stat"><span class="label">Paid</span><span class="value" style="color:var(--green)">${fmtMoney(inv.paid_amount)}</span></div></div>\n      <div class="card"><div class="stat"><span class="label">Balance due</span><span class="value" style="color:${inv.balance > 0 ? "var(--amber)" : "var(--green)"}">${fmtMoney(inv.balance)}</span></div></div>\n    </div>\n    <div class="card" style="margin-bottom:16px">\n      <h3 style="margin-bottom:12px">Line items</h3>\n      <div class="table-wrap"><table><thead><tr><th>SL</th><th>Item Description</th><th class="num">Quantity</th><th class="num">Price Before VAT</th><th class="num">${state.company?.vat_rate ?? 5}% VAT</th><th class="num">Total Amount</th></tr></thead><tbody>${itemsHtml}</tbody></table></div>\n      <div class="totals-box"><div class="totals">\n        <div class="t-row"><span class="muted">Amount Before VAT</span><span>${fmtMoney(inv.subtotal)}</span></div>\n        <div class="t-row"><span class="muted">VAT Amount (${state.company?.vat_rate ?? 5}%)</span><span>${fmtMoney(inv.tax_amount)}</span></div>\n        <div class="t-row"><span class="muted">Amount With VAT</span><span>${fmtMoney(Number(inv.subtotal) + Number(inv.tax_amount))}</span></div>\n        ${Number(inv.discount) ? `<div class="t-row"><span class="muted">Discount</span><span>− ${fmtMoney(inv.discount)}</span></div>` : ""}\n        <div class="t-row grand"><span>Total</span><span>${fmtMoney(inv.total)}</span></div>\n        <div class="t-row"><span class="muted">Amount Received</span><span style="color:var(--green)">${fmtMoney(inv.paid_amount)}</span></div>\n        <div class="t-row"><span class="muted">Amount Balance</span><span style="color:${inv.balance > 0 ? "var(--amber)" : "var(--green)"}">${fmtMoney(inv.balance)}</span></div>\n      </div></div>\n    </div>\n    <div class="card" style="margin-bottom:16px"><h3 style="margin-bottom:12px">Payments</h3>\n      <div class="table-wrap"><table><thead><tr><th>Date</th><th>Method</th><th>Reference</th><th class="num">Amount</th><th></th></tr></thead><tbody>${paysHtml}</tbody></table></div>\n    </div>\n    <div class="card">\n      <div class="grid grid-2">\n        <div><h3 style="margin-bottom:10px">Terms</h3><div class="muted" style="white-space:pre-line">${esc(inv.terms || "—")}</div></div>\n        <div><h3 style="margin-bottom:10px">Notes</h3><div class="muted" style="white-space:pre-line">${esc(inv.notes || "—")}</div></div>\n      </div>\n    </div>`;\n}\n\nasync function setInvoiceStatus(id, status) {\n  try {\n    await api("/invoices/" + id + "/status", { method: "POST", body: JSON.stringify({ status }) });\n    toast("Status updated");\n    location.hash = "#/invoice/view/" + id;\n  } catch (e) { toast(e.message, "error"); }\n}\n\nasync function openTermsModal(invoiceId) {\n  const inv = (await api("/invoices/" + invoiceId)).invoice;\n  openModal("Edit terms & notes", `\n    <div class="form-grid" style="grid-template-columns:1fr">\n      <div class="field"><label>Terms &amp; Conditions</label><textarea id="t-terms" rows="5">${esc(inv.terms || "")}</textarea></div>\n      <div class="field"><label>Notes</label><textarea id="t-notes" rows="4">${esc(inv.notes || "")}</textarea></div>\n    </div>`,\n    `<button class="btn btn-primary btn-block" onclick="saveTerms(${invoiceId})">Save</button>`);\n}\n\nasync function saveTerms(invoiceId) {\n  const inv = (await api("/invoices/" + invoiceId)).invoice;\n  const body = {\n    customer_id: inv.customer_id,\n    issue_date: inv.issue_date,\n    due_date: inv.due_date,\n    discount: inv.discount,\n    notes: $("#t-notes").value,\n    terms: $("#t-terms").value,\n    status: inv.status,\n    items: inv.items.map((it) => ({ product_id: it.product_id, description: it.description, qty: it.qty, unit_price: it.unit_price })),\n  };\n  try {\n    await api("/invoices/" + invoiceId, { method: "PUT", body: JSON.stringify(body) });\n    closeModal(); toast("Terms saved");\n    location.hash = "#/invoice/view/" + invoiceId;\n  } catch (e) { toast(e.message, "error"); }\n}\n\nfunction openPaymentModal(invoiceId) {\n  openModal("Record payment", `\n    <div class="form-grid" style="grid-template-columns:1fr">\n      <div class="field"><label>Amount *</label><input type="number" id="pay-amount" step="0.01" min="0.01" placeholder="0.00"></div>\n      <div class="field"><label>Date</label><input type="date" id="pay-date" value="${today()}"></div>\n      <div class="field"><label>Method</label><select id="pay-method">\n        ${["cash","card","bank_transfer","cheque","other"].map((m) => `<option value="${m}">${m.replace("_", " ")}</option>`).join("")}</select></div>\n      <div class="field"><label>Reference</label><input type="text" id="pay-ref" placeholder="e.g. Cheque #, transaction ID"></div>\n      <div class="field"><label>Note</label><input type="text" id="pay-note" placeholder="Optional"></div>\n    </div>`,\n    `<button class="btn btn-primary btn-block" onclick="submitPayment(${invoiceId})">Record payment</button>`);\n}\n\nasync function submitPayment(invoiceId) {\n  const body = {\n    amount: Number($("#pay-amount").value),\n    date: $("#pay-date").value,\n    method: $("#pay-method").value,\n    reference: $("#pay-ref").value,\n    note: $("#pay-note").value,\n  };\n  if (!body.amount || body.amount <= 0) { toast("Enter a valid amount", "error"); return; }\n  try {\n    await api("/invoices/" + invoiceId + "/payments", { method: "POST", body: JSON.stringify(body) });\n    closeModal(); toast("Payment recorded"); location.hash = "#/invoice/view/" + invoiceId;\n  } catch (e) { toast(e.message, "error"); }\n}\n\nasync function deletePayment(paymentId, invoiceId) {\n  if (!confirm("Delete this payment?")) return;\n  await api("/payments/" + paymentId, { method: "DELETE" });\n  toast("Payment deleted"); location.hash = "#/invoice/view/" + invoiceId;\n}\n\n// ================= QUOTES =================\nasync function renderQuotes() {\n  const qs = (await api("/quotes")).quotes;\n  state.quotes = qs;\n  const view = $("#view");\n  view.innerHTML = `\n    <div class="page-head">\n      <div><h2>Quotations</h2><div class="sub">${qs.length} quotations</div></div>\n      <a class="btn btn-primary" href="#/quote/new">+ New Quotation</a>\n    </div>\n    <div class="card"><div class="table-wrap"><table><thead><tr><th>Number</th><th>Customer</th><th>Issued</th><th>Valid until</th><th class="num">Total</th><th>Status</th></tr></thead>\n    <tbody>${qs.length ? qs.map((q) => `\n      <tr class="clickable" onclick="location.hash=\'#/quote/view/${q.id}\'">\n        <td class="mono">${esc(q.number)}</td><td>${esc(q.customer?.name || "—")}</td>\n        <td class="small muted">${esc(q.issue_date)}</td><td class="small muted">${esc(q.valid_until)}</td>\n        <td class="num">${fmtMoney(q.total)}</td><td><span class="badge ${q.status}">${q.status}</span></td>\n      </tr>`).join("") : `<tr><td colspan="6" class="empty"><div class="big">📄</div>No quotations yet</td></tr>`}</tbody></table></div></div>`;\n}\n\nasync function renderQuoteForm(args) {\n  const id = args[0];\n  let q = null;\n  if (id) q = (await api("/quotes/" + id)).quote;\n  const customers = (await api("/customers")).customers;\n  const products = (await api("/products")).products;\n  state.customers = customers; state.products = products;\n  const items = q ? q.items.map((it) => ({ product_id: it.product_id, description: it.description, qty: it.qty, unit_price: it.unit_price }))\n    : [{ product_id: null, description: "", qty: 1, unit_price: 0 }];\n\n  const view = $("#view");\n  view.innerHTML = `\n    <div class="page-head">\n      <div><h2>${q ? "Edit Quotation " + esc(q.number) : "New Quotation"}</h2><div class="sub">Send a price quote to a customer</div></div>\n      <div style="display:flex;gap:10px">\n        <a class="btn" href="#/quotes">Cancel</a>\n        <button class="btn btn-primary" onclick="saveQuote(${id || "null"}, \'draft\')">Save Draft</button>\n        <button class="btn btn-primary" style="background:var(--green);border-color:var(--green)" onclick="saveQuote(${id || "null"}, \'sent\')">Save & Send</button>\n      </div>\n    </div>\n    <div class="card">\n      <div class="form-grid">\n        <div class="field full"><label>Customer *</label>\n          <select id="q-customer">${customers.map((c) => `<option value="${c.id}" ${q && q.customer_id == c.id ? "selected" : ""}>${esc(c.name)}${c.company_name ? " — " + esc(c.company_name) : ""}</option>`).join("")}</select>\n        </div>\n        <div class="field"><label>Issue date</label><input type="date" id="q-issue" value="${q ? q.issue_date : today()}"></div>\n        <div class="field"><label>Valid until</label><input type="date" id="q-valid" value="${q ? q.valid_until : addDays(30)}"></div>\n        <div class="field"><label>Discount (${esc(state.company?.currency || "AED")})</label><input type="number" id="q-discount" step="0.01" min="0" value="${q ? q.discount : 0}"></div>\n        <div class="field"><label>Status</label><select id="q-status">\n          ${["draft","sent","accepted","rejected","expired"].map((s) => `<option value="${s}" ${q && q.status === s ? "selected" : ""}>${s[0].toUpperCase() + s.slice(1)}</option>`).join("")}\n        </select></div>\n        <div class="field full"><label>Notes</label><textarea id="q-notes">${esc(q?.notes || "")}</textarea></div>\n        <div class="field full"><label>Terms</label><textarea id="q-terms">${esc(q?.terms || state.company?.payment_terms || "")}</textarea></div>\n      </div>\n    </div>\n    <div class="card" style="margin-top:16px">\n      <div class="toolbar" style="margin-bottom:6px"><h3>Line items</h3><button class="btn btn-sm" onclick="addQuoteLine()">+ Add item</button></div>\n      <div id="q-line-items">${items.map((it, idx) => quoteLineHtml(it, idx)).join("")}</div>\n      <div class="totals-box"><div class="totals" id="q-totals"></div></div>\n    </div>`;\n  window._items = items;\n  recomputeQuoteTotals();\n}\n\nfunction quoteLineHtml(it, idx) {\n  const prodOpts = state.products.map((p) => `<option value="${p.id}" data-price="${p.sell_price}">${esc(p.name)}</option>`).join("");\n  return `<div class="line-item" data-idx="${idx}">\n    <div class="product-cell"><select onchange="quoteProduct(${idx}, this)">\n      <option value="">— Custom item —</option>${prodOpts}</select></div>\n    <input type="text" class="li-desc" placeholder="Description" value="${esc(it.description)}" oninput="quoteLineEdit(${idx})">\n    <input type="number" class="li-qty" placeholder="Qty" step="any" min="0" value="${it.qty}" oninput="quoteLineEdit(${idx})">\n    <input type="number" class="li-price" placeholder="Unit price" step="0.01" min="0" value="${it.unit_price}" oninput="quoteLineEdit(${idx})">\n    <button class="icon-btn del" style="color:var(--red)" onclick="removeQuoteLine(${idx})">✕</button>\n  </div>`;\n}\nfunction addQuoteLine() {\n  window._items.push({ product_id: null, description: "", qty: 1, unit_price: 0 });\n  $("#q-line-items").insertAdjacentHTML("beforeend", quoteLineHtml(window._items[window._items.length - 1], window._items.length - 1));\n  recomputeQuoteTotals();\n}\nfunction removeQuoteLine(idx) {\n  if (window._items.length <= 1) { toast("At least one line item is required", "error"); return; }\n  window._items.splice(idx, 1);\n  $("#q-line-items").innerHTML = window._items.map((it, i) => quoteLineHtml(it, i)).join("");\n  recomputeQuoteTotals();\n}\nfunction quoteProduct(idx, sel) {\n  const it = window._items[idx];\n  if (sel.value) { it.product_id = Number(sel.value); it.description = sel.options[sel.selectedIndex].text; it.unit_price = Number(sel.selectedOptions[0].dataset.price || 0); }\n  else { it.product_id = null; it.description = ""; }\n  const el = $$("#q-line-items .line-item")[idx];\n  el.querySelector(".li-desc").value = it.description;\n  el.querySelector(".li-price").value = it.unit_price;\n  recomputeQuoteTotals();\n}\nfunction quoteLineEdit(idx) {\n  const el = $$("#q-line-items .line-item")[idx];\n  window._items[idx].description = el.querySelector(".li-desc").value;\n  window._items[idx].qty = Number(el.querySelector(".li-qty").value || 0);\n  window._items[idx].unit_price = Number(el.querySelector(".li-price").value || 0);\n  recomputeQuoteTotals();\n}\nfunction recomputeQuoteTotals() {\n  const rate = state.company?.vat_rate ?? 5;\n  let subtotal = 0, tax = 0;\n  for (const it of window._items) {\n    const lt = (it.qty || 0) * (it.unit_price || 0); subtotal += lt;\n    const prod = state.products.find((p) => p.id === it.product_id);\n    if (prod ? prod.is_taxable : true) tax += lt * rate / 100;\n  }\n  const disc = Number($("#q-discount").value || 0);\n  let total = subtotal + tax - disc; if (total < 0) total = 0;\n  $("#q-totals").innerHTML = `\n    <div class="t-row"><span class="muted">Subtotal</span><span>${fmtMoney(subtotal)}</span></div>\n    <div class="t-row"><span class="muted">VAT (${rate}%)</span><span>${fmtMoney(tax)}</span></div>\n    ${disc ? `<div class="t-row"><span class="muted">Discount</span><span>− ${fmtMoney(disc)}</span></div>` : ""}\n    <div class="t-row grand"><span>Total</span><span>${fmtMoney(total)}</span></div>`;\n}\n\nasync function saveQuote(id, statusOverride) {\n  const body = {\n    customer_id: Number($("#q-customer").value),\n    issue_date: $("#q-issue").value,\n    valid_until: $("#q-valid").value,\n    discount: Number($("#q-discount").value || 0),\n    notes: $("#q-notes").value,\n    terms: $("#q-terms").value,\n    status: statusOverride,\n    items: window._items.filter((it) => it.description || it.qty > 0),\n  };\n  if (!body.customer_id) { toast("Please select a customer", "error"); return; }\n  if (!body.items.length) { toast("Add at least one line item", "error"); return; }\n  try {\n    const r = id ? await api("/quotes/" + id, { method: "PUT", body: JSON.stringify(body) })\n                 : await api("/quotes", { method: "POST", body: JSON.stringify(body) });\n    toast("Quotation saved"); location.hash = "#/quote/view/" + r.id;\n  } catch (e) { toast(e.message, "error"); }\n}\n\nasync function renderQuoteView(args) {\n  const id = args[0];\n  const q = (await api("/quotes/" + id)).quote;\n  const view = $("#view");\n  const itemsHtml = q.items.map((it, i) => `\n    <tr><td class="sl-num">${String(i + 1).padStart(2, "0")}</td><td>${esc(it.description)}</td><td class="num">${fmtNum(it.qty)}</td><td class="num">${fmtMoney(it.unit_price)}</td><td class="num">${fmtMoney(it.unit_vat != null ? it.unit_vat : 0)}</td><td class="num">${fmtMoney(it.unit_total != null ? it.unit_total : it.unit_price)}</td></tr>`).join("");\n  view.innerHTML = `\n    <div class="page-head">\n      <div><h2>Quotation ${esc(q.number)}</h2><div class="sub">${esc(q.customer?.name || "")} · <span class="badge ${q.status}">${q.status}</span></div></div>\n      <div class="no-print" style="display:flex;gap:8px;flex-wrap:wrap">\n        <a class="btn btn-sm" href="#/quote/edit/${q.id}">Edit</a>\n        <button class="btn btn-sm" onclick="printDoc(\'quote\', ${q.id})">🖨 Print / PDF</button>\n        ${q.status === "converted" ? `<span class="badge converted">Converted to invoice</span>` :\n          `<button class="btn btn-sm btn-primary" onclick="convertQuote(${q.id})">→ Convert to Invoice</button>`}\n      </div>\n    </div>\n    <div class="card" style="margin-bottom:16px">\n      <div class="grid grid-3">\n        <div class="stat"><span class="label">Issued</span><span class="value" style="font-size:17px">${esc(q.issue_date)}</span></div>\n        <div class="stat"><span class="label">Valid until</span><span class="value" style="font-size:17px">${esc(q.valid_until)}</span></div>\n        <div class="stat"><span class="label">Total</span><span class="value" style="font-size:17px">${fmtMoney(q.total)}</span></div>\n      </div>\n    </div>\n    <div class="card">\n      <h3 style="margin-bottom:12px">Line items</h3>\n      <div class="table-wrap"><table><thead><tr><th>SL</th><th>Item Description</th><th class="num">Quantity</th><th class="num">Price Before VAT</th><th class="num">${state.company?.vat_rate ?? 5}% VAT</th><th class="num">Total Amount</th></tr></thead><tbody>${itemsHtml}</tbody></table></div>\n      <div class="totals-box"><div class="totals">\n        <div class="t-row"><span class="muted">Amount Before VAT</span><span>${fmtMoney(q.subtotal)}</span></div>\n        <div class="t-row"><span class="muted">VAT Amount (${state.company?.vat_rate ?? 5}%)</span><span>${fmtMoney(q.tax_amount)}</span></div>\n        <div class="t-row"><span class="muted">Amount With VAT</span><span>${fmtMoney(Number(q.subtotal) + Number(q.tax_amount))}</span></div>\n        ${Number(q.discount) ? `<div class="t-row"><span class="muted">Discount</span><span>− ${fmtMoney(q.discount)}</span></div>` : ""}\n        <div class="t-row grand"><span>Total</span><span>${fmtMoney(q.total)}</span></div>\n      </div></div>\n    </div>`;\n}\n\nasync function convertQuote(id) {\n  if (!confirm("Convert this quotation to an invoice? Stock will be deducted when the invoice is sent.")) return;\n  try {\n    const r = await api("/quotes/" + id + "/convert", { method: "POST" });\n    toast("Converted to invoice " + r.number);\n    location.hash = "#/invoice/view/" + r.id;\n  } catch (e) { toast(e.message, "error"); }\n}\n\n// ================= CUSTOMERS =================\nasync function renderCustomers() {\n  const cs = (await api("/customers")).customers;\n  const view = $("#view");\n  view.innerHTML = `\n    <div class="page-head"><div><h2>Customers</h2><div class="sub">${cs.length} customers</div></div>\n      <button class="btn btn-primary" onclick="openCustomerModal()">+ New Customer</button></div>\n    <div class="card"><div class="table-wrap"><table><thead><tr><th>Name</th><th>Company</th><th>Contact</th><th>TRN</th><th class="num">Balance</th><th></th></tr></thead>\n    <tbody>${cs.length ? cs.map((c) => `\n      <tr><td>${esc(c.name)}</td><td>${esc(c.company_name || "—")}</td>\n        <td class="small">${esc(c.email || "")}${c.phone ? "<br>" + esc(c.phone) : ""}</td>\n        <td class="small mono">${esc(c.trn || "—")}</td>\n        <td class="num" style="color:${c.balance > 0 ? "var(--amber)" : "var(--green)"}">${c.balance > 0 ? fmtMoney(c.balance) : "—"}</td>\n        <td><div class="row-actions"><button class="btn btn-sm" onclick="openCustomerModal(${c.id})">Edit</button>\n        <button class="btn btn-sm" onclick="location.hash=\'#/statement/${c.id}\'">Statement</button>\n        <button class="btn btn-sm btn-danger" onclick="deleteCustomer(${c.id})">Del</button></div></td></tr>`).join("")\n      : `<tr><td colspan="6" class="empty"><div class="big">👥</div>No customers yet</td></tr>`}</tbody></table></div></div>`;\n}\n\nasync function openCustomerModal(id) {\n  let c = { name: "", company_name: "", email: "", phone: "", address: "", trn: "", credit_limit: 0 };\n  if (id) c = (await api("/customers/" + id)).customer;\n  openModal(id ? "Edit customer" : "New customer", `\n    <div class="form-grid">\n      <div class="field"><label>Name *</label><input id="c-name" value="${esc(c.name)}"></div>\n      <div class="field"><label>Company</label><input id="c-company" value="${esc(c.company_name)}"></div>\n      <div class="field"><label>Email</label><input id="c-email" type="email" value="${esc(c.email)}"></div>\n      <div class="field"><label>Phone</label><input id="c-phone" value="${esc(c.phone)}"></div>\n      <div class="field full"><label>Address</label><input id="c-address" value="${esc(c.address)}"></div>\n      <div class="field"><label>TRN (VAT number)</label><input id="c-trn" value="${esc(c.trn)}"></div>\n      <div class="field"><label>Credit limit</label><input id="c-limit" type="number" step="0.01" value="${c.credit_limit}"></div>\n    </div>`,\n    `<button class="btn btn-primary btn-block" onclick="saveCustomer(${id || "null"})">Save customer</button>`);\n}\n\nasync function saveCustomer(id) {\n  const body = {\n    name: $("#c-name").value, company_name: $("#c-company").value, email: $("#c-email").value,\n    phone: $("#c-phone").value, address: $("#c-address").value, trn: $("#c-trn").value,\n    credit_limit: Number($("#c-limit").value || 0),\n  };\n  if (!body.name) { toast("Name is required", "error"); return; }\n  try {\n    if (id) await api("/customers/" + id, { method: "PUT", body: JSON.stringify(body) });\n    else await api("/customers", { method: "POST", body: JSON.stringify(body) });\n    closeModal(); toast("Customer saved"); renderCustomers();\n  } catch (e) { toast(e.message, "error"); }\n}\nasync function deleteCustomer(id) {\n  if (!confirm("Delete this customer?")) return;\n  try { await api("/customers/" + id, { method: "DELETE" }); toast("Customer deleted"); renderCustomers(); }\n  catch (e) { toast(e.message, "error"); }\n}\n\n// ================= PRODUCTS =================\nasync function renderProducts() {\n  const ps = (await api("/products")).products;\n  const view = $("#view");\n  view.innerHTML = `\n    <div class="page-head"><div><h2>Products &amp; Stock</h2><div class="sub">${ps.length} products</div></div>\n      <button class="btn btn-primary" onclick="openProductModal()">+ New Product</button></div>\n    <div class="card"><div class="table-wrap"><table><thead><tr><th>Product</th><th>SKU</th><th class="num">Cost</th><th class="num">Price</th><th class="num">Stock</th><th>Status</th><th></th></tr></thead>\n    <tbody>${ps.length ? ps.map((p) => `\n      <tr><td>${esc(p.name)}<div class="muted small">${esc(p.description || "")}</div></td>\n        <td class="mono small">${esc(p.sku || "—")}</td>\n        <td class="num">${fmtMoney(p.cost_price)}</td><td class="num">${fmtMoney(p.sell_price)}</td>\n        <td class="num">${fmtNum(p.stock)} ${esc(p.unit)}</td>\n        <td>${p.low_stock ? `<span class="badge low">Low stock</span>` : `<span class="badge ok">In stock</span>`}</td>\n        <td><div class="row-actions">\n          <button class="btn btn-sm" onclick="openProductModal(${p.id})">Edit</button>\n          <button class="btn btn-sm" onclick="openStockModal(${p.id}, ${p.stock})">Adjust</button>\n          <button class="btn btn-sm" onclick="openMovements(${p.id})">History</button>\n          <button class="btn btn-sm btn-danger" onclick="deleteProduct(${p.id})">Del</button>\n        </div></td></tr>`).join("")\n      : `<tr><td colspan="7" class="empty"><div class="big">📦</div>No products yet</td></tr>`}</tbody></table></div></div>`;\n}\n\nasync function openProductModal(id) {\n  let p = { name: "", sku: "", description: "", unit: "pcs", cost_price: 0, sell_price: 0, stock: 0, low_stock_threshold: 0, is_taxable: true };\n  if (id) p = (await api("/products/" + id)).product;\n  openModal(id ? "Edit product" : "New product", `\n    <div class="form-grid">\n      <div class="field full"><label>Name *</label><input id="p-name" value="${esc(p.name)}"></div>\n      <div class="field"><label>SKU</label><input id="p-sku" value="${esc(p.sku)}"></div>\n      <div class="field"><label>Unit</label><input id="p-unit" value="${esc(p.unit)}"></div>\n      <div class="field full"><label>Description</label><input id="p-desc" value="${esc(p.description)}"></div>\n      <div class="field"><label>Cost price</label><input id="p-cost" type="number" step="0.01" value="${p.cost_price}"></div>\n      <div class="field"><label>Selling price</label><input id="p-sell" type="number" step="0.01" value="${p.sell_price}"></div>\n      <div class="field"><label>Initial stock</label><input id="p-stock" type="number" step="any" value="${p.stock}"></div>\n      <div class="field"><label>Low-stock alert at</label><input id="p-low" type="number" step="any" value="${p.low_stock_threshold}"></div>\n      <div class="field"><label>VAT</label><select id="p-tax"><option value="1" ${p.is_taxable ? "selected" : ""}>Taxable</option><option value="0" ${!p.is_taxable ? "selected" : ""}>Exempt</option></select></div>\n    </div>`,\n    `<button class="btn btn-primary btn-block" onclick="saveProduct(${id || "null"})">Save product</button>`);\n}\n\nasync function saveProduct(id) {\n  const body = {\n    name: $("#p-name").value, sku: $("#p-sku").value, description: $("#p-desc").value,\n    unit: $("#p-unit").value, cost_price: Number($("#p-cost").value || 0), sell_price: Number($("#p-sell").value || 0),\n    stock: Number($("#p-stock").value || 0), low_stock_threshold: Number($("#p-low").value || 0),\n    is_taxable: $("#p-tax").value === "1",\n  };\n  if (!body.name) { toast("Name is required", "error"); return; }\n  try {\n    if (id) await api("/products/" + id, { method: "PUT", body: JSON.stringify(body) });\n    else await api("/products", { method: "POST", body: JSON.stringify(body) });\n    closeModal(); toast("Product saved"); renderProducts();\n  } catch (e) { toast(e.message, "error"); }\n}\nasync function deleteProduct(id) {\n  if (!confirm("Delete this product?")) return;\n  try { await api("/products/" + id, { method: "DELETE" }); toast("Product deleted"); renderProducts(); }\n  catch (e) { toast(e.message, "error"); }\n}\n\nfunction openStockModal(id, current) {\n  openModal("Adjust stock", `\n    <p class="muted" style="margin-bottom:14px">Current stock: <strong>${fmtNum(current)}</strong>. Enter a positive or negative change (e.g. +5 to receive, −2 to remove).</p>\n    <div class="form-grid" style="grid-template-columns:1fr">\n      <div class="field"><label>Change (+/−) *</label><input type="number" id="s-change" step="any" placeholder="+5 or -2"></div>\n      <div class="field"><label>Reason</label><input type="text" id="s-reason" placeholder="e.g. Purchase, damage, correction"></div>\n    </div>`,\n    `<button class="btn btn-primary btn-block" onclick="submitStockAdjust(${id})">Apply adjustment</button>`);\n}\nasync function submitStockAdjust(id) {\n  const body = { change: Number($("#s-change").value), reason: $("#s-reason").value };\n  if (!body.change) { toast("Enter a change amount", "error"); return; }\n  try { await api("/stock/" + id + "/adjust", { method: "POST", body: JSON.stringify(body) }); closeModal(); toast("Stock updated"); renderProducts(); }\n  catch (e) { toast(e.message, "error"); }\n}\n\nasync function openMovements(id) {\n  const m = (await api("/stock/" + id + "/movements")).movements;\n  openModal("Stock history", `\n    <div class="table-wrap"><table><thead><tr><th>Date</th><th class="num">Change</th><th>Reason</th><th>Ref</th></tr></thead>\n    <tbody>${m.length ? m.map((x) => `<tr><td class="small">${esc(x.created_at)}</td>\n      <td class="num" style="color:${x.change >= 0 ? "var(--green)" : "var(--red)"}">${x.change >= 0 ? "+" : ""}${fmtNum(x.change)}</td>\n      <td>${esc(x.reason)}</td><td class="small mono">${esc(x.reference_type || "")}</td></tr>`).join("")\n      : `<tr><td colspan="4" class="muted">No movements</td></tr>`}</tbody></table></div>`, "");\n}\n\n// ================= PAYMENTS =================\nasync function renderPayments() {\n  const ps = (await api("/payments")).payments;\n  const view = $("#view");\n  const total = ps.reduce((s, p) => s + Number(p.amount), 0);\n  view.innerHTML = `\n    <div class="page-head"><div><h2>Payments</h2><div class="sub">${ps.length} payments · total ${fmtMoney(total)}</div></div></div>\n    <div class="card"><div class="table-wrap"><table><thead><tr><th>Date</th><th>Invoice</th><th>Customer</th><th>Method</th><th>Reference</th><th class="num">Amount</th></tr></thead>\n    <tbody>${ps.length ? ps.map((p) => `\n      <tr><td class="small">${esc(p.date)}</td><td class="mono link" onclick="location.hash=\'#/invoice/view/${p.invoice_id}\'">${esc(p.invoice_number)}</td>\n        <td>${esc(p.customer_name || "—")}</td><td>${esc(p.method.replace("_", " "))}</td>\n        <td class="small mono">${esc(p.reference || "—")}</td><td class="num" style="color:var(--green)">${fmtMoney(p.amount)}</td></tr>`).join("")\n      : `<tr><td colspan="6" class="empty"><div class="big">💵</div>No payments recorded yet</td></tr>`}</tbody></table></div></div>`;\n}\n\n// ================= EXPENSES =================\nconst EXPENSE_CATEGORIES = [\n  "Utilities (Electricity & Water)", "Rent", "Salaries & Wages", "Supplies & Materials",\n  "Telephone & Internet", "Transport & Fuel", "Maintenance & Repairs", "Marketing & Advertising",\n  "Insurance", "Government Fees & Licences", "Other",\n];\n\nasync function renderExpenses() {\n  const ex = (await api("/expenses")).expenses;\n  const view = $("#view");\n  const total = ex.reduce((s, e) => s + Number(e.amount), 0);\n  // group totals by category for summary\n  const byCat = {};\n  ex.forEach((e) => { byCat[e.category] = (byCat[e.category] || 0) + Number(e.amount); });\n\n  view.innerHTML = `\n    <div class="page-head"><div><h2>Expenses</h2><div class="sub">${ex.length} expense entries · total ${fmtMoney(total)}</div></div>\n      <button class="btn btn-primary" onclick="openExpenseModal()">+ Add Expense</button></div>\n    <div class="card"><div class="table-wrap"><table><thead><tr><th>Date</th><th>Category</th><th>Description</th><th class="num">Amount</th><th></th></tr></thead>\n    <tbody>${ex.length ? ex.map((e) => `\n      <tr><td class="small">${esc(e.date)}</td><td>${esc(e.category)}</td><td>${esc(e.description || "—")}</td>\n        <td class="num" style="color:var(--red)">${fmtMoney(e.amount)}</td>\n        <td><div class="row-actions">\n          <button class="btn btn-sm" onclick="openExpenseModal(${e.id})">Edit</button>\n          <button class="btn btn-sm btn-danger" onclick="deleteExpense(${e.id})">Del</button>\n        </div></td></tr>`).join("")\n      : `<tr><td colspan="5" class="empty"><div class="big">🧾</div>No expenses recorded yet</td></tr>`}</tbody></table></div></div>`;\n}\n\nasync function openExpenseModal(id) {\n  let e = { date: today(), category: EXPENSE_CATEGORIES[0], description: "", amount: 0 };\n  if (id) {\n    const all = (await api("/expenses")).expenses;\n    const found = all.find((x) => x.id === id);\n    if (found) e = found;\n  }\n  openModal(id ? "Edit expense" : "Add expense", `\n    <div class="form-grid">\n      <div class="field"><label>Date</label><input type="date" id="e-date" value="${esc(e.date)}"></div>\n      <div class="field"><label>Amount *</label><input type="number" id="e-amount" step="0.01" min="0.01" value="${e.amount}"></div>\n      <div class="field full"><label>Category</label>\n        <select id="e-category">${EXPENSE_CATEGORIES.map((c) => `<option ${e.category === c ? "selected" : ""}>${esc(c)}</option>`).join("")}</select>\n      </div>\n      <div class="field full"><label>Description</label><input id="e-desc" value="${esc(e.description)}" placeholder="e.g. DEWA bill, rent for shop, staff salary"></div>\n    </div>`,\n    `<button class="btn btn-primary btn-block" onclick="saveExpense(${id || "null"})">Save expense</button>`);\n}\n\nasync function saveExpense(id) {\n  const body = {\n    date: $("#e-date").value,\n    amount: Number($("#e-amount").value || 0),\n    category: $("#e-category").value,\n    description: $("#e-desc").value,\n  };\n  if (!body.amount || body.amount <= 0) { toast("Enter a valid amount", "error"); return; }\n  try {\n    if (id) await api("/expenses/" + id, { method: "PUT", body: JSON.stringify(body) });\n    else await api("/expenses", { method: "POST", body: JSON.stringify(body) });\n    closeModal(); toast("Expense saved"); renderExpenses();\n  } catch (e) { toast(e.message, "error"); }\n}\n\nasync function deleteExpense(id) {\n  if (!confirm("Delete this expense?")) return;\n  try { await api("/expenses/" + id, { method: "DELETE" }); toast("Expense deleted"); renderExpenses(); }\n  catch (e) { toast(e.message, "error"); }\n}\n\n// ================= STATEMENTS =================\nasync function renderStatement(args) {\n  const preselected = args[0] ? Number(args[0]) : null;\n  const customers = (await api("/customers")).customers;\n  const view = $("#view");\n  view.innerHTML = `\n    <div class="page-head">\n      <div><h2>Customer Statements</h2><div class="sub">Generate a statement of account to send to a customer</div></div>\n    </div>\n    <div class="card" style="max-width:900px">\n      <div class="toolbar">\n        <div class="searchbar">\n          <label class="small">Customer</label>\n          <select id="st-customer">${customers.map((c) => `<option value="${c.id}" ${preselected === c.id ? "selected" : ""}>${esc(c.name)}${c.company_name ? " — " + esc(c.company_name) : ""}</option>`).join("")}</select>\n          <label class="small">From</label><input type="date" id="st-from" value="${firstOfYear()}">\n          <label class="small">To</label><input type="date" id="st-to" value="${today()}">\n          <button class="btn btn-sm btn-primary" onclick="loadStatement()">Generate</button>\n          <button class="btn btn-sm" onclick="printStatement()">🖨 Print / PDF</button>\n        </div>\n      </div>\n      <div id="statement-body"></div>\n    </div>`;\n  window._stmt = { from: $("#st-from").value, to: $("#st-to").value };\n  loadStatement();\n}\n\nasync function loadStatement() {\n  const customer_id = $("#st-customer").value;\n  const from = $("#st-from").value, to = $("#st-to").value;\n  window._stmt = { customer_id, from, to };\n  const d = await api(`/reports/statement?customer_id=${customer_id}&from=${from}&to=${to}`);\n  const cust = d.customer;\n  const rows = d.transactions.map((t) => `\n    <tr>\n      <td class="small">${esc(t.date)}</td>\n      <td>${esc(t.desc)}<div class="muted small mono">${esc(t.ref || "")}</div></td>\n      <td class="num">${t.debit ? fmtMoney(t.debit) : ""}</td>\n      <td class="num">${t.credit ? fmtMoney(t.credit) : ""}</td>\n      <td class="num" style="font-weight:600">${fmtMoney(t.balance)}</td>\n    </tr>`).join("");\n  $("#statement-body").innerHTML = `\n    <div class="grid grid-3" style="margin:12px 0 16px">\n      <div class="stat"><span class="label">Customer</span><span class="value" style="font-size:16px">${esc(cust.name)}</span><span class="delta muted">${esc(cust.company_name || "")}</span></div>\n      <div class="stat"><span class="label">Opening Balance</span><span class="value" style="font-size:16px">${fmtMoney(d.opening_balance)}</span></div>\n      <div class="stat"><span class="label">Closing Balance</span><span class="value" style="font-size:16px;color:${d.closing_balance > 0 ? "var(--amber)" : "var(--green)"}">${fmtMoney(d.closing_balance)}</span></div>\n    </div>\n    <div class="table-wrap"><table><thead><tr><th>Date</th><th>Description</th><th class="num">Debit</th><th class="num">Credit</th><th class="num">Balance</th></tr></thead>\n    <tbody>${rows || `<tr><td colspan="5" class="muted">No transactions in this period</td></tr>`}</tbody></table></div>`;\n}\n\nasync function printStatement() {\n  const { customer_id, from, to } = window._stmt || {};\n  if (!customer_id) { toast("Select a customer first", "error"); return; }\n  const d = await api(`/reports/statement?customer_id=${customer_id}&from=${from}&to=${to}`);\n  const comp = (await api("/settings")).company;\n  const cust = d.customer;\n  const brand = comp?.name || "My Company LLC";\n  const tagline = comp?.tagline || "";\n  const rows = d.transactions.map((t) => `\n    <tr>\n      <td>${esc(t.date)}</td>\n      <td>${esc(t.desc)}${t.ref ? \' <span class="ref">\' + esc(t.ref) + "</span>" : ""}</td>\n      <td class="num">${t.debit ? fmtMoney(t.debit) : ""}</td>\n      <td class="num">${t.credit ? fmtMoney(t.credit) : ""}</td>\n      <td class="num">${fmtMoney(t.balance)}</td>\n    </tr>`).join("");\n  const html = \'<!DOCTYPE html><html><head><meta charset="utf-8"><title>Statement - \' + esc(cust.name) + \'</title><style>\' +\n    \'*{margin:0;padding:0;box-sizing:border-box}\' +\n    \'body{font-family:"Segoe UI",-apple-system,Arial,sans-serif;color:#1a202c;font-size:13px;background:#fff}\' +\n    \'.page{max-width:820px;margin:0 auto}\' +\n    \'.header{background:linear-gradient(135deg,#0c3740 0%,#0a4a54 45%,#037c84 100%);color:#fff;padding:24px 40px;position:relative;overflow:hidden}\' +\n    \'.header-top{display:flex;align-items:center;gap:18px}\' +\n    \'.logo-box{background:#fff;border-radius:10px;padding:8px 12px;flex-shrink:0;box-shadow:0 2px 8px rgba(0,0,0,.15)}\' +\n    \'.logo-box img{height:52px;width:auto;display:block}\' +\n    \'.doc-type{font-size:30px;font-weight:800;letter-spacing:2px;line-height:1}\' +\n    \'.brand{font-size:16px;font-weight:700;margin-top:6px}\' +\n    \'.tagline{font-size:11px;opacity:.9;margin-top:2px;letter-spacing:1.5px;text-transform:uppercase}\' +\n    \'.trn-chip{display:inline-block;margin-top:10px;font-size:10px;letter-spacing:.5px;background:rgba(255,255,255,.14);padding:4px 10px;border-radius:20px}\' +\n    \'.body{padding:30px 40px}\' +\n    \'.label{font-size:11px;text-transform:uppercase;letter-spacing:1.5px;color:#037c84;font-weight:800;margin-bottom:6px}\' +\n    \'.info-row{display:flex;justify-content:space-between;gap:30px;margin-bottom:24px}\' +\n    \'.bill-to .name{font-size:16px;font-weight:700}\' +\n    \'.bill-to .dim{color:#64748b;margin-top:2px}\' +\n    \'.meta{text-align:right}\' +\n    \'.m-row{display:flex;justify-content:space-between;gap:16px;padding:3px 0;border-bottom:1px dashed #e2e8f0;min-width:220px}\' +\n    \'.m-row .k{color:#64748b}\' +\n    \'.m-row .v{font-weight:700}\' +\n    \'table{width:100%;border-collapse:collapse;margin-top:8px}\' +\n    \'table thead th{background:#0c3740;color:#fff;padding:10px 14px;font-size:11px;text-transform:uppercase;letter-spacing:.7px;text-align:left}\' +\n    \'table thead th.num,table td.num{text-align:right}\' +\n    \'table td{padding:10px 14px;border-bottom:1px solid #e2e8f0}\' +\n    \'table tbody tr:nth-child(even){background:#f8fafc}\' +\n    \'.ref{color:#64748b;font-size:11px}\' +\n    \'.summary{display:flex;justify-content:flex-end;margin-top:18px}\' +\n    \'.summary-box{width:280px;border:1px solid #e2e8f0;border-radius:10px;overflow:hidden}\' +\n    \'.sb-head{background:#037c84;color:#fff;font-size:11px;font-weight:800;letter-spacing:1.5px;padding:9px 16px;text-transform:uppercase}\' +\n    \'.s-row{display:flex;justify-content:space-between;padding:9px 16px;font-size:13px;border-top:1px solid #f1f5f9}\' +\n    \'.s-row span:first-child{color:#475569}\' +\n    \'.s-row.big{font-size:16px;font-weight:800;color:#0c3740;border-top:2px solid #0c3740}\' +\n    \'.s-row.big span:last-child{color:#037c84}\' +\n    \'.footer{background:#0c3740;color:#d7f0f2;text-align:center;padding:16px 40px;font-size:11px;letter-spacing:.4px;margin-top:36px}\' +\n    \'.footer strong{color:#fff}\' +\n    \'@media print{.page{max-width:none}}\' +\n    \'</style></head><body><div class="page">\' +\n    \'<div class="header"><div class="header-top"><div class="logo-box"><img src="/logo.png"></div>\' +\n    \'<div><div class="doc-type">STATEMENT OF ACCOUNT</div><div class="brand">\' + esc(brand) + \'</div>\' +\n    (tagline ? \'<div class="tagline">\' + esc(tagline) + \'</div>\' : "") +\n    (comp?.trn ? \'<div class="trn-chip">TRN: \' + esc(comp.trn) + \'</div>\' : "") + \'</div></div></div>\' +\n    \'<div class="body">\' +\n    \'<div class="info-row"><div class="bill-to"><div class="label">Customer</div>\' +\n    \'<div class="name">\' + esc(cust.name) + \'</div>\' +\n    (cust.company_name ? \'<div class="dim">\' + esc(cust.company_name) + \'</div>\' : "") +\n    (cust.address ? \'<div class="dim">\' + esc(cust.address) + \'</div>\' : "") +\n    (cust.trn ? \'<div class="dim">TRN: \' + esc(cust.trn) + \'</div>\' : "") +\n    \'</div><div class="meta"><div class="label">Statement Details</div>\' +\n    \'<div class="m-row"><span class="k">Period</span><span class="v">\' + from + \' → \' + to + \'</span></div>\' +\n    \'<div class="m-row"><span class="k">Statement Date</span><span class="v">\' + today() + \'</span></div>\' +\n    \'<div class="m-row"><span class="k">Currency</span><span class="v">\' + esc(d.currency) + \'</span></div>\' +\n    \'</div></div>\' +\n    \'<table><thead><tr><th>Date</th><th>Description</th><th class="num">Debit</th><th class="num">Credit</th><th class="num">Balance</th></tr></thead>\' +\n    \'<tbody>\' + (rows || \'<tr><td colspan="5">No transactions</td></tr>\') + \'</tbody></table>\' +\n    \'<div class="summary"><div class="summary-box"><div class="sb-head">Summary</div>\' +\n    \'<div class="s-row"><span>Opening Balance</span><span>\' + fmtMoney(d.opening_balance) + \'</span></div>\' +\n    \'<div class="s-row big"><span>Closing Balance</span><span>\' + fmtMoney(d.closing_balance) + \'</span></div>\' +\n    \'</div></div></div>\' +\n    \'<div class="footer"><strong>\' + esc(brand) + \'</strong> · Thank you for your business!</div>\' +\n    \'</div><script>window.onload=function(){window.print();}</script></body></html>\';\n  const w = window.open("", "_blank");\n  w.document.write(html);\n  w.document.close();\n}\n\n// ================= REPORTS =================\nasync function renderReports() {\n  const view = $("#view");\n  view.innerHTML = `\n    <div class="page-head"><div><h2>Reports</h2><div class="sub">Insights into your business</div></div></div>\n    <div class="tabs" style="margin-bottom:16px">\n      <button class="tab active" onclick="showReport(\'sales\', this)">Sales</button>\n      <button class="tab" onclick="showReport(\'vat\', this)">VAT / Tax</button>\n      <button class="tab" onclick="showReport(\'pl\', this)">Profit &amp; Loss</button>\n      <button class="tab" onclick="showReport(\'profit\', this)">Profit</button>\n    </div>\n    <div id="report-body"></div>`;\n  showReport("sales", $(".tab"));\n}\n\nasync function showReport(type, btn) {\n  $$(".tab").forEach((t) => t.classList.remove("active"));\n  btn.classList.add("active");\n  const body = $("#report-body");\n  if (type === "sales") {\n    body.innerHTML = `<div class="card"><div class="toolbar">\n      <div class="searchbar"><label class="small">From</label><input type="date" id="rep-from" value="${firstOfMonth()}">\n      <label class="small">To</label><input type="date" id="rep-to" value="${today()}">\n      <button class="btn btn-sm btn-primary" onclick="loadSalesReport()">Apply</button></div></div>\n      <div id="sales-report"></div></div>`;\n    loadSalesReport();\n  } else if (type === "vat") {\n    const v = (await api("/reports/vat"));\n    body.innerHTML = `<div class="card"><h3 style="margin-bottom:14px">VAT report (rate ${v.vat_rate}%)</h3>\n      <div class="stat" style="margin-bottom:16px"><span class="label">Total VAT collected (sales)</span><span class="value" style="color:var(--primary)">${fmtMoney(v.sales_tax)}</span></div>\n      <div class="table-wrap"><table><thead><tr><th>Invoice</th><th>Date</th><th class="num">Total</th><th class="num">VAT</th></tr></thead>\n      <tbody>${v.invoices.map((i) => `<tr><td class="mono">${esc(i.number)}</td><td class="small">${esc(i.date)}</td><td class="num">${fmtMoney(i.total)}</td><td class="num">${fmtMoney(i.tax)}</td></tr>`).join("")}</tbody></table></div></div>`;\n  } else if (type === "pl") {\n    body.innerHTML = `<div class="card"><div class="toolbar">\n      <div class="searchbar"><label class="small">From</label><input type="date" id="pl-from" value="${firstOfYear()}">\n      <label class="small">To</label><input type="date" id="pl-to" value="${today()}">\n      <button class="btn btn-sm btn-primary" onclick="loadPLReport()">Calculate</button>\n      <button class="btn btn-sm" onclick="printPL()">🖨 Print / PDF</button></div></div>\n      <div id="pl-report"></div></div>`;\n    window._plRange = { from: $("#pl-from").value, to: $("#pl-to").value };\n    loadPLReport();\n  } else if (type === "profit") {\n    const p = (await api("/reports/profit"));\n    const margin = p.revenue ? ((p.profit / p.revenue) * 100).toFixed(1) : "0";\n    body.innerHTML = `<div class="card" style="margin-bottom:16px"><div class="grid grid-3">\n      <div class="stat"><span class="label">Revenue</span><span class="value">${fmtMoney(p.revenue)}</span></div>\n      <div class="stat"><span class="label">Cost of goods</span><span class="value">${fmtMoney(p.cost)}</span></div>\n      <div class="stat"><span class="label">Gross profit</span><span class="value" style="color:${p.profit >= 0 ? "var(--green)" : "var(--red)"}">${fmtMoney(p.profit)} <span class="small">(${margin}%)</span></span></div>\n    </div></div>\n    <div class="card"><div class="table-wrap"><table><thead><tr><th>Invoice</th><th>Item</th><th class="num">Qty</th><th class="num">Revenue</th><th class="num">Cost</th><th class="num">Profit</th></tr></thead>\n    <tbody>${p.detail.map((d) => `<tr><td class="mono small">${esc(d.invoice)}</td><td>${esc(d.description)}</td><td class="num">${fmtNum(d.qty)}</td><td class="num">${fmtMoney(d.revenue)}</td><td class="num">${fmtMoney(d.cost)}</td><td class="num" style="color:${d.profit >= 0 ? "var(--green)" : "var(--red)"}">${fmtMoney(d.profit)}</td></tr>`).join("")}</tbody></table></div></div>`;\n  }\n}\n\nasync function loadPLReport() {\n  const from = $("#pl-from").value, to = $("#pl-to").value;\n  window._plRange = { from, to };\n  const d = await api(`/reports/pl?from=${from}&to=${to}`);\n  const expRows = d.expenses_by_cat.length\n    ? d.expenses_by_cat.map((e) => `<tr><td>${esc(e.category)}</td><td class="num">${e.count}</td><td class="num" style="color:var(--red)">${fmtMoney(e.total)}</td></tr>`).join("")\n    : `<tr><td colspan="3" class="muted">No expenses in this period</td></tr>`;\n  const netColor = d.net_profit >= 0 ? "var(--green)" : "var(--red)";\n  const grossColor = d.gross_profit >= 0 ? "var(--green)" : "var(--red)";\n  $("#pl-report").innerHTML = `\n    <div class="grid grid-3" style="margin-bottom:16px">\n      <div class="card"><div class="stat"><span class="label">Revenue (Sales)</span><span class="value">${fmtMoney(d.revenue)}</span></div></div>\n      <div class="card"><div class="stat"><span class="label">Cost of Goods Sold</span><span class="value" style="color:var(--red)">${fmtMoney(d.cogs)}</span></div></div>\n      <div class="card"><div class="stat"><span class="label">Gross Profit</span><span class="value" style="color:${grossColor}">${fmtMoney(d.gross_profit)}</span></div></div>\n    </div>\n    <div class="card" style="margin-bottom:16px">\n      <h3 style="margin-bottom:12px">Expenses (${from} → ${to})</h3>\n      <div class="table-wrap"><table><thead><tr><th>Category</th><th class="num">Entries</th><th class="num">Amount</th></tr></thead><tbody>${expRows}</tbody></table></div>\n      <div class="totals-box"><div class="totals">\n        <div class="t-row grand"><span>Total Expenses</span><span style="color:var(--red)">${fmtMoney(d.total_expenses)}</span></div>\n      </div></div>\n    </div>\n    <div class="card" style="border-left:4px solid ${d.net_profit >= 0 ? "var(--green)" : "var(--red)"}">\n      <div class="stat"><span class="label">Net Profit / (Loss)</span>\n        <span class="value" style="font-size:28px;color:${netColor}">${fmtMoney(d.net_profit)}</span>\n        <span class="delta muted">${d.gross_profit} − ${d.total_expenses} = ${d.net_profit}</span></div>\n    </div>`;\n}\n\nasync function printPL() {\n  const { from, to } = window._plRange || {};\n  if (!from || !to) { toast("Select a date range first", "error"); return; }\n  const d = await api(`/reports/pl?from=${from}&to=${to}`);\n  const comp = (await api("/settings")).company;\n  const brand = comp?.name || "My Company LLC";\n  const expRows = d.expenses_by_cat.map((e) => `<tr><td>${esc(e.category)}</td><td class="num">${e.count}</td><td class="num">${fmtMoney(e.total)}</td></tr>`).join("");\n  const netColor = d.net_profit >= 0 ? "#16a34a" : "#dc2626";\n  const html = \'<!DOCTYPE html><html><head><meta charset="utf-8"><title>Profit &amp; Loss Statement</title><style>\' +\n    \'*{margin:0;padding:0;box-sizing:border-box}\' +\n    \'body{font-family:"Segoe UI",-apple-system,Arial,sans-serif;color:#1a202c;font-size:13px;background:#fff}\' +\n    \'.page{max-width:820px;margin:0 auto;padding:40px}\' +\n    \'.header{background:linear-gradient(135deg,#0c3740 0%,#0a4a54 45%,#037c84 100%);color:#fff;padding:28px 34px;border-radius:12px;margin-bottom:28px}\' +\n    \'.doc-type{font-size:30px;font-weight:800;letter-spacing:1.5px}\' +\n    \'.brand{font-size:16px;font-weight:700;margin-top:6px}\' +\n    \'.range{font-size:12px;opacity:.9;margin-top:8px}\' +\n    \'.label{font-size:11px;text-transform:uppercase;letter-spacing:1.5px;color:#037c84;font-weight:800;margin-bottom:10px}\' +\n    \'table{width:100%;border-collapse:collapse}\' +\n    \'table.pl th{background:#0c3740;color:#fff;padding:10px 14px;font-size:11px;text-transform:uppercase;text-align:left}\' +\n    \'table.pl td{padding:11px 14px;border-bottom:1px solid #e2e8f0}\' +\n    \'table.pl td.num{text-align:right}\' +\n    \'.section{margin-top:26px}\' +\n    \'.line{display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px dashed #e2e8f0}\' +\n    \'.line span:first-child{color:#475569}\' +\n    \'.line.bold{font-weight:800;font-size:15px;border-bottom:2px solid #0c3740;padding-top:12px}\' +\n    \'.line.net{font-size:18px;font-weight:800;padding-top:14px;border-bottom:none}\' +\n    \'.footer{background:#0c3740;color:#d7f0f2;text-align:center;padding:16px;font-size:11px;margin-top:36px;border-radius:10px}\' +\n    \'.footer strong{color:#fff}\' +\n    \'@media print{.page{max-width:none}}\' +\n    \'</style></head><body><div class="page">\' +\n    \'<div class="header"><div class="doc-type">PROFIT &amp; LOSS STATEMENT</div>\' +\n    \'<div class="brand">\' + esc(brand) + \'</div>\' +\n    \'<div class="range">Period: \' + from + \' to \' + to + \'</div></div>\' +\n    \'<div class="label">Income</div>\' +\n    \'<div class="line"><span>Revenue (Sales)</span><span>\' + fmtMoney(d.revenue) + \'</span></div>\' +\n    \'<div class="line"><span>Cost of Goods Sold</span><span>− \' + fmtMoney(d.cogs) + \'</span></div>\' +\n    \'<div class="line bold"><span>Gross Profit</span><span>\' + fmtMoney(d.gross_profit) + \'</span></div>\' +\n    \'<div class="section"><div class="label">Expenses</div>\' +\n    \'<table class="pl"><thead><tr><th>Category</th><th class="num">Entries</th><th class="num">Amount</th></tr></thead><tbody>\' + expRows + \'</tbody></table>\' +\n    \'<div class="line bold"><span>Total Expenses</span><span>− \' + fmtMoney(d.total_expenses) + \'</span></div></div>\' +\n    \'<div class="line net"><span>Net Profit / (Loss)</span><span style="color:\' + netColor + \'">\' + fmtMoney(d.net_profit) + \'</span></div>\' +\n    \'<div class="footer"><strong>\' + esc(brand) + \'</strong> · Generated on \' + today() + \'</div>\' +\n    \'</div><script>window.onload=function(){window.print();}</script></body></html>\';\n  const w = window.open("", "_blank");\n  w.document.write(html);\n  w.document.close();\n}\n\nasync function loadSalesReport() {\n  const from = $("#rep-from").value, to = $("#rep-to").value;\n  const r = await api(`/reports/sales?from=${from}&to=${to}`);\n  $("#sales-report").innerHTML = `\n    <div class="stat" style="margin:8px 0 16px"><span class="label">Total sales (${from} → ${to})</span><span class="value">${fmtMoney(r.total)}</span><span class="delta muted">VAT included: ${fmtMoney(r.tax_total)}</span></div>\n    <div class="table-wrap"><table><thead><tr><th>Number</th><th>Customer</th><th>Date</th><th class="num">Total</th><th>Status</th></tr></thead>\n    <tbody>${r.invoices.length ? r.invoices.map((i) => `<tr class="clickable" onclick="location.hash=\'#/invoice/view/${i.id}\'"><td class="mono">${esc(i.number)}</td><td>${esc(i.customer?.name || "—")}</td><td class="small">${esc(i.issue_date)}</td><td class="num">${fmtMoney(i.total)}</td><td><span class="badge ${i.status}">${i.status}</span></td></tr>`).join("") : `<tr><td colspan="5" class="empty">No sales in this period</td></tr>`}</tbody></table></div>`;\n}\n\n// ================= SETTINGS =================\nasync function renderSettings() {\n  const c = state.company || (await api("/settings")).company;\n  const view = $("#view");\n  view.innerHTML = `\n    <div class="page-head"><div><h2>Company Settings</h2><div class="sub">Your business details appear on invoices &amp; quotations</div></div></div>\n    <div class="card" style="max-width:720px">\n      <div class="form-grid">\n        <div class="field"><label>Company name *</label><input id="s-name" value="${esc(c.name)}"></div>\n        <div class="field"><label>Tagline (on documents)</label><input id="s-tagline" value="${esc(c.tagline || "")}" placeholder="e.g. Uniforms Made With Care"></div>\n        <div class="field"><label>Legal name</label><input id="s-legal" value="${esc(c.legal_name)}"></div>\n        <div class="field"><label>TRN (VAT registration number)</label><input id="s-trn" value="${esc(c.trn)}"></div>\n        <div class="field"><label>Phone</label><input id="s-phone" value="${esc(c.phone)}"></div>\n        <div class="field"><label>Email</label><input id="s-email" value="${esc(c.email)}"></div>\n        <div class="field"><label>Currency</label><select id="s-currency">${["AED","USD","EUR","GBP","SAR","INR"].map((x) => `<option ${c.currency === x ? "selected" : ""}>${x}</option>`).join("")}</select></div>\n        <div class="field"><label>VAT rate (%)</label><input id="s-vat" type="number" step="0.1" value="${c.vat_rate}"></div>\n        <div class="field"><label>Invoice prefix</label><input id="s-invpre" value="${esc(c.invoice_prefix)}"></div>\n        <div class="field"><label>Quote prefix</label><input id="s-quopre" value="${esc(c.quote_prefix)}"></div>\n        <div class="field full"><label>Address</label><input id="s-address" value="${esc(c.address)}"></div>\n        <div class="field full"><label>Default payment terms</label><input id="s-terms" value="${esc(c.payment_terms)}"></div>\n        <div class="field full"><label>Default invoice notes</label><textarea id="s-notes">${esc(c.invoice_notes)}</textarea></div>\n      </div>\n      <div class="form-actions"><button class="btn btn-primary" onclick="saveSettings()">Save settings</button></div>\n    </div>`;\n}\n\nasync function saveSettings() {\n  const body = {\n    name: $("#s-name").value, tagline: $("#s-tagline").value, legal_name: $("#s-legal").value, trn: $("#s-trn").value,\n    phone: $("#s-phone").value, email: $("#s-email").value, currency: $("#s-currency").value,\n    vat_rate: Number($("#s-vat").value || 0), invoice_prefix: $("#s-invpre").value,\n    quote_prefix: $("#s-quopre").value, address: $("#s-address").value,\n    payment_terms: $("#s-terms").value, invoice_notes: $("#s-notes").value,\n  };\n  if (!body.name) { toast("Company name is required", "error"); return; }\n  try {\n    await api("/settings", { method: "PUT", body: JSON.stringify(body) });\n    state.company = body;\n    $("#sidebar-company").textContent = body.name;\n    toast("Settings saved");\n  } catch (e) { toast(e.message, "error"); }\n}\n\n// ================= USERS =================\nasync function renderUsers() {\n  const us = (await api("/users")).users;\n  const view = $("#view");\n  view.innerHTML = `\n    <div class="page-head"><div><h2>Users</h2><div class="sub">Team members with access to this system</div></div>\n      <button class="btn btn-primary" onclick="openUserModal()">+ New User</button></div>\n    <div class="card"><div class="table-wrap"><table><thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th><th></th></tr></thead>\n    <tbody>${us.map((u) => `\n      <tr><td>${esc(u.name)}</td><td>${esc(u.email)}</td>\n        <td><span class="badge ${u.role}">${u.role}</span></td>\n        <td>${u.active ? `<span class="badge ok">Active</span>` : `<span class="badge expired">Disabled</span>`}</td>\n        <td><div class="row-actions">\n          <button class="btn btn-sm" onclick="openUserModal(${u.id})">Edit</button>\n          ${u.id !== state.user.id ? `<button class="btn btn-sm btn-danger" onclick="deleteUser(${u.id})">Del</button>` : ""}\n        </div></td></tr>`).join("")}</tbody></table></div></div>`;\n}\n\nasync function openUserModal(id) {\n  let u = { name: "", email: "", role: "staff", active: true };\n  if (id) { const r = (await api("/users")).users.find((x) => x.id === id); if (r) u = r; }\n  openModal(id ? "Edit user" : "New user", `\n    <div class="form-grid" style="grid-template-columns:1fr">\n      <div class="field"><label>Name</label><input id="u-name" value="${esc(u.name)}"></div>\n      <div class="field"><label>Email</label><input id="u-email" type="email" value="${esc(u.email)}"></div>\n      <div class="field"><label>Password ${id ? "(leave blank to keep)" : ""}</label><input id="u-pass" type="password" placeholder="${id ? "••••••••" : "Set a password"}"></div>\n      <div class="field"><label>Role</label><select id="u-role"><option value="staff" ${u.role === "staff" ? "selected" : ""}>Staff</option><option value="admin" ${u.role === "admin" ? "selected" : ""}>Admin</option></select></div>\n      ${id ? `<div class="field"><label>Status</label><select id="u-active"><option value="1" ${u.active ? "selected" : ""}>Active</option><option value="0" ${!u.active ? "selected" : ""}>Disabled</option></select></div>` : ""}\n    </div>`,\n    `<button class="btn btn-primary btn-block" onclick="saveUser(${id || "null"})">Save user</button>`);\n}\n\nasync function saveUser(id) {\n  const body = { name: $("#u-name").value, email: $("#u-email").value, role: $("#u-role").value };\n  if ($("#u-pass").value) body.password = $("#u-pass").value;\n  if (id) body.active = $("#u-active")?.value === "1";\n  try {\n    if (id) await api("/users/" + id, { method: "PUT", body: JSON.stringify(body) });\n    else await api("/users", { method: "POST", body: JSON.stringify(body) });\n    closeModal(); toast("User saved"); renderUsers();\n  } catch (e) { toast(e.message, "error"); }\n}\nasync function deleteUser(id) {\n  if (!confirm("Delete this user?")) return;\n  try { await api("/users/" + id, { method: "DELETE" }); toast("User deleted"); renderUsers(); }\n  catch (e) { toast(e.message, "error"); }\n}\n\n// ================= PRINT / PDF =================\nasync function printDoc(type, id) {\n  let doc, comp;\n  try { comp = (await api("/settings")).company; } catch {}\n  if (type === "invoice") doc = (await api("/invoices/" + id)).invoice;\n  else doc = (await api("/quotes/" + id)).quote;\n  const isQuote = type === "quote";\n  const docType = isQuote ? "QUOTATION" : "INVOICE";\n  const cust = doc.customer || {};\n  const brand = comp?.name || "My Company LLC";\n  const tagline = comp?.tagline || "";\n  const vatRate = comp?.vat_rate ?? 5;\n\n  const items = doc.items.map((it, i) => {\n    const sl = String(i + 1).padStart(2, "0");\n    const qty = Number(it.qty);\n    const unitVat = Number(it.unit_vat != null ? it.unit_vat : 0);\n    const unitTotal = Number(it.unit_total != null ? it.unit_total : it.unit_price);\n    return \'<tr><td class="sl">\' + sl + \'</td><td>\' + esc(it.description) + \'</td><td class="num">\' + fmtNum(qty) +\n      \'</td><td class="num">\' + fmtMoney(it.unit_price) + \'</td><td class="num">\' + fmtMoney(unitVat) +\n      \'</td><td class="num">\' + fmtMoney(unitTotal) + \'</td></tr>\';\n  }).join("");\n\n  const metaRows = isQuote\n    ? \'<div class="m-row"><span class="k">Quotation No.</span><span class="v">\' + esc(doc.number) + \'</span></div>\' +\n      \'<div class="m-row"><span class="k">Date</span><span class="v">\' + esc(doc.issue_date) + \'</span></div>\' +\n      \'<div class="m-row"><span class="k">Valid Until</span><span class="v">\' + esc(doc.valid_until) + \'</span></div>\'\n    : \'<div class="m-row"><span class="k">Invoice No.</span><span class="v">\' + esc(doc.number) + \'</span></div>\' +\n      \'<div class="m-row"><span class="k">Date</span><span class="v">\' + esc(doc.issue_date) + \'</span></div>\' +\n      \'<div class="m-row"><span class="k">Due Date</span><span class="v">\' + esc(doc.due_date) + \'</span></div>\';\n\n  const custLines = [\n    cust.name ? \'<div class="name">\' + esc(cust.name) + \'</div>\' : "",\n    cust.company_name ? "<div>" + esc(cust.company_name) + "</div>" : "",\n    cust.address ? \'<div class="dim">\' + esc(cust.address) + "</div>" : "",\n    cust.phone ? \'<div class="dim">Tel: \' + esc(cust.phone) + "</div>" : "",\n    cust.trn ? \'<div class="dim">TRN: \' + esc(cust.trn) + "</div>" : "",\n  ].join("");\n\n  const amountWithVat = Number(doc.subtotal) + Number(doc.tax_amount);\n  let totalRows = \'<div class="t-row"><span>Amount Before VAT</span><span>\' + fmtMoney(doc.subtotal) + "</span></div>";\n  totalRows += \'<div class="t-row"><span>VAT Amount (\' + vatRate + \'%)</span><span>\' + fmtMoney(doc.tax_amount) + "</span></div>";\n  totalRows += \'<div class="t-row"><span>Amount With VAT</span><span>\' + fmtMoney(amountWithVat) + "</span></div>";\n  if (Number(doc.discount)) totalRows += \'<div class="t-row"><span>Discount</span><span>− \' + fmtMoney(doc.discount) + "</span></div>";\n  totalRows += \'<div class="t-row grand"><span>Grand Total</span><span>\' + fmtMoney(doc.total) + "</span></div>";\n  if (!isQuote) {\n    totalRows += \'<div class="t-row"><span>Amount Received</span><span>\' + fmtMoney(doc.paid_amount) + "</span></div>";\n    totalRows += \'<div class="t-row due"><span>Amount Balance</span><span>\' + fmtMoney(doc.balance) + "</span></div>";\n  }\n\n  let contact = "";\n  if (comp?.phone) contact += \'<div><strong>Call:</strong> \' + esc(comp.phone) + "</div>";\n  if (comp?.email) contact += \'<div><strong>Email:</strong> \' + esc(comp.email) + "</div>";\n  if (comp?.address) contact += \'<div><strong>Address:</strong> \' + esc(comp.address) + "</div>";\n\n  const html = \'<!DOCTYPE html><html><head><meta charset="utf-8"><title>\' + esc(doc.number) + \'</title><style>\' +\n    \'*{margin:0;padding:0;box-sizing:border-box}\' +\n    \'body{font-family:"Segoe UI",-apple-system,Arial,sans-serif;color:#1a202c;font-size:13px;background:#fff}\' +\n    \'.page{max-width:820px;margin:0 auto}\' +\n    \'.header{background:linear-gradient(135deg,#0c3740 0%,#0a4a54 45%,#037c84 100%);color:#fff;padding:24px 40px;position:relative;overflow:hidden}\' +\n    \'.header-top{display:flex;align-items:center;gap:18px;position:relative;z-index:1}\' +\n    \'.logo-box{background:#fff;border-radius:10px;padding:8px 12px;flex-shrink:0;box-shadow:0 2px 8px rgba(0,0,0,.15)}\' +\n    \'.logo-box img{height:52px;width:auto;display:block}\' +\n    \'.header:after{content:"";position:absolute;right:-60px;top:-60px;width:220px;height:220px;border-radius:50%;background:rgba(255,255,255,.06)}\' +\n    \'.header:before{content:"";position:absolute;right:60px;top:40px;width:120px;height:120px;border-radius:50%;background:rgba(255,255,255,.05)}\' +\n    \'.doc-type{font-size:32px;font-weight:800;letter-spacing:2px;line-height:1}\' +\n    \'.brand{font-size:16px;font-weight:700;margin-top:6px}\' +\n    \'.tagline{font-size:11px;opacity:.9;margin-top:2px;letter-spacing:1.5px;text-transform:uppercase}\' +\n    \'.trn-chip{display:inline-block;margin-top:10px;font-size:10px;letter-spacing:.5px;background:rgba(255,255,255,.14);padding:4px 10px;border-radius:20px}\' +\n    \'.body{padding:30px 40px}\' +\n    \'.info-row{display:flex;justify-content:space-between;gap:30px}\' +\n    \'.bill-to{flex:1}\' +\n    \'.label{font-size:11px;text-transform:uppercase;letter-spacing:1.5px;color:#037c84;font-weight:800;margin-bottom:8px}\' +\n    \'.bill-to .name{font-size:16px;font-weight:700}\' +\n    \'.bill-to .dim{color:#64748b;margin-top:2px}\' +\n    \'.meta{min-width:210px;text-align:right}\' +\n    \'.m-row{display:flex;justify-content:space-between;gap:16px;padding:4px 0;border-bottom:1px dashed #e2e8f0}\' +\n    \'.m-row .k{color:#64748b}\' +\n    \'.m-row .v{font-weight:700}\' +\n    \'table.items{width:100%;border-collapse:collapse;margin-top:28px}\' +\n    \'table.items thead th{background:#0c3740;color:#fff;padding:11px 14px;font-size:11px;text-transform:uppercase;letter-spacing:.7px;text-align:left}\' +\n    \'table.items thead th.num,table.items td.num{text-align:right}\' +\n    \'table.items td{padding:11px 14px;border-bottom:1px solid #e2e8f0}\' +\n    \'table.items tbody tr:nth-child(even){background:#f8fafc}\' +\n    \'.sl{width:44px;font-weight:700;color:#037c84}\' +\n    \'.qty-note{color:#64748b;font-size:11px}\' +\n    \'.totals-wrap{display:flex;justify-content:flex-end;margin-top:20px}\' +\n    \'.totals{width:280px;border:1px solid #e2e8f0;border-radius:10px;overflow:hidden}\' +\n    \'.totals .t-head{background:#037c84;color:#fff;font-size:11px;font-weight:800;letter-spacing:1.5px;padding:9px 16px;text-transform:uppercase}\' +\n    \'.t-row{display:flex;justify-content:space-between;padding:8px 16px;font-size:13px}\' +\n    \'.t-row span:first-child{color:#475569}\' +\n    \'.t-row.grand{border-top:2px solid #0c3740;font-size:16px;font-weight:800;color:#0c3740;margin-top:2px;padding:11px 16px}\' +\n    \'.t-row.grand span:last-child{color:#037c84}\' +\n    \'.t-row.due{background:#fef3c7;font-weight:700;color:#b45309}\' +\n    \'.bottom{display:flex;justify-content:space-between;gap:30px;margin-top:32px}\' +\n    \'.terms{flex:1.2;font-size:11.5px;color:#475569;line-height:1.7}\' +\n    \'.contact{flex:1;font-size:11.5px;line-height:1.8;color:#475569}\' +\n    \'.signature{margin-top:44px;width:230px}\' +\n    \'.signature .line{border-top:1.5px solid #94a3b8;padding-top:6px;font-size:11px;color:#64748b;text-align:center;letter-spacing:.5px}\' +\n    \'.footer{background:#0c3740;color:#d7f0f2;text-align:center;padding:16px 40px;font-size:11px;letter-spacing:.4px}\' +\n    \'.footer strong{color:#fff}\' +\n    \'@media print{.page{max-width:none}}\' +\n    \'</style></head><body><div class="page">\' +\n    \'<div class="header"><div class="header-top"><div class="logo-box"><img src="/logo.png"></div>\' +\n    \'<div><div class="doc-type">\' + docType + \'</div>\' +\n    \'<div class="brand">\' + esc(brand) + \'</div>\' +\n    (tagline ? \'<div class="tagline">\' + esc(tagline) + \'</div>\' : "") +\n    (comp?.trn ? \'<div class="trn-chip">TRN: \' + esc(comp.trn) + \'</div>\' : "") +\n    \'</div></div></div>\' +\n    \'<div class="body">\' +\n    \'<div class="info-row"><div class="bill-to"><div class="label">Invoice To</div>\' + custLines + \'</div>\' +\n    \'<div class="meta">\' + metaRows + \'</div></div>\' +\n    \'<table class="items"><thead><tr><th class="sl">SL</th><th>Item Description</th><th class="num">Quantity</th><th class="num">Price Before VAT</th><th class="num">\' + vatRate + \'% VAT</th><th class="num">Total Amount</th></tr></thead>\' +\n    \'<tbody>\' + items + \'</tbody></table>\' +\n    \'<div class="totals-wrap"><div class="totals"><div class="t-head">Payment Info</div>\' + totalRows + \'</div></div>\' +\n    \'<div class="bottom"><div class="terms"><div class="label">Terms &amp; Conditions</div>\' +\n    (doc.terms ? esc(doc.terms) : "") + (doc.notes ? \'<br>\' + esc(doc.notes) : "") +\n    \'</div><div class="contact"><div class="label">Get in Touch</div>\' + contact + \'</div></div>\' +\n    \'<div class="signature"><div class="line">Authorised Signature</div></div>\' +\n    \'</div>\' +\n    \'<div class="footer"><strong>\' + esc(brand) + \'</strong> · Thank you for your business!</div>\' +\n    \'</div><script>window.onload=function(){window.print();}</script></body></html>\';\n\n  const w = window.open("", "_blank");\n  w.document.write(html);\n  w.document.close();\n}\n\n// ---------------- Utils ----------------\nfunction today() { return new Date().toISOString().slice(0, 10); }\nfunction addDays(n) { const d = new Date(); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10); }\nfunction firstOfMonth() { const d = new Date(); return d.toISOString().slice(0, 8) + "01"; }\nfunction firstOfYear() { return new Date().getFullYear() + "-01-01"; }\n\n// expose globals used by inline handlers\nObject.assign(window, {\n  closeModal, openModal, saveInvoice, addLineItem, removeLine, lineProduct, lineEdit,\n  saveQuote, addQuoteLine, removeQuoteLine, quoteProduct, quoteLineEdit,\n  openCustomerModal, saveCustomer, deleteCustomer, openProductModal, saveProduct, deleteProduct,\n  openStockModal, submitStockAdjust, openMovements, openPaymentModal, submitPayment,\n  setInvoiceStatus, deletePayment, convertQuote, openTermsModal, saveTerms, openUserModal, saveUser, deleteUser,\n  openExpenseModal, saveExpense, deleteExpense,\n  saveSettings, showReport, loadSalesReport, loadPLReport, printPL, printDoc,\n  loadStatement, printStatement,\n});\n\nboot();\n'

EMBEDDED_LOGO_B64 = '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'


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = db()
    c = conn.cursor()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'staff',   -- 'admin' | 'staff'
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        expires_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS company (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        name TEXT NOT NULL DEFAULT 'My Company LLC',
        tagline TEXT DEFAULT '',
        legal_name TEXT DEFAULT '',
        trn TEXT DEFAULT '',
        address TEXT DEFAULT '',
        phone TEXT DEFAULT '',
        email TEXT DEFAULT '',
        vat_rate REAL NOT NULL DEFAULT 5.0,
        currency TEXT NOT NULL DEFAULT 'AED',
        invoice_prefix TEXT NOT NULL DEFAULT 'INV',
        quote_prefix TEXT NOT NULL DEFAULT 'QUO',
        payment_terms TEXT DEFAULT 'Payment due within 14 days.',
        invoice_notes TEXT DEFAULT 'Thank you for your business.'
    );

    CREATE TABLE IF NOT EXISTS counters (
        type TEXT PRIMARY KEY,
        value INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        company_name TEXT DEFAULT '',
        email TEXT DEFAULT '',
        phone TEXT DEFAULT '',
        address TEXT DEFAULT '',
        trn TEXT DEFAULT '',
        credit_limit REAL DEFAULT 0,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        sku TEXT DEFAULT '',
        description TEXT DEFAULT '',
        unit TEXT DEFAULT 'pcs',
        cost_price REAL NOT NULL DEFAULT 0,
        sell_price REAL NOT NULL DEFAULT 0,
        stock REAL NOT NULL DEFAULT 0,
        low_stock_threshold REAL NOT NULL DEFAULT 0,
        is_taxable INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS invoices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        number TEXT NOT NULL UNIQUE,
        customer_id INTEGER NOT NULL,
        issue_date TEXT NOT NULL,
        due_date TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'draft', -- draft|sent|partial|paid|overdue|cancelled
        subtotal REAL NOT NULL DEFAULT 0,
        discount REAL NOT NULL DEFAULT 0,
        tax_amount REAL NOT NULL DEFAULT 0,
        total REAL NOT NULL DEFAULT 0,
        notes TEXT DEFAULT '',
        terms TEXT DEFAULT '',
        created_by INTEGER,
        created_at TEXT NOT NULL,
        FOREIGN KEY(customer_id) REFERENCES customers(id),
        FOREIGN KEY(created_by) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS invoice_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_id INTEGER NOT NULL,
        product_id INTEGER,
        description TEXT NOT NULL,
        qty REAL NOT NULL DEFAULT 1,
        unit_price REAL NOT NULL DEFAULT 0,
        line_total REAL NOT NULL DEFAULT 0,
        FOREIGN KEY(invoice_id) REFERENCES invoices(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS quotes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        number TEXT NOT NULL UNIQUE,
        customer_id INTEGER NOT NULL,
        issue_date TEXT NOT NULL,
        valid_until TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'draft', -- draft|sent|accepted|rejected|expired|converted
        subtotal REAL NOT NULL DEFAULT 0,
        discount REAL NOT NULL DEFAULT 0,
        tax_amount REAL NOT NULL DEFAULT 0,
        total REAL NOT NULL DEFAULT 0,
        notes TEXT DEFAULT '',
        terms TEXT DEFAULT '',
        created_by INTEGER,
        created_at TEXT NOT NULL,
        FOREIGN KEY(customer_id) REFERENCES customers(id)
    );

    CREATE TABLE IF NOT EXISTS quote_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        quote_id INTEGER NOT NULL,
        product_id INTEGER,
        description TEXT NOT NULL,
        qty REAL NOT NULL DEFAULT 1,
        unit_price REAL NOT NULL DEFAULT 0,
        line_total REAL NOT NULL DEFAULT 0,
        FOREIGN KEY(quote_id) REFERENCES quotes(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_id INTEGER NOT NULL,
        amount REAL NOT NULL,
        method TEXT DEFAULT 'cash',  -- cash|card|bank_transfer|cheque|other
        date TEXT NOT NULL,
        reference TEXT DEFAULT '',
        note TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        FOREIGN KEY(invoice_id) REFERENCES invoices(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS stock_movements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        change REAL NOT NULL,
        reason TEXT DEFAULT '',
        reference_type TEXT DEFAULT '',
        reference_id INTEGER,
        created_at TEXT NOT NULL,
        FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS activities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        action TEXT NOT NULL,
        entity TEXT NOT NULL,
        entity_id INTEGER,
        detail TEXT DEFAULT '',
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        category TEXT NOT NULL DEFAULT 'Other',
        description TEXT DEFAULT '',
        amount REAL NOT NULL DEFAULT 0,
        created_by INTEGER,
        created_at TEXT NOT NULL,
        FOREIGN KEY(created_by) REFERENCES users(id)
    );
    """)
    conn.commit()

    # Migrations for databases created before new columns were added
    colnames = [r[1] for r in c.execute("PRAGMA table_info(company)").fetchall()]
    if "tagline" not in colnames:
        c.execute("ALTER TABLE company ADD COLUMN tagline TEXT DEFAULT ''")
        conn.commit()

    # Seed admin + demo data on first run
    if c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        now = now_iso()
        admin_pw = os.environ.get("ADMIN_PASSWORD", "admin123")
        admin_hash = hash_password(admin_pw)
        staff_hash = hash_password("staff123")
        c.execute("INSERT INTO users(name,email,password_hash,role,created_at) VALUES(?,?,?,?,?)",
                  ("Admin", "admin@quickinvoice.com", admin_hash, "admin", now))
        c.execute("INSERT INTO users(name,email,password_hash,role,created_at) VALUES(?,?,?,?,?)",
                  ("Sales User", "sales@quickinvoice.com", staff_hash, "staff", now))
        c.execute("INSERT INTO company(id) VALUES(1)")
        conn.commit()
        seed_demo_data(conn)
    conn.close()


def seed_demo_data(conn):
    c = conn.cursor()
    now = now_iso()
    # Customers
    customers = [
        ("Al Noor Trading", "Al Noor Trading LLC", "info@alnoor.ae", "+971 4 123 4567",
         "Sheikh Zayed Road, Dubai", "100123456789003", 50000),
        ("Gulf Tech Systems", "Gulf Tech Systems FZE", "accounts@gulftech.ae", "+971 6 555 1234",
         "Ajman Free Zone, Ajman", "100987654321003", 25000),
        ("Desert Rose Catering", "Desert Rose Catering LLC", "billing@desertrose.ae", "+971 2 987 6543",
         "Hamdan Street, Abu Dhabi", "100555666777003", 30000),
    ]
    for x in customers:
        c.execute("INSERT INTO customers(name,company_name,email,phone,address,trn,credit_limit,created_at) "
                  "VALUES(?,?,?,?,?,?,?,?)", (*x, now))

    # Products
    products = [
        ("Laptop - Dell XPS 15", "LAP-001", "15.6\" laptop, 16GB RAM, 512GB SSD", "pcs", 4200, 4999, 25, 5, 1),
        ("Wireless Mouse", "MOU-001", "Bluetooth wireless mouse", "pcs", 40, 89, 120, 20, 1),
        ("Mechanical Keyboard", "KEY-001", "RGB mechanical keyboard", "pcs", 150, 249, 60, 10, 1),
        ("27\" Monitor", "MON-001", "27 inch 4K IPS monitor", "pcs", 780, 1099, 35, 8, 1),
        ("USB-C Cable 2m", "CAB-001", "Braided USB-C cable, 2 meter", "pcs", 8, 25, 300, 40, 1),
        ("Office Chair", "FRN-001", "Ergonomic mesh office chair", "pcs", 350, 649, 12, 4, 1),
    ]
    for x in products:
        c.execute("INSERT INTO products(name,sku,description,unit,cost_price,sell_price,stock,"
                  "low_stock_threshold,is_taxable,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (*x, now))

    # Counters
    c.execute("INSERT INTO counters(type,value) VALUES('invoice', 0)")
    c.execute("INSERT INTO counters(type,value) VALUES('quote', 0)")
    conn.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def now_iso():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_iso():
    return dt.date.today().isoformat()


def hash_password(pw):
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 120000).hex()
    return f"{salt}${h}"


def verify_password(pw, stored):
    try:
        salt, h = stored.split("$", 1)
        test = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 120000).hex()
        return secrets.compare_digest(test, h)
    except Exception:
        return False


def next_number(conn, ctype, prefix):
    c = conn.cursor()
    c.execute("UPDATE counters SET value = value + 1 WHERE type = ?", (ctype,))
    val = c.execute("SELECT value FROM counters WHERE type = ?", (ctype,)).fetchone()[0]
    conn.commit()
    return f"{prefix}-{val:04d}"


def get_company(conn):
    row = conn.execute("SELECT * FROM company WHERE id=1").fetchone()
    return dict(row) if row else {}


def log_activity(conn, user_id, action, entity, entity_id, detail=""):
    conn.execute("INSERT INTO activities(user_id,action,entity,entity_id,detail,created_at) "
                 "VALUES(?,?,?,?,?,?)", (user_id, action, entity, entity_id, detail, now_iso()))


def get_invoice_totals(conn, invoice_id):
    """Return (subtotal, tax_amount, total) recomputed from items."""
    c = conn.cursor()
    comp = get_company(conn)
    rate = float(comp.get("vat_rate", 5))
    items = c.execute("SELECT * FROM invoice_items WHERE invoice_id=?", (invoice_id,)).fetchall()
    subtotal = 0.0
    tax = 0.0
    for it in items:
        qty = float(it["qty"])
        price = float(it["unit_price"])
        line_total = qty * price
        taxable = True
        if it["product_id"]:
            p = c.execute("SELECT is_taxable FROM products WHERE id=?", (it["product_id"],)).fetchone()
            taxable = bool(p["is_taxable"]) if p else True
        subtotal += line_total
        if taxable:
            tax += line_total * rate / 100.0
    inv = c.execute("SELECT discount FROM invoices WHERE id=?", (invoice_id,)).fetchone()
    discount = float(inv["discount"]) if inv else 0.0
    total = subtotal + tax - discount
    if total < 0:
        total = 0.0
    return round(subtotal, 2), round(tax, 2), round(total, 2)


def get_quote_totals(conn, quote_id):
    c = conn.cursor()
    comp = get_company(conn)
    rate = float(comp.get("vat_rate", 5))
    items = c.execute("SELECT * FROM quote_items WHERE quote_id=?", (quote_id,)).fetchall()
    subtotal = 0.0
    tax = 0.0
    for it in items:
        qty = float(it["qty"])
        price = float(it["unit_price"])
        line_total = qty * price
        taxable = True
        if it["product_id"]:
            p = c.execute("SELECT is_taxable FROM products WHERE id=?", (it["product_id"],)).fetchone()
            taxable = bool(p["is_taxable"]) if p else True
        subtotal += line_total
        if taxable:
            tax += line_total * rate / 100.0
    q = c.execute("SELECT discount FROM quotes WHERE id=?", (quote_id,)).fetchone()
    discount = float(q["discount"]) if q else 0.0
    total = subtotal + tax - discount
    if total < 0:
        total = 0.0
    return round(subtotal, 2), round(tax, 2), round(total, 2)


def invoice_paid_amount(conn, invoice_id):
    row = conn.execute("SELECT COALESCE(SUM(amount),0) AS s FROM payments WHERE invoice_id=?",
                       (invoice_id,)).fetchone()
    return float(row["s"])


def recompute_invoice_status(conn, invoice_id):
    inv = conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
    if not inv:
        return
    paid = invoice_paid_amount(conn, invoice_id)
    total = float(inv["total"])
    status = inv["status"]
    if status in ("cancelled",):
        return
    if paid >= total and total > 0:
        new_status = "paid"
    elif paid > 0:
        new_status = "partial"
    elif status in ("draft", "sent", "overdue"):
        if inv["due_date"] and inv["due_date"] < today_iso() and status != "draft":
            new_status = "overdue"
        else:
            new_status = status if status in ("sent", "draft") else "sent"
    else:
        new_status = status
    conn.execute("UPDATE invoices SET status=? WHERE id=?", (new_status, invoice_id))
    conn.commit()


def apply_stock_for_invoice(conn, invoice_id, committed):
    """committed = True -> deduct stock; False -> restore stock. Idempotent."""
    c = conn.cursor()
    items = c.execute("SELECT * FROM invoice_items WHERE invoice_id=?", (invoice_id,)).fetchall()
    # First reverse any existing movements for this invoice
    existing = c.execute("SELECT * FROM stock_movements WHERE reference_type='invoice' AND reference_id=?",
                         (invoice_id,)).fetchall()
    for m in existing:
        c.execute("UPDATE products SET stock = stock - ? WHERE id=?", (float(m["change"]), m["product_id"]))
        c.execute("DELETE FROM stock_movements WHERE id=?", (m["id"],))
    if committed:
        for it in items:
            if not it["product_id"]:
                continue
            c.execute("UPDATE products SET stock = stock - ? WHERE id=?", (float(it["qty"]), it["product_id"]))
            c.execute("INSERT INTO stock_movements(product_id,change,reason,reference_type,reference_id,created_at) "
                      "VALUES(?,?,?,?,?,?)",
                      (it["product_id"], -float(it["qty"]), "Invoice", "invoice", invoice_id, now_iso()))
    conn.commit()


# ---------------------------------------------------------------------------
# HTTP server / routing
# ---------------------------------------------------------------------------

def enrich_line_items(conn, items):
    """Attach per-unit vat and per-unit total (price + vat) to each item dict,
    matching the template: Price Before VAT | 5% VAT | Total Amount (per unit)."""
    rate = float(get_company(conn).get("vat_rate", 5))
    out = []
    for it in items:
        d = dict(it)
        taxable = True
        if d.get("product_id"):
            p = conn.execute("SELECT is_taxable FROM products WHERE id=?", (d["product_id"],)).fetchone()
            taxable = bool(p["is_taxable"]) if p else True
        unit_price = float(d.get("unit_price") or 0)
        unit_vat = round(unit_price * rate / 100.0, 2) if taxable else 0.0
        d["unit_vat"] = unit_vat
        d["unit_total"] = round(unit_price + unit_vat, 2)
        out.append(d)
    return out

class Handler(BaseHTTPRequestHandler):
    server_version = "QuickInvoice/1.0"

    # --- helpers ---
    def send_json(self, obj, status=200):
        body = json.dumps(obj, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def current_user(self):
        conn = db()
        token = None
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
        else:
            cookie = self.headers.get("Cookie", "")
            m = re.search(r"(?:^|;\s*)qi_session=([^;]+)", cookie)
            if m:
                token = m.group(1)
        if not token:
            return None, conn
        row = conn.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id "
            "WHERE s.token=? AND s.expires_at > ?", (token, now_iso())).fetchone()
        if not row:
            return None, conn
        return dict(row), conn

    def require_user(self):
        user, conn = self.current_user()
        if not user:
            self.send_json({"error": "Authentication required"}, 401)
            return None, conn
        return user, conn

    # --- routing ---
    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def do_PUT(self):
        self.route("PUT")

    def do_DELETE(self):
        self.route("DELETE")

    def route(self, method):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        parts = [p for p in path.split("/") if p]

        # Static files
        if path == "/" or (len(parts) == 1 and parts[0] not in ("api",)):
            return self.serve_static(path)

        if parts[0] != "api":
            return self.serve_static(path)

        try:
            # /api/...
            if len(parts) == 1:
                return self.send_json({"app": "QuickInvoice", "status": "ok"})

            resource = parts[1]
            rid = parts[2] if len(parts) > 2 else None
            sub = parts[3] if len(parts) > 3 else None

            # --- auth ---
            if resource == "login" and method == "POST":
                return self.api_login()
            if resource == "logout" and method == "POST":
                return self.api_logout()
            if resource == "me" and method == "GET":
                return self.api_me()

            user, conn = self.require_user()
            if not user:
                return

            try:
                handlers = {
                "customers": self.api_customers,
                "products": self.api_products,
                "invoices": self.api_invoices,
                "quotes": self.api_quotes,
                "payments": self.api_payments,
                "reports": self.api_reports,
                "settings": self.api_settings,
                "users": self.api_users,
                "stock": self.api_stock,
                "expenses": self.api_expenses,
                }
                fn = handlers.get(resource)
                if not fn:
                    return self.send_json({"error": "Not found"}, 404)
                return fn(method, rid, sub, user, conn)
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
        except sqlite3.IntegrityError as e:
            return self.send_json({"error": f"Data integrity error: {e}"}, 400)
        except Exception as e:
            return self.send_json({"error": f"Server error: {e}"}, 500)
        finally:
            pass

    def serve_static(self, path):
        if path == "/":
            path = "/index.html"
        mapping = {
            "/index.html": ("text/html; charset=utf-8", EMBEDDED_INDEX),
            "/style.css": ("text/css; charset=utf-8", EMBEDDED_STYLE),
            "/app.js": ("application/javascript; charset=utf-8", EMBEDDED_APPJS),
            "/logo.png": ("image/png", base64.b64decode(EMBEDDED_LOGO_B64)),
        }
        if path in mapping:
            ctype, content = mapping[path]
            body = content.encode("utf-8") if isinstance(content, str) else content
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_json({"error": "Not found"}, 404)


    # --- auth ---
    def api_login(self):
        body = self.read_body()
        email = (body.get("email") or "").strip().lower()
        pw = body.get("password") or ""
        conn = db()
        row = conn.execute("SELECT * FROM users WHERE lower(email)=? AND active=1", (email,)).fetchone()
        if not row or not verify_password(pw, row["password_hash"]):
            return self.send_json({"error": "Invalid email or password"}, 401)
        token = secrets.token_hex(32)
        expires = (dt.datetime.now() + dt.timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("INSERT INTO sessions(token,user_id,expires_at) VALUES(?,?,?)",
                     (token, row["id"], expires))
        conn.commit()
        log_activity(conn, row["id"], "login", "user", row["id"], "")
        conn.commit()
        return self.send_json({"token": token, "user": self._public_user(dict(row))})

    def api_logout(self):
        user, conn = self.current_user()
        token = None
        cookie = self.headers.get("Cookie", "")
        m = re.search(r"(?:^|;\s*)qi_session=([^;]+)", cookie)
        if m:
            token = m.group(1)
        if token:
            conn.execute("DELETE FROM sessions WHERE token=?", (token,))
            conn.commit()
        return self.send_json({"ok": True})

    def api_me(self):
        user, conn = self.current_user()
        if not user:
            return self.send_json({"error": "Authentication required"}, 401)
        return self.send_json({"user": self._public_user(user)})

    @staticmethod
    def _public_user(u):
        return {"id": u["id"], "name": u["name"], "email": u["email"], "role": u["role"]}

    def require_admin(self, user, conn):
        if user["role"] != "admin":
            self.send_json({"error": "Admin access required"}, 403)
            return False
        return True

    # --- customers ---
    def api_customers(self, method, rid, sub, user, conn):
        c = conn.cursor()
        if method == "GET" and not rid:
            rows = c.execute("SELECT * FROM customers ORDER BY name").fetchall()
            out = []
            for r in rows:
                d = dict(r)
                bal = c.execute(
                    "SELECT COALESCE(SUM(total),0) FROM invoices WHERE customer_id=? AND status NOT IN ('paid','cancelled','draft')",
                    (r["id"],)).fetchone()[0]
                paid = c.execute(
                    "SELECT COALESCE(SUM(p.amount),0) FROM payments p JOIN invoices i ON i.id=p.invoice_id "
                    "WHERE i.customer_id=? AND i.status NOT IN ('cancelled')", (r["id"],)).fetchone()[0]
                d["balance"] = round(float(bal) - float(paid), 2)
                d["invoice_count"] = c.execute("SELECT COUNT(*) FROM invoices WHERE customer_id=?", (r["id"],)).fetchone()[0]
                out.append(d)
            return self.send_json({"customers": out})
        if method == "GET" and rid:
            row = c.execute("SELECT * FROM customers WHERE id=?", (rid,)).fetchone()
            if not row:
                return self.send_json({"error": "Not found"}, 404)
            return self.send_json({"customer": dict(row)})
        if method == "POST":
            body = self.read_body()
            name = (body.get("name") or "").strip()
            if not name:
                return self.send_json({"error": "Name is required"}, 400)
            c.execute("INSERT INTO customers(name,company_name,email,phone,address,trn,credit_limit,created_at) "
                      "VALUES(?,?,?,?,?,?,?,?)",
                      (name, body.get("company_name", ""), body.get("email", ""), body.get("phone", ""),
                       body.get("address", ""), body.get("trn", ""), float(body.get("credit_limit") or 0), now_iso()))
            conn.commit()
            log_activity(conn, user["id"], "create", "customer", c.lastrowid, name)
            conn.commit()
            return self.send_json({"id": c.lastrowid}, 201)
        if method == "PUT" and rid:
            body = self.read_body()
            c.execute("UPDATE customers SET name=?,company_name=?,email=?,phone=?,address=?,trn=?,credit_limit=? WHERE id=?",
                      (body.get("name", ""), body.get("company_name", ""), body.get("email", ""),
                       body.get("phone", ""), body.get("address", ""), body.get("trn", ""),
                       float(body.get("credit_limit") or 0), rid))
            conn.commit()
            log_activity(conn, user["id"], "update", "customer", rid, body.get("name", ""))
            conn.commit()
            return self.send_json({"ok": True})
        if method == "DELETE" and rid:
            c.execute("DELETE FROM customers WHERE id=?", (rid,))
            conn.commit()
            return self.send_json({"ok": True})
        return self.send_json({"error": "Bad request"}, 400)

    # --- products ---
    def api_products(self, method, rid, sub, user, conn):
        c = conn.cursor()
        if method == "GET" and not rid:
            rows = c.execute("SELECT * FROM products ORDER BY name").fetchall()
            out = []
            for r in rows:
                d = dict(r)
                d["low_stock"] = (d["stock"] <= d["low_stock_threshold"])
                out.append(d)
            return self.send_json({"products": out})
        if method == "GET" and rid:
            row = c.execute("SELECT * FROM products WHERE id=?", (rid,)).fetchone()
            if not row:
                return self.send_json({"error": "Not found"}, 404)
            return self.send_json({"product": dict(row)})
        if method == "POST":
            body = self.read_body()
            if not (body.get("name") or "").strip():
                return self.send_json({"error": "Name is required"}, 400)
            c.execute("INSERT INTO products(name,sku,description,unit,cost_price,sell_price,stock,"
                      "low_stock_threshold,is_taxable,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (body.get("name", ""), body.get("sku", ""), body.get("description", ""),
                       body.get("unit", "pcs"), float(body.get("cost_price") or 0), float(body.get("sell_price") or 0),
                       float(body.get("stock") or 0), float(body.get("low_stock_threshold") or 0),
                       1 if body.get("is_taxable", True) else 0, now_iso()))
            conn.commit()
            log_activity(conn, user["id"], "create", "product", c.lastrowid, body.get("name", ""))
            conn.commit()
            return self.send_json({"id": c.lastrowid}, 201)
        if method == "PUT" and rid:
            body = self.read_body()
            c.execute("UPDATE products SET name=?,sku=?,description=?,unit=?,cost_price=?,sell_price=?,"
                      "low_stock_threshold=?,is_taxable=? WHERE id=?",
                      (body.get("name", ""), body.get("sku", ""), body.get("description", ""),
                       body.get("unit", "pcs"), float(body.get("cost_price") or 0), float(body.get("sell_price") or 0),
                       float(body.get("low_stock_threshold") or 0), 1 if body.get("is_taxable", True) else 0, rid))
            conn.commit()
            log_activity(conn, user["id"], "update", "product", rid, body.get("name", ""))
            conn.commit()
            return self.send_json({"ok": True})
        if method == "DELETE" and rid:
            c.execute("DELETE FROM products WHERE id=?", (rid,))
            conn.commit()
            return self.send_json({"ok": True})
        return self.send_json({"error": "Bad request"}, 400)

    # --- invoices ---
    def api_invoices(self, method, rid, sub, user, conn):
        c = conn.cursor()
        if method == "GET" and not rid:
            rows = c.execute("SELECT * FROM invoices ORDER BY id DESC").fetchall()
            out = []
            for r in rows:
                d = self._invoice_view(conn, r)
                out.append(d)
            return self.send_json({"invoices": out})
        if method == "GET" and rid and sub is None:
            row = c.execute("SELECT * FROM invoices WHERE id=?", (rid,)).fetchone()
            if not row:
                return self.send_json({"error": "Not found"}, 404)
            d = self._invoice_view(conn, row, with_items=True)
            return self.send_json({"invoice": d})
        if method == "POST" and not rid:
            return self._save_invoice(user, conn, None)
        if method == "PUT" and rid:
            return self._save_invoice(user, conn, rid)
        if method == "DELETE" and rid:
            inv = c.execute("SELECT * FROM invoices WHERE id=?", (rid,)).fetchone()
            if not inv:
                return self.send_json({"error": "Not found"}, 404)
            apply_stock_for_invoice(conn, int(rid), committed=False)
            c.execute("DELETE FROM invoices WHERE id=?", (rid,))
            conn.commit()
            return self.send_json({"ok": True})
        # sub-actions: payments, status, print
        if method == "POST" and rid and sub == "payments":
            return self._add_payment(user, conn, rid)
        if method == "POST" and rid and sub == "status":
            return self._set_invoice_status(user, conn, rid)
        return self.send_json({"error": "Bad request"}, 400)

    def _invoice_view(self, conn, r, with_items=False):
        d = dict(r)
        cust = conn.execute("SELECT * FROM customers WHERE id=?", (r["customer_id"],)).fetchone()
        d["customer"] = dict(cust) if cust else None
        d["paid_amount"] = round(invoice_paid_amount(conn, r["id"]), 2)
        d["balance"] = round(float(r["total"]) - d["paid_amount"], 2)
        if with_items:
            items = conn.execute("SELECT * FROM invoice_items WHERE invoice_id=?", (r["id"],)).fetchall()
            d["items"] = enrich_line_items(conn, items)
            pays = conn.execute("SELECT * FROM payments WHERE invoice_id=? ORDER BY date DESC, id DESC",
                                (r["id"],)).fetchall()
            d["payments"] = [dict(p) for p in pays]
        return d

    def _save_invoice(self, user, conn, inv_id):
        body = self.read_body()
        customer_id = body.get("customer_id")
        if not customer_id:
            return self.send_json({"error": "Customer is required"}, 400)
        items = body.get("items") or []
        if not items:
            return self.send_json({"error": "At least one line item is required"}, 400)
        status = body.get("status", "draft")
        issue = body.get("issue_date") or today_iso()
        due = body.get("due_date") or issue
        c = conn.cursor()
        was_new = inv_id is None
        if inv_id:
            old = c.execute("SELECT * FROM invoices WHERE id=?", (inv_id,)).fetchone()
            if not old:
                return self.send_json({"error": "Not found"}, 404)
            number = old["number"]
            c.execute("DELETE FROM invoice_items WHERE invoice_id=?", (inv_id,))
            c.execute("UPDATE invoices SET customer_id=?,issue_date=?,due_date=?,status=?,discount=?,notes=?,terms=? "
                      "WHERE id=?", (customer_id, issue, due, status,
                                     float(body.get("discount") or 0), body.get("notes", ""), body.get("terms", ""), inv_id))
        else:
            number = next_number(conn, "invoice", get_company(conn).get("invoice_prefix", "INV"))
            c.execute("INSERT INTO invoices(number,customer_id,issue_date,due_date,status,discount,notes,terms,"
                      "created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (number, customer_id, issue, due, status, float(body.get("discount") or 0),
                       body.get("notes", ""), body.get("terms", ""), user["id"], now_iso()))
            inv_id = c.lastrowid
        for it in items:
            c.execute("INSERT INTO invoice_items(invoice_id,product_id,description,qty,unit_price,line_total) "
                      "VALUES(?,?,?,?,?,?)",
                      (inv_id, it.get("product_id"), it.get("description", ""), float(it.get("qty") or 0),
                       float(it.get("unit_price") or 0), float(it.get("qty") or 0) * float(it.get("unit_price") or 0)))
        subtotal, tax, total = get_invoice_totals(conn, inv_id)
        c.execute("UPDATE invoices SET subtotal=?,tax_amount=?,total=? WHERE id=?", (subtotal, tax, total, inv_id))
        # stock: reverse then apply if committed
        committed = status not in ("draft", "cancelled")
        apply_stock_for_invoice(conn, int(inv_id), committed)
        recompute_invoice_status(conn, int(inv_id))
        log_activity(conn, user["id"], "save", "invoice", inv_id, number)
        conn.commit()
        return self.send_json({"id": inv_id, "number": number}, 201 if was_new else 200)

    def _add_payment(self, user, conn, inv_id):
        body = self.read_body()
        amount = float(body.get("amount") or 0)
        if amount <= 0:
            return self.send_json({"error": "Amount must be positive"}, 400)
        conn.execute("INSERT INTO payments(invoice_id,amount,method,date,reference,note,created_at) "
                     "VALUES(?,?,?,?,?,?,?)",
                     (inv_id, amount, body.get("method", "cash"), body.get("date") or today_iso(),
                      body.get("reference", ""), body.get("note", ""), now_iso()))
        conn.commit()
        recompute_invoice_status(conn, int(inv_id))
        log_activity(conn, user["id"], "payment", "invoice", inv_id, f"{amount}")
        conn.commit()
        return self.send_json({"ok": True}, 201)

    def _set_invoice_status(self, user, conn, inv_id):
        body = self.read_body()
        status = body.get("status")
        if status not in ("draft", "sent", "cancelled"):
            return self.send_json({"error": "Invalid status"}, 400)
        conn.execute("UPDATE invoices SET status=? WHERE id=?", (status, inv_id))
        apply_stock_for_invoice(conn, int(inv_id), status not in ("draft", "cancelled"))
        conn.commit()
        recompute_invoice_status(conn, int(inv_id))
        log_activity(conn, user["id"], "status", "invoice", inv_id, status)
        conn.commit()
        return self.send_json({"ok": True})

    # --- quotes ---
    def api_quotes(self, method, rid, sub, user, conn):
        c = conn.cursor()
        if method == "GET" and not rid:
            rows = c.execute("SELECT * FROM quotes ORDER BY id DESC").fetchall()
            out = []
            for r in rows:
                d = self._quote_view(conn, r)
                out.append(d)
            return self.send_json({"quotes": out})
        if method == "GET" and rid and sub is None:
            row = c.execute("SELECT * FROM quotes WHERE id=?", (rid,)).fetchone()
            if not row:
                return self.send_json({"error": "Not found"}, 404)
            return self.send_json({"quote": self._quote_view(conn, row, with_items=True)})
        if method == "POST" and not rid:
            return self._save_quote(user, conn, None)
        if method == "PUT" and rid:
            return self._save_quote(user, conn, rid)
        if method == "DELETE" and rid:
            c.execute("DELETE FROM quotes WHERE id=?", (rid,))
            conn.commit()
            return self.send_json({"ok": True})
        if method == "POST" and rid and sub == "convert":
            return self._convert_quote(user, conn, rid)
        if method == "POST" and rid and sub == "status":
            body = self.read_body()
            st = body.get("status")
            if st not in ("draft", "sent", "accepted", "rejected", "expired"):
                return self.send_json({"error": "Invalid status"}, 400)
            c.execute("UPDATE quotes SET status=? WHERE id=?", (st, rid))
            conn.commit()
            log_activity(conn, user["id"], "status", "quote", rid, st)
            conn.commit()
            return self.send_json({"ok": True})
        return self.send_json({"error": "Bad request"}, 400)

    def _quote_view(self, conn, r, with_items=False):
        d = dict(r)
        cust = conn.execute("SELECT * FROM customers WHERE id=?", (r["customer_id"],)).fetchone()
        d["customer"] = dict(cust) if cust else None
        if with_items:
            d["items"] = enrich_line_items(conn, conn.execute(
                "SELECT * FROM quote_items WHERE quote_id=?", (r["id"],)).fetchall())
        return d

    def _save_quote(self, user, conn, qid):
        body = self.read_body()
        customer_id = body.get("customer_id")
        if not customer_id:
            return self.send_json({"error": "Customer is required"}, 400)
        items = body.get("items") or []
        if not items:
            return self.send_json({"error": "At least one line item is required"}, 400)
        c = conn.cursor()
        if qid:
            old = c.execute("SELECT * FROM quotes WHERE id=?", (qid,)).fetchone()
            if not old:
                return self.send_json({"error": "Not found"}, 404)
            number = old["number"]
            c.execute("DELETE FROM quote_items WHERE quote_id=?", (qid,))
            c.execute("UPDATE quotes SET customer_id=?,issue_date=?,valid_until=?,status=?,discount=?,notes=?,terms=? "
                      "WHERE id=?", (customer_id, body.get("issue_date") or today_iso(),
                                     body.get("valid_until") or today_iso(), body.get("status", "draft"),
                                     float(body.get("discount") or 0), body.get("notes", ""), body.get("terms", ""), qid))
        else:
            number = next_number(conn, "quote", get_company(conn).get("quote_prefix", "QUO"))
            c.execute("INSERT INTO quotes(number,customer_id,issue_date,valid_until,status,discount,notes,terms,"
                      "created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (number, customer_id, body.get("issue_date") or today_iso(),
                       body.get("valid_until") or today_iso(), body.get("status", "draft"),
                       float(body.get("discount") or 0), body.get("notes", ""), body.get("terms", ""),
                       user["id"], now_iso()))
            qid = c.lastrowid
        for it in items:
            c.execute("INSERT INTO quote_items(quote_id,product_id,description,qty,unit_price,line_total) "
                      "VALUES(?,?,?,?,?,?)",
                      (qid, it.get("product_id"), it.get("description", ""), float(it.get("qty") or 0),
                       float(it.get("unit_price") or 0), float(it.get("qty") or 0) * float(it.get("unit_price") or 0)))
        subtotal, tax, total = get_quote_totals(conn, qid)
        c.execute("UPDATE quotes SET subtotal=?,tax_amount=?,total=? WHERE id=?", (subtotal, tax, total, qid))
        log_activity(conn, user["id"], "save", "quote", qid, number)
        conn.commit()
        return self.send_json({"id": qid, "number": number}, 201)

    def _convert_quote(self, user, conn, qid):
        q = conn.execute("SELECT * FROM quotes WHERE id=?", (qid,)).fetchone()
        if not q:
            return self.send_json({"error": "Not found"}, 404)
        items = conn.execute("SELECT * FROM quote_items WHERE quote_id=?", (qid,)).fetchall()
        comp = get_company(conn)
        number = next_number(conn, "invoice", comp.get("invoice_prefix", "INV"))
        c = conn.cursor()
        c.execute("INSERT INTO invoices(number,customer_id,issue_date,due_date,status,discount,notes,terms,"
                  "created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (number, q["customer_id"], today_iso(),
                   (dt.date.today() + dt.timedelta(days=14)).isoformat(), "draft",
                   float(q["discount"]), q["notes"], q["terms"], user["id"], now_iso()))
        new_id = c.lastrowid
        for it in items:
            c.execute("INSERT INTO invoice_items(invoice_id,product_id,description,qty,unit_price,line_total) "
                      "VALUES(?,?,?,?,?,?)",
                      (new_id, it["product_id"], it["description"], float(it["qty"]),
                       float(it["unit_price"]), float(it["qty"]) * float(it["unit_price"])))
        subtotal, tax, total = get_invoice_totals(conn, new_id)
        c.execute("UPDATE invoices SET subtotal=?,tax_amount=?,total=? WHERE id=?", (subtotal, tax, total, new_id))
        c.execute("UPDATE quotes SET status='converted' WHERE id=?", (qid,))
        conn.commit()
        log_activity(conn, user["id"], "convert", "quote", qid, f"-> {number}")
        conn.commit()
        return self.send_json({"id": new_id, "number": number}, 201)

    # --- payments ---
    def api_payments(self, method, rid, sub, user, conn):
        if method == "GET":
            rows = conn.execute(
                "SELECT p.*, i.number AS invoice_number, c.name AS customer_name "
                "FROM payments p JOIN invoices i ON i.id=p.invoice_id JOIN customers c ON c.id=i.customer_id "
                "ORDER BY p.date DESC, p.id DESC").fetchall()
            return self.send_json({"payments": [dict(r) for r in rows]})
        if method == "DELETE" and rid:
            p = conn.execute("SELECT * FROM payments WHERE id=?", (rid,)).fetchone()
            if not p:
                return self.send_json({"error": "Not found"}, 404)
            inv_id = p["invoice_id"]
            conn.execute("DELETE FROM payments WHERE id=?", (rid,))
            conn.commit()
            recompute_invoice_status(conn, int(inv_id))
            conn.commit()
            return self.send_json({"ok": True})
        return self.send_json({"error": "Bad request"}, 400)

    # --- stock ---
    def api_stock(self, method, rid, sub, user, conn):
        if method == "GET":
            if rid and sub == "movements":
                rows = conn.execute(
                    "SELECT sm.*, p.name AS product_name FROM stock_movements sm "
                    "JOIN products p ON p.id=sm.product_id WHERE sm.product_id=? ORDER BY sm.id DESC LIMIT 100",
                    (rid,)).fetchall()
                return self.send_json({"movements": [dict(r) for r in rows]})
            rows = conn.execute("SELECT * FROM stock_movements ORDER BY id DESC LIMIT 200").fetchall()
            return self.send_json({"movements": [dict(r) for r in rows]})
        if method == "POST" and rid and sub == "adjust":
            # manual stock adjustment (admin)
            if not self.require_admin(user, conn):
                return
            body = self.read_body()
            change = float(body.get("change") or 0)
            reason = body.get("reason", "Manual adjustment")
            conn.execute("UPDATE products SET stock = stock + ? WHERE id=?", (change, rid))
            conn.execute("INSERT INTO stock_movements(product_id,change,reason,reference_type,reference_id,created_at) "
                         "VALUES(?,?,?,?,?,?)", (rid, change, reason, "manual", None, now_iso()))
            conn.commit()
            log_activity(conn, user["id"], "adjust", "stock", rid, f"{change:+.2f} {reason}")
            conn.commit()
            return self.send_json({"ok": True})
        return self.send_json({"error": "Bad request"}, 400)

    # --- expenses ---
    def api_expenses(self, method, rid, sub, user, conn):
        c = conn.cursor()
        if method == "GET":
            rows = c.execute("SELECT * FROM expenses ORDER BY date DESC, id DESC").fetchall()
            return self.send_json({"expenses": [dict(r) for r in rows]})
        if method == "POST":
            body = self.read_body()
            amount = float(body.get("amount") or 0)
            if amount <= 0:
                return self.send_json({"error": "Amount must be positive"}, 400)
            c.execute("INSERT INTO expenses(date,category,description,amount,created_by,created_at) "
                      "VALUES(?,?,?,?,?,?)",
                      (body.get("date") or today_iso(), body.get("category", "Other"),
                       body.get("description", ""), amount, user["id"], now_iso()))
            conn.commit()
            log_activity(conn, user["id"], "create", "expense", c.lastrowid,
                         f"{body.get('category','')} {amount}")
            conn.commit()
            return self.send_json({"id": c.lastrowid}, 201)
        if method == "PUT" and rid:
            body = self.read_body()
            amount = float(body.get("amount") or 0)
            c.execute("UPDATE expenses SET date=?,category=?,description=?,amount=? WHERE id=?",
                      (body.get("date") or today_iso(), body.get("category", "Other"),
                       body.get("description", ""), amount, rid))
            conn.commit()
            return self.send_json({"ok": True})
        if method == "DELETE" and rid:
            c.execute("DELETE FROM expenses WHERE id=?", (rid,))
            conn.commit()
            return self.send_json({"ok": True})
        return self.send_json({"error": "Bad request"}, 400)

    # --- reports ---
    def api_reports(self, method, rid, sub, user, conn):
        if method != "GET":
            return self.send_json({"error": "Bad request"}, 400)
        c = conn.cursor()
        comp = get_company(conn)
        rate = float(comp.get("vat_rate", 5))
        if rid == "dashboard":
            today = today_iso()
            month_start = today[:8] + "01"
            # totals
            def q(sql, *a):
                return float(c.execute(sql, a).fetchone()[0] or 0)
            total_invoiced = q("SELECT COALESCE(SUM(total),0) FROM invoices WHERE status NOT IN ('cancelled','draft')")
            total_paid = q("SELECT COALESCE(SUM(amount),0) FROM payments")
            outstanding = round(total_invoiced - total_paid, 2)
            sales_this_month = q(
                "SELECT COALESCE(SUM(total),0) FROM invoices WHERE issue_date >= ? AND status NOT IN ('cancelled','draft')",
                month_start)
            # counts
            open_invoices = c.execute("SELECT COUNT(*) FROM invoices WHERE status IN ('sent','partial','overdue')").fetchone()[0]
            overdue_invoices = c.execute("SELECT COUNT(*) FROM invoices WHERE status='overdue'").fetchone()[0]
            draft_invoices = c.execute("SELECT COUNT(*) FROM invoices WHERE status='draft'").fetchone()[0]
            low_stock = c.execute("SELECT COUNT(*) FROM products WHERE stock <= low_stock_threshold").fetchone()[0]
            # top customers by revenue
            top_customers = [dict(r) for r in c.execute(
                "SELECT c.name AS name, COALESCE(SUM(i.total),0) AS total "
                "FROM invoices i JOIN customers c ON c.id=i.customer_id "
                "WHERE i.status NOT IN ('cancelled','draft') GROUP BY c.id ORDER BY total DESC LIMIT 5").fetchall()]
            # monthly revenue (last 6 months)
            monthly = []
            for k in range(5, -1, -1):
                m = dt.date.today().replace(day=1) - dt.timedelta(days=1)
                m = (m.replace(day=1) - dt.timedelta(days=k * 1))
                # simpler: compute month string
                y = today[:4]; mo = int(today[5:7])
                idx = mo - k
                yy = int(y); mm = idx
                while mm < 1:
                    mm += 12; yy -= 1
                while mm > 12:
                    mm -= 12; yy += 1
                start = f"{yy:04d}-{mm:02d}-01"
                end = f"{yy:04d}-{mm:02d}-31"
                rev = q("SELECT COALESCE(SUM(total),0) FROM invoices WHERE issue_date BETWEEN ? AND ? "
                        "AND status NOT IN ('cancelled','draft')", start, end)
                monthly.append({"month": f"{yy:04d}-{mm:02d}", "revenue": round(rev, 2)})
            recent = [dict(r) for r in c.execute(
                "SELECT i.id, i.number, i.total, i.status, i.created_at, c.name AS customer "
                "FROM invoices i JOIN customers c ON c.id=i.customer_id ORDER BY i.id DESC LIMIT 8").fetchall()]
            return self.send_json({
                "total_invoiced": round(total_invoiced, 2),
                "total_paid": round(total_paid, 2),
                "outstanding": outstanding,
                "sales_this_month": round(sales_this_month, 2),
                "open_invoices": open_invoices,
                "overdue_invoices": overdue_invoices,
                "draft_invoices": draft_invoices,
                "low_stock": low_stock,
                "top_customers": top_customers,
                "monthly": monthly,
                "recent": recent,
                "currency": comp.get("currency", "AED"),
            })
        if rid == "sales":
            from_date = self.qparam("from")
            to_date = self.qparam("to")
            where = "status NOT IN ('cancelled','draft')"
            args = []
            if from_date:
                where += " AND issue_date >= ?"; args.append(from_date)
            if to_date:
                where += " AND issue_date <= ?"; args.append(to_date)
            rows = c.execute(f"SELECT * FROM invoices WHERE {where} ORDER BY issue_date DESC", args).fetchall()
            total = sum(float(r["total"]) for r in rows)
            tax_total = sum(float(r["tax_amount"]) for r in rows)
            return self.send_json({
                "invoices": [self._invoice_view(conn, r) for r in rows],
                "total": round(total, 2),
                "tax_total": round(tax_total, 2),
            })
        if rid == "vat":
            # VAT collected on sales vs paid on purchases (purchases not tracked -> just sales)
            rows = c.execute(
                "SELECT * FROM invoices WHERE status NOT IN ('cancelled','draft') ORDER BY issue_date").fetchall()
            total_tax = sum(float(r["tax_amount"]) for r in rows)
            return self.send_json({
                "vat_rate": rate,
                "sales_tax": round(total_tax, 2),
                "invoices": [{"number": r["number"], "date": r["issue_date"], "tax": r["tax_amount"],
                              "total": r["total"]} for r in rows],
            })
        if rid == "profit":
            # profit = sum( (sell - cost)*qty ) across invoiced items
            rows = c.execute(
                "SELECT ii.product_id, ii.qty, ii.unit_price, ii.description, i.number, i.issue_date "
                "FROM invoice_items ii JOIN invoices i ON i.id=ii.invoice_id "
                "WHERE i.status NOT IN ('cancelled','draft')").fetchall()
            revenue = 0.0; cost = 0.0
            detail = []
            for r in rows:
                rev = float(r["qty"]) * float(r["unit_price"])
                revenue += rev
                cst = 0.0
                if r["product_id"]:
                    p = c.execute("SELECT cost_price FROM products WHERE id=?", (r["product_id"],)).fetchone()
                    if p:
                        cst = float(p["cost_price"]) * float(r["qty"])
                cost += cst
                detail.append({"invoice": r["number"], "date": r["issue_date"], "description": r["description"],
                               "qty": r["qty"], "revenue": round(rev, 2), "cost": round(cst, 2),
                               "profit": round(rev - cst, 2)})
            return self.send_json({
                "revenue": round(revenue, 2),
                "cost": round(cost, 2),
                "profit": round(revenue - cost, 2),
                "detail": detail,
            })
        if rid == "pl":
            # Profit & Loss statement for a date range
            from_date = self.qparam("from") or "0000-01-01"
            to_date = self.qparam("to") or "9999-12-31"

            def q(sql, *a):
                return float(c.execute(sql, a).fetchone()[0] or 0)

            # Revenue = invoice totals (excl. VAT) for non-cancelled/non-draft in range
            revenue = q(
                "SELECT COALESCE(SUM(subtotal - discount),0) FROM invoices "
                "WHERE issue_date BETWEEN ? AND ? AND status NOT IN ('cancelled','draft')",
                from_date, to_date)
            # Cost of goods sold
            cogs = 0.0
            cogs_rows = c.execute(
                "SELECT ii.product_id, ii.qty FROM invoice_items ii JOIN invoices i ON i.id=ii.invoice_id "
                "WHERE i.issue_date BETWEEN ? AND ? AND i.status NOT IN ('cancelled','draft')",
                (from_date, to_date)).fetchall()
            for r in cogs_rows:
                if r["product_id"]:
                    p = c.execute("SELECT cost_price FROM products WHERE id=?", (r["product_id"],)).fetchone()
                    if p:
                        cogs += float(p["cost_price"]) * float(r["qty"])
            gross_profit = revenue - cogs
            # Expenses grouped by category
            exp_rows = c.execute(
                "SELECT category, COALESCE(SUM(amount),0) AS total, COUNT(*) AS n FROM expenses "
                "WHERE date BETWEEN ? AND ? GROUP BY category ORDER BY total DESC",
                (from_date, to_date)).fetchall()
            expenses_by_cat = [{"category": r["category"], "total": round(float(r["total"]), 2), "count": r["n"]}
                               for r in exp_rows]
            total_expenses = sum(x["total"] for x in expenses_by_cat)
            net_profit = gross_profit - total_expenses
            return self.send_json({
                "from": from_date,
                "to": to_date,
                "revenue": round(revenue, 2),
                "cogs": round(cogs, 2),
                "gross_profit": round(gross_profit, 2),
                "expenses_by_cat": expenses_by_cat,
                "total_expenses": round(total_expenses, 2),
                "net_profit": round(net_profit, 2),
                "currency": comp.get("currency", "AED"),
            })
        if rid == "statement":
            # Customer statement of account for a date range
            customer_id = self.qparam("customer_id")
            from_date = self.qparam("from") or "0000-01-01"
            to_date = self.qparam("to") or "9999-12-31"
            cust = c.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
            if not cust:
                return self.send_json({"error": "Customer not found"}, 404)
            invs_before = c.execute(
                "SELECT id, total FROM invoices WHERE customer_id=? AND issue_date < ? "
                "AND status NOT IN ('cancelled','draft')", (customer_id, from_date)).fetchall()
            opening = 0.0
            for inv in invs_before:
                opening += float(inv["total"]) - invoice_paid_amount(conn, inv["id"])
            invoices = c.execute(
                "SELECT * FROM invoices WHERE customer_id=? AND issue_date BETWEEN ? AND ? "
                "AND status NOT IN ('cancelled','draft') ORDER BY issue_date, id",
                (customer_id, from_date, to_date)).fetchall()
            payments = c.execute(
                "SELECT p.*, i.number AS inv_number FROM payments p JOIN invoices i ON i.id=p.invoice_id "
                "WHERE i.customer_id=? AND p.date BETWEEN ? AND ? ORDER BY p.date, p.id",
                (customer_id, from_date, to_date)).fetchall()
            txs = []
            for inv in invoices:
                txs.append({"date": inv["issue_date"], "type": "invoice", "ref": inv["number"],
                            "desc": "Invoice", "debit": float(inv["total"]), "credit": 0.0,
                            "status": inv["status"]})
            for p in payments:
                ref = (p["reference"] + " (" + p["inv_number"] + ")") if p["reference"] else p["inv_number"]
                txs.append({"date": p["date"], "type": "payment", "ref": ref,
                            "desc": "Payment (" + str(p["method"]).replace("_", " ") + ")",
                            "debit": 0.0, "credit": float(p["amount"]), "status": ""})
            txs.sort(key=lambda t: (t["date"], 0 if t["type"] == "invoice" else 1))
            balance = opening
            for t in txs:
                balance += t["debit"] - t["credit"]
                t["balance"] = round(balance, 2)
            closing = round(balance, 2)
            return self.send_json({
                "customer": dict(cust),
                "from": from_date,
                "to": to_date,
                "opening_balance": round(opening, 2),
                "closing_balance": closing,
                "transactions": txs,
                "currency": comp.get("currency", "AED"),
            })
        return self.send_json({"error": "Not found"}, 404)

    def qparam(self, name):
        q = parse_qs(urlparse(self.path).query)
        return q.get(name, [None])[0]

    # --- settings ---
    def api_settings(self, method, rid, sub, user, conn):
        if method == "GET":
            return self.send_json({"company": get_company(conn)})
        if method == "PUT":
            if not self.require_admin(user, conn):
                return
            body = self.read_body()
            c = conn.cursor()
            c.execute("UPDATE company SET name=?,tagline=?,legal_name=?,trn=?,address=?,phone=?,email=?,vat_rate=?,currency=?,"
                      "invoice_prefix=?,quote_prefix=?,payment_terms=?,invoice_notes=? WHERE id=1",
                      (body.get("name", ""), body.get("tagline", ""), body.get("legal_name", ""), body.get("trn", ""),
                       body.get("address", ""), body.get("phone", ""), body.get("email", ""),
                       float(body.get("vat_rate") or 0), body.get("currency", "AED"),
                       body.get("invoice_prefix", "INV"), body.get("quote_prefix", "QUO"),
                       body.get("payment_terms", ""), body.get("invoice_notes", "")))
            conn.commit()
            log_activity(conn, user["id"], "update", "settings", 1, "")
            conn.commit()
            return self.send_json({"ok": True})
        return self.send_json({"error": "Bad request"}, 400)

    # --- users (admin) ---
    def api_users(self, method, rid, sub, user, conn):
        if not self.require_admin(user, conn):
            return
        c = conn.cursor()
        if method == "GET":
            rows = c.execute("SELECT id,name,email,role,active,created_at FROM users ORDER BY id").fetchall()
            return self.send_json({"users": [dict(r) for r in rows]})
        if method == "POST":
            body = self.read_body()
            email = (body.get("email") or "").strip().lower()
            if not email or not (body.get("password") or ""):
                return self.send_json({"error": "Email and password required"}, 400)
            exists = c.execute("SELECT id FROM users WHERE lower(email)=?", (email,)).fetchone()
            if exists:
                return self.send_json({"error": "Email already in use"}, 400)
            c.execute("INSERT INTO users(name,email,password_hash,role,created_at) VALUES(?,?,?,?,?)",
                      (body.get("name", ""), email, hash_password(body["password"]),
                       body.get("role", "staff"), now_iso()))
            conn.commit()
            return self.send_json({"id": c.lastrowid}, 201)
        if method == "PUT" and rid:
            body = self.read_body()
            if int(rid) == user["id"] and body.get("role") != user["role"]:
                return self.send_json({"error": "You cannot change your own role"}, 400)
            c.execute("UPDATE users SET name=?,role=?,active=? WHERE id=?",
                      (body.get("name", ""), body.get("role", "staff"), 1 if body.get("active", True) else 0, rid))
            if body.get("password"):
                c.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(body["password"]), rid))
            conn.commit()
            return self.send_json({"ok": True})
        if method == "DELETE" and rid:
            if int(rid) == user["id"]:
                return self.send_json({"error": "You cannot delete yourself"}, 400)
            c.execute("DELETE FROM users WHERE id=?", (rid,))
            conn.commit()
            return self.send_json({"ok": True})
        return self.send_json({"error": "Bad request"}, 400)

    def log_message(self, fmt, *args):
        pass  # silence default request logging


def main():
    init_db()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"QuickInvoice running on http://0.0.0.0:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
