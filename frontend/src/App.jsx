import { useEffect, useState } from "react";
import "./index.css";

const API = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000/api";

function App() {
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [monitoring, setMonitoring] = useState(false);
  const [emergencyResponse, setEmergencyResponse] = useState(false);
  const [nowTime, setNowTime] = useState(Date.now());

  useEffect(() => {
    const timer = setInterval(() => {
      setNowTime(Date.now());
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  async function toggleEmergencyResponse(val) {
    try {
      const response = await fetch(
        `${API}/monitor/emergency`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ enabled: val }),
        }
      );
      if (response.ok) {
        setEmergencyResponse(val);
      }
    } catch (err) {
      console.error("Failed to toggle emergency response:", err);
    }
  }

  async function fetchCurrentStatus() {
    try {
      const response = await fetch(`${API}/monitor/status`);
      if (!response.ok) return;
      const data = await response.json();
      if (data.state) {
        setResult({
          status: "success",
          current_step: data.state.current_step,
          environment: data.state.environment || {},
          workers: data.state.workers || [],
          incidents: data.state.incidents || [],
          agent_actions: data.state.agent_actions || [],
          emergency_response_enabled: data.state.emergency_response_enabled || false
        });
        setEmergencyResponse(data.state.emergency_response_enabled || false);
      }
    } catch (err) {
      console.error("Status update failed:", err);
    }
  }

  async function resetScenario() {
    if (loading) return;
    setLoading(true);
    setError(null);
    try {
      await fetch(
        `${API}/demo/reset`,
        {
          method: "POST",
        }
      );
      setMonitoring(false);
      await fetchCurrentStatus();
    } catch (err) {
      console.error("Failed to reset scenario:", err);
    } finally {
      setLoading(false);
    }
  }

  async function startMonitoring() {
    if (loading) return;
    setLoading(true);
    setError(null);

    try {
      const response = await fetch(
        `${API}/monitor/start`,
        {
          method: "POST",
        }
      );

      if (!response.ok) {
        throw new Error(
          "Failed to start monitoring."
        );
      }

      setMonitoring(true);
      await fetchCurrentStatus();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function stopMonitoring() {
    if (loading) return;
    setLoading(true);
    try {
      await fetch(
        `${API}/monitor/stop`,
        {
          method: "POST",
        }
      );
      setMonitoring(false);
      await fetchCurrentStatus();
    } catch (err) {
      console.error("Failed to stop monitoring:", err);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!monitoring) {
      return;
    }

    let cancelled = false;

    async function poll() {
      if (!cancelled) {
        await fetchCurrentStatus();
      }
    }

    poll();

    const interval =
      setInterval(
        poll,
        500
      );

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [monitoring]);

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">
            S
          </div>

          <div>
            <div className="brand-name">
              Sentinel
            </div>

            <div className="brand-subtitle">
              Environmental Safety Agent
            </div>
          </div>
        </div>

        <div className="system-status">
          <span className="status-dot" />

          <span>
            {monitoring
              ? "Monitoring active"
              : "Agent online"}
          </span>
        </div>
      </header>

      <main className="main-content">
        <section className="hero">
          <div className="hero-eyebrow">
            AUTONOMOUS ENVIRONMENTAL SAFETY
          </div>

          <h1>
            Your safety workforce,
            <span>
              {" "}
              always watching.
            </span>
          </h1>

          <p>
            Sentinel continuously observes
            environmental conditions, monitors
            field workers, and executes
            safety-response workflows when
            action is required.
          </p>

          <div className="hero-actions" style={{ display: "flex", gap: "15px", flexWrap: "wrap", alignItems: "center", marginTop: "26px" }}>
            <button
              className="analyze-button"
              onClick={
                monitoring
                  ? stopMonitoring
                  : startMonitoring
              }
              disabled={loading}
              style={{ width: "auto", flexGrow: 0, marginTop: 0 }}
            >
              <span>
                {loading
                  ? "Starting Sentinel..."
                  : monitoring
                    ? "Stop monitoring"
                    : "Start Sentinel monitoring"}
              </span>

              <span className="button-arrow" style={{ marginLeft: "10px" }}>
                {loading
                  ? "…"
                  : monitoring
                    ? "×"
                    : "→"}
              </span>
            </button>

            {monitoring && (
              <button
                className="analyze-button"
                onClick={resetScenario}
                disabled={loading}
                style={{ width: "auto", background: "#f3ece3", color: "#6f6861", border: "1px solid #e2d5c5", boxShadow: "none", marginTop: 0 }}
              >
                <span>Reset Scenario</span>
              </button>
            )}

            <div className="emergency-control" style={{ display: "flex", alignItems: "center", gap: "10px", marginLeft: "auto", padding: "10px 15px", background: "white", borderRadius: "11px", border: "1px solid #e7ddd1" }}>
              <span style={{ fontSize: "13px", fontWeight: "700", color: "#403a35" }}>EMERGENCY RESPONSE:</span>
              <button 
                onClick={() => toggleEmergencyResponse(!emergencyResponse)}
                disabled={loading}
                style={{
                  padding: "6px 12px",
                  borderRadius: "6px",
                  border: "none",
                  fontWeight: "bold",
                  fontSize: "12px",
                  background: emergencyResponse ? "#e85d2a" : "#eee6dd",
                  color: emergencyResponse ? "white" : "#6f6861",
                  transition: "background 0.2s"
                }}
              >
                {emergencyResponse ? "ON" : "OFF"}
              </button>
            </div>
          </div>
        </section>

        {error && (
          <div className="error-state">
            <strong>
              Agent unavailable
            </strong>

            <p>{error}</p>
          </div>
        )}

        {loading && (
          <section className="workspace">
            <div className="overview-card agent-running">
              <div className="loading-ring" />

              <h2>
                Agent is working
              </h2>

              <p>
                Observing environmental
                conditions and evaluating
                worker safety.
              </p>
            </div>
          </section>
        )}

        {result && !loading && (
          <>
            <section className="workspace">
              <div className="overview-card">
                <div className="section-heading">
                  <div>
                    <span className="section-kicker">
                      01
                    </span>

                    <h2>
                      Environment
                    </h2>
                  </div>

                  <span className="card-label">
                    FORTYGUARD
                  </span>
                </div>

                <div className="result-summary">
                  <div>
                    <span>
                      TEMPERATURE
                    </span>

                    <strong>
                      {result.environment
                        .temperature_c ??
                        "—"}
                      °C
                    </strong>
                  </div>

                  <div>
                    <span>
                      HEAT INDEX
                    </span>

                    <strong>
                      {result.environment
                        .heat_index_c ??
                        "—"}
                      °C
                    </strong>
                  </div>

                  <div>
                    <span>
                      WET BULB
                    </span>

                    <strong>
                      {result.environment
                        .wet_bulb_c ??
                        "—"}
                      °C
                    </strong>
                  </div>

                  <div>
                    <span>
                      HUMIDITY
                    </span>

                    <strong>
                      {result.environment
                        .humidity_percent ??
                        "—"}
                      %
                    </strong>
                  </div>
                </div>
              </div>

              <div className="overview-card">
                <div className="section-heading">
                  <div>
                    <span className="section-kicker">
                      02
                    </span>

                    <h2>
                      Field workforce
                    </h2>
                  </div>

                  <span className="card-label">
                    {result.workers.length}{" "}
                    WORKERS
                  </span>
                </div>

                <div className="ranking">
                  {result.workers.map(
                    (worker) => {
                      let countdownText = "";
                      if (worker.check_in_status === "pending" && worker.check_in_sent_at) {
                        const sentTime = new Date(worker.check_in_sent_at).getTime();
                        const elapsed = Math.floor((nowTime - sentTime) / 1000);
                        const timeout = worker.check_in_timeout_seconds || 300;
                        const remaining = timeout - elapsed;
                        if (remaining > 0) {
                          const minutes = Math.floor(remaining / 60);
                          const seconds = remaining % 60;
                          countdownText = ` (${minutes}:${seconds < 10 ? "0" : ""}${seconds} left)`;
                        } else {
                          countdownText = " (Timing out...)";
                        }
                      }

                      return (
                        <div
                          className="ranking-row"
                          key={worker.id}
                        >
                          <div className="rank-number">
                            {worker.id}
                          </div>

                          <div className="rank-info">
                            <div className="rank-title">
                              <span>
                                {worker.name}
                                {countdownText && (
                                  <span style={{ color: "#d97706", fontWeight: "normal", fontSize: "12px", marginLeft: "8px" }}>
                                    {countdownText}
                                  </span>
                                )}
                                {worker.buddy_verification_status === "pending" && (
                                  <span style={{ color: "#dc2626", fontWeight: "normal", fontSize: "12px", marginLeft: "8px" }}>
                                    (Buddy check pending)
                                  </span>
                                )}
                              </span>

                              <strong>
                                {worker.status.replaceAll(
                                  "_",
                                  " "
                                )}
                              </strong>
                            </div>

                            <small>
                              {worker.task} ·{" "}
                              {
                                worker.exposure_minutes
                              }{" "}
                              min exposure
                            </small>
                          </div>
                        </div>
                      );
                    }
                  )}
                </div>
              </div>
            </section>

            <section className="overview-card agent-log">
              <div className="section-heading">
                <div>
                  <span className="section-kicker">
                    03
                  </span>

                  <h2>
                    Agent activity
                  </h2>
                </div>

                <span className="card-label">
                  LIVE LOG
                </span>
              </div>

              <div className="activity-list">
                {result.agent_actions.map(
                  (action, index) => (
                    <div
                      className="activity-row"
                      key={`${action}-${index}`}
                    >
                      <span className="activity-dot" />

                      <span>
                        {action}
                      </span>
                    </div>
                  )
                )}
              </div>
            </section>

            <section className="overview-card">
              <div className="section-heading">
                <div>
                  <span className="section-kicker">
                    04
                  </span>

                  <h2>
                    Incidents
                  </h2>
                </div>

                <span className="card-label">
                  {result.incidents.length}{" "}
                  ACTIVE
                </span>
              </div>

              {result.incidents.length ===
                0 ? (
                <div className="empty-state">
                  <h3>
                    No incidents
                  </h3>

                  <p>
                    All monitored workers
                    are currently within
                    the simulated safety
                    state.
                  </p>
                </div>
              ) : (
                <div className="ranking">
                  {result.incidents.map(
                    (incident) => (
                      <div
                        className="ranking-row"
                        key={incident.id}
                      >
                        <div className="rank-number">
                          {incident.id}
                        </div>

                        <div className="rank-info">
                          <div className="rank-title">
                            <span>
                              Worker{" "}
                              {
                                incident.worker_id
                              }
                            </span>

                            <strong>
                              {
                                incident.status
                              }
                            </strong>
                          </div>

                          <small>
                            {incident.type}
                          </small>
                        </div>
                      </div>
                    )
                  )}
                </div>
              )}
            </section>
          </>
        )}

        {!result &&
          !loading &&
          !error && (
            <section className="overview-card empty-state">
              <div className="empty-icon">
                ◎
              </div>

              <h3>
                Agent standing by
              </h3>

              <p>
                Start Sentinel to begin
                environmental observation,
                worker assessment, and
                autonomous response.
              </p>
            </section>
          )}

        <section className="intelligence-strip">
          <div>
            <span>
              ENVIRONMENT
            </span>

            <strong>
              FortyGuard intelligence
            </strong>
          </div>

          <div>
            <span>
              AGENT
            </span>

            <strong>
              LangGraph · LangChain
            </strong>
          </div>

          <div>
            <span>
              EXECUTION
            </span>

            <strong>
              Observe · Decide · Act · Escalate
            </strong>
          </div>
        </section>
      </main>

      <footer>
        <span>
          SENTINEL
        </span>

        <span>
          Autonomous environmental
          safety workforce
        </span>
      </footer>
    </div>
  );
}

export default App;