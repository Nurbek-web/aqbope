# Aqbobek — Smart Education Suite

A lyceum portal with multi-role dashboards (student, teacher, parent, admin), AI-powered reports, real-time WebSocket notifications, and a hall kiosk display.

## Stack

- **Backend** — Python 3.11+, FastAPI, Uvicorn
- **Frontend** — Vanilla HTML/CSS/JS (no build step)
- **AI** — OpenAI API (optional, for weekly digests and risk analysis)

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Set environment variables (optional)

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | _(empty)_ | OpenAI key for AI summaries |
| `OPENAI_MODEL` | `gpt-4o-mini` | Model used for AI reports |
| `OPENAI_API_URL` | OpenAI default | Override for a custom endpoint |
| `BILIMCLASS_URL` | _(empty)_ | BilimClass integration URL |
| `BILIMCLASS_TOKEN` | _(empty)_ | BilimClass auth token |
| `APP_SECRET` | `aqbobek-dev-secret` | JWT signing secret — **change in production** |
| `TOKEN_TTL_MIN` | `240` | Token lifetime in minutes |

```bash
export OPENAI_API_KEY=sk-...
export APP_SECRET=your-production-secret
```

### 3. Start the API server

```bash
uvicorn app:app --reload --port 8000
```

API is now available at `http://localhost:8000`.  
Interactive docs: `http://localhost:8000/docs`

### 4. Open the frontend

Open `index.html` directly in a browser — no web server required:

```bash
open index.html        # macOS
xdg-open index.html    # Linux
```

Or serve it with any static server if you prefer:

```bash
python -m http.server 3000
# then open http://localhost:3000
```

---

## Demo Accounts

All demo accounts use the password **`demo123`**.

| Email | Role |
|---|---|
| `aruzhan.student@aqbobek.edu.kz` | Student (high performer) |
| `maksat.student@aqbobek.edu.kz` | Student (at-risk) |
| `aigerim.student@aqbobek.edu.kz` | Student (needs support) |
| `nurlan.teacher@aqbobek.edu.kz` | Teacher (Physics & Math) |
| `dana.teacher@aqbobek.edu.kz` | Teacher (History) |
| `parent.aruzhan@gmail.com` | Parent |
| `admin@aqbobek.edu.kz` | Admin |

---

## Pages

| File | Purpose |
|---|---|
| `index.html` | Main portal — login + all role dashboards |
| `kiosk.html` | Hall display for screen/TV (auto-rotating, no login) |
| `aqbobek_presentation.html` | Project presentation slides |

---

## Project Structure

```
aqbope/
├── app.py                    # FastAPI backend (API + in-memory DB)
├── app.js                    # Frontend JS (role renderers, API calls)
├── index.html                # Main portal UI
├── kiosk.html                # Hall kiosk display
├── aqbobek_presentation.html # Presentation
├── styles.css                # Shared styles
└── requirements.txt          # Python dependencies
```

---

## Notes

- Data is stored **in-memory** — restarting the server resets all state.
- The AI features (weekly digest, risk score) require a valid `OPENAI_API_KEY`. Without it the endpoints return placeholder responses.
- The kiosk page connects to the backend WebSocket at the same host; update the `API` constant in `kiosk.html` if running on a different host/port.
