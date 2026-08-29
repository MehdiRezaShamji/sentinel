# Sentinel — Environmental Safety Agent

Sentinel is a real-time autonomous environmental safety agent designed to monitor field workers under hazardous heat conditions, detect elevated risk levels, coordinate safety check-ins and buddy verifications via **Telegram**, escalate incidents to supervisors, and simulate emergency responses.

---

## The Problem
Field workers (e.g. road maintenance crews, inspection teams) are frequently exposed to high environmental heat. Heat stress can quickly become life-threatening if unnoticed or untreated. Traditional check-in systems rely on manual reporting or supervisors constantly monitoring temperatures, which is prone to oversight.

---

## The Solution
Sentinel automates the entire safety monitoring process using a deterministic, event-driven state machine combined with localized high-fidelity weather metrics:
1. **Local monitoring loop** constantly evaluates worker exposure times and local heat indexes.
2. **Elevated risk detection** automatically triggers a worker check-in via Telegram.
3. **Escalation path** alerts a designated "buddy" if the worker is unresponsive, then alerts the supervisor and creates a safety incident if the buddy confirms a hazard.
4. **LLM Reasoning** acts as an exception-handling and complex decision-making layer rather than a primary monitoring loop.

---

## Architecture

```
                      START
                        ↓
               FortyGuard refresh
                        ↓
                cached environment
                        ↓
               LOCAL MONITOR LOOP
                   every 10 sec
                        ↓
                worker evaluation
                        ↓
                    High-risk?
                   /         \
                 NO           YES
                 |             ↓
                 |        ONE check-in
                 |             ↓
                 |        wait (timeout)
                 |             ↓
                 |        worker SAFE?
                 |          /       \
                 |        YES        NO / NOT SAFE
                 |         |          ↓
                 |         |      notify buddy
                 |         |          ↓
                 |         |       SAFE / NOT SAFE
                 |         |        /         \
                 |         |      SAFE       NOT SAFE
                 |         |       |            ↓
                 |         |    resolve      supervisor
                 |         |                    ↓
                 |         |                 incident
                 |         |                    ↓
                 |         |                 escalation
```

**Key components**
- **Backend** (`backend/`): FastAPI + a deterministic local monitoring loop (thread-based). SQLite (`backend/app/sentinel.db`, auto-created and seeded on first run) persists workers and their discovered Telegram chat IDs. Telegram uses outbound-only long polling (`getUpdates`) — no webhook or public inbound access required.
- **Frontend** (`frontend/`): React + Vite dashboard for start/stop/reset monitoring, worker state, incidents, and the live agent activity log.
- **Environmental data**: FortyGuard REST API, refreshed asynchronously every 4 hours by default.

---

## Cost Optimization & Efficiency
* **FortyGuard Refresh**: Fetched once on startup and cached. Periodic refreshes run in a separate thread only every 4 hours (`FORTYGUARD_REFRESH_SECONDS=14400`), keeping API calls to a minimum.
* **LLM Calls**: Groq is **not** called by the monitoring loop. Check-ins, timeout timers, and buddy verification routing are fully handled by the deterministic state machine (0 LLM calls). Groq and LangGraph are reserved for explicit agent reasoning runs.

---

## Technologies Used
- **Backend**: Python, FastAPI, LangGraph, LangChain, Groq, SQLite, requests, python-dotenv.
- **Environmental Data**: FortyGuard REST API.
- **Communications**: Telegram Bot API (with simulated `[DEMO TELEGRAM]` fallback for fake demo phone numbers).
- **Frontend**: React, Vite, Custom CSS.

---

## Environment Variables
Copy `.env.example` to `backend/.env` and fill in real values (never commit `.env`):

