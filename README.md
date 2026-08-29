# Sentinel — Environmental Safety Agent

Sentinel is an AI-powered environmental safety agent for heat-exposed field workers. It continuously evaluates the conditions a crew is working in, and when those conditions become dangerous, it does not just raise a warning — it actively asks each worker whether they are safe, verifies with their buddy when they can't answer, and escalates to a supervisor with a documented incident when something is wrong.

Heat illness is not a slow, forgiving problem. It can progress rapidly from heat exhaustion to heat stroke, which is a medical emergency. In hazardous heat, waiting for someone to notice that a worker has stopped responding can mean losing the window in which the outcome was still preventable. Sentinel exists to close that gap: the system checks, so people don't have to be checked on by chance.

---

## Why This Problem Matters

Outdoor and field workers — road crews, inspection teams, maintenance staff — perform physically demanding work in conditions that can quietly become dangerous. The risk is not a single number on a thermometer:

- **Risk is a combination.** Risk depends on both environmental conditions and exposure duration; conditions that may be tolerable for a short task can become hazardous during prolonged exposure. A temperature reading alone is insufficient.
- **The dangerous failure is not detecting heat — it is not knowing whether the worker is okay.** Sensors and weather APIs can measure the environment all day, but they cannot tell you that a specific human on a specific roadside is still responsive and safe.
- **Traditional monitoring depends on humans noticing in time.** Manual check-ins rely on a supervisor remembering, on a coworker glancing over, on someone speaking up. Each of those is a single point of failure precisely when everyone on site is under the same physiological stress.

Sentinel was designed around that last mile: turning environmental intelligence into an active, auditable human-response loop.

---

## From Environmental Risk to Human Response

Sentinel implements a complete response chain, and every step of it is recorded in an activity log:

```
environmental intelligence (FortyGuard)
        ↓
risk detection (heat index + exposure duration)
        ↓
worker check-in ("Are you safe? Reply SAFE or NOT SAFE")
        ↓
   SAFE ──→ worker returns to working status
        ↓
   NOT SAFE ──→ incident created ──→ supervisor escalation
        ↓
   no response ──→ buddy verification ("Please check on Alex")
        ↓
   buddy: SAFE ──→ resolved | NOT SAFE ──→ incident + supervisor
        ↓
incident record ──→ optional simulated emergency response
```

Nothing in that chain waits for someone to look at a dashboard. The monitor notices, the message goes out, and if the worker cannot answer, the system goes and asks someone else — then it writes down what happened.

---

## Why Sentinel Is Not Just an LLM

Safety-critical systems need behavior you can predict, audit, and reason about. That is why Sentinel's monitoring, check-in, timeout, and escalation path is **fully deterministic** — a fixed state machine with explicit transitions:

- **Predictable:** the same conditions always produce the same transitions. A check-in is sent once; a timeout fires exactly when configured; a buddy is asked once. There is no probabilistic path between "worker at risk" and "worker asked."
- **Auditable:** every transition is appended to an activity log the supervisor can read after the fact — who was checked, when, what was answered, what was escalated.
- **Cheap and fast:** the local monitoring loop makes zero LLM calls and zero environmental API calls per cycle. FortyGuard data is fetched once on startup and refreshed asynchronously every 4 hours by default.

LangGraph with Groq is part of the system — but as an **agent reasoning layer for exceptions and complex decision support**, not as the timer or the safety-state authority. The state machine is the source of truth for worker safety status; the LLM never decides whether a check-in happens or whether an incident is created.

---

## Research-Driven Design

Sentinel's thresholds and response flow were chosen after researching occupational heat stress rather than invented: how heat index and apparent temperature relate to actual physiological strain, why exposure duration matters as much as conditions, how worker check-in and buddy-verification procedures are used in the field, what escalation paths look like when a worker is unresponsive, and the limitations of relying on manual observation alone.

Authoritative references that informed this design:

