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
import datetime as dt
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "quickinvoice.db")
STATIC_DIR = os.path.join(BASE_DIR, "static")
PORT = int(os.environ.get("PORT", 8000))

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
        admin_hash = hash_password("admin123")
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
        filepath = os.path.normpath(os.path.join(STATIC_DIR, path.lstrip("/")))
        if not filepath.startswith(STATIC_DIR):
            return self.send_json({"error": "Forbidden"}, 403)
        if not os.path.isfile(filepath):
            return self.send_json({"error": "Not found"}, 404)
        ext = os.path.splitext(filepath)[1].lower()
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".ico": "image/x-icon",
        }.get(ext, "application/octet-stream")
        with open(filepath, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