| Variable | Required | Purpose |
|---|---|---|
| `FORTYGUARD_API_KEY` | Yes | Environmental intelligence API |
| `GROQ_API_KEY` | Yes | LLM reasoning layer |
| `TELEGRAM_BOT_TOKEN` | Yes | Worker check-ins via Telegram |
| `DEMO_MODE` | Demo | `true` → 20s check-in timeout, 1s poll interval |
| `CHECKIN_TIMEOUT_SECONDS` | No | Production check-in timeout (default 300) |
| `SUPERVISOR_PHONE` | No | Supervisor destination (default simulated `+15550000999`) |
| `FORTYGUARD_REFRESH_SECONDS` | No | Environment refresh interval (default 14400) |
| `ALLOWED_ORIGIN_REGEX` | Deploy | CORS regex allowing the deployed frontend origin |
| `VITE_API_URL` | Deploy | Frontend build-time backend URL, e.g. `https://<backend>.onrender.com/api` |

If `TELEGRAM_BOT_TOKEN` is omitted, Sentinel logs intended messages as `[DEMO TELEGRAM]` instead of calling the Telegram API.

---

## Getting Started

### 1. Backend Setup
1. Open a terminal in `backend/`.
2. Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Copy `.env.example` to `.env` and fill in API keys.
5. Start the FastAPI server:
   ```bash
   uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
   ```

### 2. Frontend Setup
1. Open a terminal in `frontend/`.
2. Install Node packages and start the dev server:
   ```bash
   npm install
   npm run dev
   ```
3. Open your browser to `http://localhost:5173/`.

### 3. Tests
Run the unit/integration test suite from `backend/`:
```bash
.venv/Scripts/python -m unittest discover -s tests -v
```
(`tests/test_live_api.py` additionally requires a running server.)

---

## Demo Flow
1. Start the backend in `DEMO_MODE=true` and open the frontend.
2. In Telegram, send `/start` to your bot **once** — Sentinel discovers your chat ID, routes the live worker's (Alex, W001) check-ins to you, and persists it in SQLite so it survives restarts.
3. Press **Start Monitoring**. Workers accumulate exposure; once the heat index and exposure thresholds are met, they go high-risk and receive check-ins.
4. Alex receives a **real Telegram** message — reply `SAFE` (confirmed working) or `NOT SAFE` (incident created → supervisor notified).
5. Jordan (`+15550000002`) and Sam (`+15550000003`) are simulated actors: their check-ins/buddy alerts appear as `[DEMO TELEGRAM]` lines in the server log and activity feed.
6. A 20-second (demo) check-in timeout marks the worker unresponsive and alerts their buddy.
7. Optionally toggle **Emergency Response** in the UI to see simulated emergency dispatch log entries.

---

## Deployment (Render)

The repo includes a [`render.yaml`](render.yaml) blueprint defining both services.

1. Push this repository to GitHub.
2. In [Render](https://dashboard.render.com): **New → Blueprint**, select the repo.
3. When prompted, set:
   - Backend: `FORTYGUARD_API_KEY`, `GROQ_API_KEY`, `TELEGRAM_BOT_TOKEN`, `ALLOWED_ORIGIN_REGEX` (e.g. `^https://sentinel-frontend\.onrender\.com$`)
   - Frontend: `VITE_API_URL` (e.g. `https://sentinel-backend.onrender.com/api`) — must be set **before** the frontend build runs.
4. Deploy both services. The backend starts with `uvicorn app.main:app --host 0.0.0.0 --port $PORT` and serves the Telegram polling loop.

---

## Limitations
> [!IMPORTANT]
> - **Demo/Simulated actors**: Jordan and Sam are simulated Telegram actors (fake `+1555…` numbers logged as `[DEMO TELEGRAM]`). Only the live worker who sends `/start` receives real Telegram messages.
> - **SQLite**: not suited to multi-instance production deployments. On Render's free tier the disk is ephemeral — the database re-seeds with default demo workers on every restart/deploy, and the discovered Telegram chat ID must be re-learned by sending `/start` again (or use a paid instance with a persistent disk).
> - **Telegram polling**: long polling is outbound-only and works behind Render's proxy, but one backend instance must own the polling loop; do not scale the backend to multiple instances.
> - **Emergency response** is fully simulated — `[EMERGENCY DEMO]` log entries only. **No real emergency services are ever contacted.**
