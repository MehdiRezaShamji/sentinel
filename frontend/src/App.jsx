import { useState } from "react";
import "./index.css";

function App() {
  const [area, setArea] = useState("Mumbai");
  const [locations, setLocations] = useState(
    "Location A, Location B, Location C"
  );
  const [resources, setResources] = useState(2);
  const [interventions, setInterventions] = useState(
    "Cooling center, Shade structure, Water station"
  );

  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  async function analyzeScenario() {
    setLoading(true);
    setError(null);
    setResult(null);

    const scenario = {
      area,
      candidate_locations: locations
        .split(",")
        .map((location) => location.trim())
        .filter(Boolean),
      available_resources: Number(resources),
      intervention_options: interventions
        .split(",")
        .map((intervention) => intervention.trim())
        .filter(Boolean),
    };

    try {
      const response = await fetch("http://127.0.0.1:8000/api/analyze", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(scenario),
      });

      if (!response.ok) {
        throw new Error("Analysis request failed.");
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
          <div className="brand-mark">H</div>

          <div>
            <div className="brand-name">Heat Resource</div>
            <div className="brand-subtitle">Optimizer</div>
          </div>
        </div>

        <div className="system-status">
          <span className="status-dot" />
          <span>Thermal intelligence system</span>
        </div>
      </header>

      <main className="main-content">
        <section className="hero">
          <div className="hero-eyebrow">
            CLIMATE RESOURCE INTELLIGENCE
          </div>

          <h1>
            Make every heat-mitigation
            <span> decision count.</span>
          </h1>

          <p>
            Evaluate candidate locations, understand thermal severity,
            and prioritize limited resources where they can have the
            greatest impact.
          </p>
        </section>

        <section className="workspace">
          <div className="scenario-card">
            <div className="section-heading">
              <div>
                <span className="section-kicker">01</span>
                <h2>Define your scenario</h2>
              </div>

              <span className="card-label">INPUT</span>
            </div>

            <div className="form-grid">
              <label className="field field-full">
                <span>Area</span>
                <input
                  value={area}
                  onChange={(event) => setArea(event.target.value)}
                  placeholder="e.g. Mumbai"
                />
              </label>

              <label className="field field-full">
                <span>Candidate locations</span>
                <input
                  value={locations}
                  onChange={(event) => setLocations(event.target.value)}
                  placeholder="Location A, Location B, Location C"
                />
                <small>Separate locations with commas.</small>
              </label>

              <label className="field">
                <span>Available resources</span>
                <input
                  type="number"
                  min="1"
                  value={resources}
                  onChange={(event) => setResources(event.target.value)}
                />
              </label>

              <label className="field">
                <span>Intervention options</span>
                <input
                  value={interventions}
                  onChange={(event) => setInterventions(event.target.value)}
                  placeholder="Cooling center, shade..."
                />
              </label>
            </div>

            <button
              className="analyze-button"
              onClick={analyzeScenario}
              disabled={loading}
            >
              <span>
                {loading ? "Analyzing scenario" : "Analyze scenario"}
              </span>

              <span className="button-arrow">
                {loading ? "…" : "→"}
              </span>
            </button>
          </div>

          <div className="overview-card">
            <div className="section-heading">
              <div>
                <span className="section-kicker">02</span>
                <h2>Priority overview</h2>
              </div>

              <span className="card-label">OUTPUT</span>
            </div>

            {!result && !loading && (
              <div className="empty-state">
                <div className="empty-icon">◎</div>

                <h3>Ready for analysis</h3>

                <p>
                  Configure your scenario and run the analysis to
                  identify the locations requiring priority attention.
                </p>
              </div>
            )}

            {loading && (
              <div className="empty-state">
                <div className="loading-ring" />

                <h3>Analyzing thermal conditions</h3>

                <p>
                  Evaluating candidate locations and optimizing the
                  available resources.
                </p>
              </div>
            )}

            {error && (
              <div className="error-state">
                <strong>Analysis unavailable</strong>
                <p>{error}</p>
              </div>
            )}

            {result && (
              <div className="results">
                <div className="result-summary">
                  <div>
                    <span>LOCATIONS EVALUATED</span>
                    <strong>{result.analysis.locations_evaluated}</strong>
                  </div>

                  <div>
                    <span>RESOURCES AVAILABLE</span>
                    <strong>{resources}</strong>
                  </div>
                </div>

                <div className="ranking">
                  {result.analysis.heat_ranking.map((location, index) => (
                    <div className="ranking-row" key={location.location}>
                      <div className="rank-number">
                        {String(index + 1).padStart(2, "0")}
                      </div>

                      <div className="rank-info">
                        <div className="rank-title">
                          <span>{location.location}</span>
                          <strong>{location.heat_score}</strong>
                        </div>

                        <div className="score-track">
                          <div
                            className="score-fill"
                            style={{
                              width: `${location.heat_score}%`,
                            }}
                          />
                        </div>
                      </div>
                    </div>
                  ))}
                </div>

                <div className="recommendation">
                  <div className="recommendation-label">
                    RECOMMENDED ALLOCATION
                  </div>

                  <h3>
                    Prioritize{" "}
                    {result.recommendation.priority_locations.length}{" "}
                    locations
                  </h3>

                  <p>{result.recommendation.message}</p>

                  <div className="priority-list">
                    {result.recommendation.priority_locations.map(
                      (location, index) => (
                        <div
                          className="priority-item"
                          key={location.location}
                        >
                          <span className="priority-index">
                            0{index + 1}
                          </span>

                          <span>{location.location}</span>

                          <strong>{location.heat_score}</strong>
                        </div>
                      )
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>
        </section>

        <section className="intelligence-strip">
          <div>
            <span>DATA SOURCE</span>
            <strong>FortyGuard thermal intelligence</strong>
          </div>

          <div>
            <span>DECISION MODEL</span>
            <strong>Resource-constrained prioritization</strong>
          </div>

          <div>
            <span>WORKFLOW</span>
            <strong>FastAPI · LangGraph · LangChain</strong>
          </div>
        </section>
      </main>

      <footer>
        <span>HEAT RESOURCE OPTIMIZER</span>
        <span>Decision support for heat resilience</span>
      </footer>
    </div>
  );
}

export default App;