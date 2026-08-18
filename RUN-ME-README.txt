# QuickInvoice — Run it on your own computer

This folder contains your complete invoicing, quotations, stock, expenses and
Profit & Loss software. It needs **only Python 3** — no other setup, no
database server, no internet required.

---

## 1. Install Python (one time, ~2 minutes)

1. Go to **https://www.python.org/downloads/**
2. Click the big **"Download Python"** button.
3. Run the installer.
4. **IMPORTANT:** tick the checkbox **"Add Python to PATH"** at the bottom of
   the installer window, then click **Install Now**.

## 2. Start the software

- **Windows:** double-click **`START-WINDOWS.bat`**
- **Mac / Linux:** open Terminal in this folder and run:
  ```
  chmod +x START-MAC-LINUX.sh
  ./START-MAC-LINUX.sh
  ```
  (or simply: `python3 server.py`)

A black window will open showing `QuickInvoice running on http://0.0.0.0:8000`.
**Keep that window open** — it is the server.

## 3. Open the software

Open your web browser (Chrome, Edge, Safari…) and go to:

```
http://localhost:8000
```

## 4. Sign in

| Field    | Value                   |
|----------|-------------------------|
| Email    | admin@quickinvoice.com  |
| Password | Miraj@2026              |

> Change this password after first login (Settings → Users → Edit).

---

## Put it online (access from anywhere)

Right now this runs on your computer only. To use it from your phone or from
another location, you have these options:

### Option A — Keep your computer on + free Cloudflare Tunnel (easiest, free)
1. Create a free account at https://dash.cloudflare.com
2. Install `cloudflared` and run:
   ```
   cloudflared tunnel --url http://localhost:8000
   ```
3. It prints a public web address like `https://xxxx.trycloudflare.com`
   — open that on your phone from anywhere.

### Option B — Free cloud hosting (always on, no computer needed)
Upload this whole folder to **Render** (https://render.com, free tier):
1. Create account → **New +** → **Web Service** → connect this folder.
2. Build command: *(leave empty)*
3. Start command: `python3 server.py`
4. Add a **Persistent Disk** (so the database `quickinvoice.db` is saved).
5. Open the generated `https://xxx.onrender.com` URL — done.

### Option C — Cheap VPS
Rent a small VPS (DigitalOcean, Hetzner, AWS Lightsail — ~$5/month) and run:
```
nohup python3 server.py &
```

---

## Backing up your data

**Everything is stored in one file: `quickinvoice.db`.**

Copy that file anywhere (USB, Google Drive, email) to back up your whole
business data. To restore, put the file back in this folder.

---

## Files in this folder

| File                 | Purpose                              |
|----------------------|--------------------------------------|
| `server.py`          | The whole backend (no dependencies)  |
| `static/`            | Web interface (HTML, CSS, JS)        |
| `quickinvoice.db`    | Your database (created automatically)|
| `START-WINDOWS.bat`  | One-click start for Windows          |
| `START-MAC-LINUX.sh` | One-click start for Mac/Linux        |
