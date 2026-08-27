import { useState } from "react";
import "./index.css";

function App() {
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  async function runAgent() {
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const response = await fetch(
        "http://127.0.0.1:8000/api/agent/run",
        {
          method: "POST",
        }
      );

      if (!response.ok) {
        throw new Error("Agent request failed.");
      }

      const data = await response.json();
      setResult(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">S</div>

          <div>
            <div className="brand-name">Sentinel</div>
            <div className="brand-subtitle">
              Environmental Safety Agent
            </div>
          </div>
        </div>

        <div className="system-status">
          <span className="status-dot" />
          <span>Agent online</span>
        </div>
      </header>

      <main className="main-content">
        <section className="hero">
          <div className="hero-eyebrow">
            AUTONOMOUS ENVIRONMENTAL SAFETY
          </div>

          <h1>
            Your safety workforce,
            <span> always watching.</span>
          </h1>

          <p>
            Sentinel continuously observes environmental conditions,
            monitors field workers, and executes safety-response
            workflows when action is required.
          </p>

          <button
            className="analyze-button"
            onClick={runAgent}
            disabled={loading}
          >
            <span>
              {loading ? "Agent is working..." : "Run safety agent"}
            </span>

            <span className="button-arrow">
              {loading ? "…" : "→"}
            </span>
          </button>
        </section>

        {error && (
          <div className="error-state">
            <strong>Agent unavailable</strong>
            <p>{error}</p>
          </div>
        )}

        {loading && (
          <section className="workspace">
            <div className="overview-card agent-running">
              <div className="loading-ring" />

              <h2>Agent is working</h2>

              <p>
                Observing environmental conditions and evaluating
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
                    <span className="section-kicker">01</span>
                    <h2>Environment</h2>
                  </div>

                  <span className="card-label">FORTYGUARD</span>
                </div>

                <div className="result-summary">
                  <div>
                    <span>TEMPERATURE</span>
                    <strong>
                      {result.environment.temperature_c}°C
                    </strong>
                  </div>

                  <div>
                    <span>HEAT INDEX</span>
                    <strong>
                      {result.environment.heat_index_c ?? "—"}°C
                    </strong>
                  </div>

                  <div>
                    <span>WET BULB</span>
                    <strong>
                      {result.environment.wet_bulb_c ?? "—"}°C
                    </strong>
                  </div>

                  <div>
                    <span>HUMIDITY</span>
                    <strong>
                      {result.environment.humidity_percent ?? "—"}%
                    </strong>
                  </div>
                </div>
              </div>

              <div className="overview-card">
                <div className="section-heading">
                  <div>
                    <span className="section-kicker">02</span>
                    <h2>Field workforce</h2>
                  </div>

                  <span className="card-label">
                    {result.workers.length} WORKERS
                  </span>
                </div>

                <div className="ranking">
                  {result.workers.map((worker) => (
                    <div className="ranking-row" key={worker.id}>
                      <div className="rank-number">
                        {worker.id}
                      </div>

                      <div className="rank-info">
                        <div className="rank-title">
                          <span>{worker.name}</span>

                          <strong>
                            {worker.status.replaceAll("_", " ")}
                          </strong>
                        </div>

                        <small>
                          {worker.task} ·{" "}
                          {worker.exposure_minutes} min exposure
                        </small>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </section>

            <section className="overview-card agent-log">
              <div className="section-heading">
                <div>
                  <span className="section-kicker">03</span>
                  <h2>Agent activity</h2>
                </div>

                <span className="card-label">LIVE LOG</span>
              </div>

              <div className="activity-list">
                {result.agent_actions.map((action, index) => (
                  <div className="activity-row" key={index}>
                    <span className="activity-dot" />
                    <span>{action}</span>
                  </div>
                ))}
              </div>
            </section>

            <section className="overview-card">
              <div className="section-heading">
                <div>
                  <span className="section-kicker">04</span>
                  <h2>Incidents</h2>
                </div>

                <span className="card-label">
                  {result.incidents.length} ACTIVE
                </span>
              </div>

              {result.incidents.length === 0 ? (
                <div className="empty-state">
                  <h3>No incidents</h3>
                  <p>
                    All monitored workers are currently within the
                    simulated safety state.
                  </p>
                </div>
              ) : (
                <div className="ranking">
                  {result.incidents.map((incident) => (
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
                            Worker {incident.worker_id}
                          </span>

                          <strong>{incident.status}</strong>
                        </div>

                        <small>{incident.type}</small>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </>
        )}

        {!result && !loading && !error && (
          <section className="overview-card empty-state">
            <div className="empty-icon">◎</div>

            <h3>Agent standing by</h3>

            <p>
              Run the safety agent to begin environmental observation,
              worker assessment, and autonomous response.
            </p>
          </section>
        )}

        <section className="intelligence-strip">
          <div>
            <span>ENVIRONMENT</span>
            <strong>FortyGuard intelligence</strong>
          </div>

          <div>
            <span>AGENT</span>
            <strong>LangGraph · LangChain</strong>
          </div>

          <div>
            <span>EXECUTION</span>
            <strong>Observe · Act · Escalate</strong>
          </div>
        </section>
      </main>

      <footer>
        <span>SENTINEL</span>
        <span>Autonomous environmental safety workforce</span>
      </footer>
    </div>
  );
}

export default App;