- [OSHA — Occupational Heat Exposure](https://www.osha.gov/heat-exposure): heat index risk levels, symptoms of heat exhaustion and heat stroke, and the emphasis on acclimatization and work/rest cycles.
- [CDC/NIOSH — Criteria for a Recommended Standard: Occupational Exposure to Heat and Hot Environments](https://www.cdc.gov/niosh/docs/2016-106/): exposure duration, physiological monitoring, and the recommendation of systematic surveillance of workers in hot environments.
- [CDC — Heat Stress](https://www.cdc.gov/niosh/topics/heatstress/): heat-related illness progression and workplace response guidance.

---

## See Sentinel in Action

The demo ships with three workers and a simulated heat scenario:

1. **Hazardous environment detected.** Monitoring starts; the heat index and each worker's accumulated exposure cross the risk thresholds. Alex (W001) and Sam (W003) go high-risk.
2. **Alex receives a real Telegram check-in.** *"Sentinel safety check-in: Are you safe? Reply SAFE or NOT SAFE."* This is a real message to a real Telegram chat — the demo operator's phone.
3. **Reply `SAFE`** → Alex returns to working status, check-in confirmed, logged.
4. **Reply `NOT SAFE`** → an incident is created and immediately escalated to the supervisor.
5. **No response** → after the check-in timeout (20 seconds in demo mode; 5 minutes in production), Sentinel marks Alex unresponsive and asks his buddy Jordan to verify: *"Reply SAFE or NOT SAFE."* A timeout for Sam alerts Alex instead — the chain always has a next step.
6. **Emergency response** can be toggled in the UI to demonstrate the final escalation stage. It is logged as `[EMERGENCY DEMO]` — it is a simulation, and it says so in the log.

---

## Demo vs Production Timing

The hackathon demo compresses every timer so the complete workflow can be demonstrated in minutes. These demo values are **not** the intended real-world response windows:

| Timer | Demo (`DEMO_MODE=true`) | Production / default |
|---|---|---|
| Monitoring poll interval | 1 second | 10 seconds |
| Check-in response timeout | 20 seconds | 5 minutes (300 s, `CHECKIN_TIMEOUT_SECONDS`) |
| Environment refresh | configurable (`FORTYGUARD_REFRESH_SECONDS`, default 4 h) | same |

The 20-second demo timeout exists only so judges can watch a full check-in → timeout → buddy-verification cycle live. In production, a worker is given a substantially longer response window, and monitoring/check-in cadence slows accordingly.

---

## Risk Levels & Periodic Check-ins (as implemented)

Sentinel's current implementation uses a **single high-risk intervention trigger**, evaluated on every monitoring cycle: a worker becomes high-risk when the heat index is at or above **35 °C** *and* their accumulated exposure is at or above **45 minutes** (both are explicit constants in the code). There are **no separate automated Low/Medium risk levels** with distinct actions — conditions and exposure duration jointly determine whether intervention is required, and below that threshold the monitor simply keeps watching. This is an intentional starting point for a deterministic safety path, not a complete risk-grading system.

A key clarification on check-in recurrence — the response timeout is **not** a contact frequency:

- The 20-second demo / 5-minute production value is the **response timeout**: how long Sentinel waits for a worker to answer a check-in that was already sent. It is **not** the frequency at which workers are contacted — Sentinel does **not** send a check-in every 20 seconds or every 5 minutes.
- A check-in is triggered when a worker **enters a high-risk episode** (the trigger above).
- If the worker replies SAFE, that confirms their current safety state.
- While the same high-risk episode continues, there is currently **no fixed recurring re-check interval** (e.g. no 45-minute recurring check-in) implemented.
- If conditions fall below the high-risk threshold and later become high-risk again, Sentinel can initiate a fresh check-in for the new high-risk episode.
- A fixed periodic re-check cadence is a **future enhancement**, not current functionality.

---

## What Is Real vs Simulated?

| Real | Simulated |
|---|---|
| FortyGuard environmental data (real API) | Jordan & Sam as demo actors (fake `+1555…` numbers, `[DEMO TELEGRAM]` log lines) |
| Telegram communication (real bot, real messages, real replies) | Emergency dispatch (log-only, never contacts real services) |
| Monitoring loop & all state transitions | Demo timing values (20s check-in timeout, 1s poll interval in `DEMO_MODE`) |
| Incident creation & supervisor escalation logic | |

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
        1 sec demo / 10 sec production monitoring poll
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

## Technologies Used
- **Backend**: Python, FastAPI, LangGraph, LangChain, Groq, SQLite, requests, python-dotenv.
- **Environmental Data**: FortyGuard REST API.
- **Communications**: Telegram Bot API (with simulated `[DEMO TELEGRAM]` fallback for fake demo phone numbers).
- **Frontend**: React, Vite, Custom CSS.

---

## Cost Optimization & Efficiency
* **FortyGuard Refresh**: Fetched once on startup and cached. Periodic refreshes run in a separate thread only every 4 hours (`FORTYGUARD_REFRESH_SECONDS=14400`), keeping API calls to a minimum.
* **LLM Calls**: Groq is **not** called on any monitoring cycle (1 s demo / 10 s production). Check-ins, timeout timers, and buddy verification routing are fully handled by the deterministic state machine (0 LLM calls). Groq and LangGraph are reserved for explicit agent reasoning runs.

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
> - **Re-check cadence**: workers who remain continuously in high-risk exposure are not re-prompted on a fixed interval; a fresh check-in is triggered when the risk condition clears and re-occurs (see "Risk Levels & Periodic Check-ins" above).
> - **Emergency response** is fully simulated — `[EMERGENCY DEMO]` log entries only. **No real emergency services are ever contacted.**
> - **Scope**: Sentinel is a demonstration of an automated check-in and escalation workflow. It does not replace workplace heat-safety programs, medical monitoring, or emergency services, and it cannot guarantee a worker's safety.

---

Sentinel is designed around a simple principle: when environmental conditions become dangerous, the system should not merely display a warning — it should actively establish whether the human is safe, and escalate when it cannot.
