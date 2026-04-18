import { useState, useEffect, useRef, useCallback } from 'react';
import axios from 'axios';
import './index.css';

// Dynamically route to current host in production, or localhost during React dev server
const API_URL = import.meta.env?.VITE_API_URL || (import.meta.env.PROD ? '/api' : 'http://localhost:8000/api');
const SSE_URL = `${API_URL}/stream`;

const getHeatmapColor = (utilization) => {
  if (utilization < 40) return 'rgba(76, 175, 80, 0.7)';
  if (utilization < 80) return 'rgba(255, 235, 59, 0.7)';
  return 'rgba(244, 67, 54, 0.8)';
};

function App() {
  const [state, setState] = useState({ mode: 'LOADING', zones: {} });
  const [messages, setMessages] = useState([
    { role: 'ai', content: 'Hello Supervisor. I am strictly monitoring the venue.' }
  ]);
  const [chatInput, setChatInput] = useState('');
  const [error, setError] = useState(null);
  const [sseStatus, setSseStatus] = useState('connecting'); // 'connected' | 'connecting' | 'disconnected'

  // Dynamic Zone Creation State
  const [newZoneName, setNewZoneName] = useState('');
  const [newZoneCap, setNewZoneCap] = useState('');
  const [headcountInputs, setHeadcountInputs] = useState({});

  // Routing Tester State
  const [routeStart, setRouteStart] = useState('');
  const [routeEnd, setRouteEnd] = useState('');
  const [accessibleOnly, setAccessibleOnly] = useState(false);
  const [routePath, setRoutePath] = useState(null);
  const [routeError, setRouteError] = useState(null);

  const esRef = useRef(null);
  const reconnectTimer = useRef(null);
  const fallbackTimer = useRef(null);

  // ── SSE Connection ──────────────────────────────────────────────────────

  const connectSSE = useCallback(() => {
    // Clean up any existing connection first
    if (esRef.current) {
      esRef.current.close();
    }
    clearTimeout(reconnectTimer.current);

    setSseStatus('connecting');
    const es = new EventSource(SSE_URL);
    esRef.current = es;

    es.onopen = () => {
      setSseStatus('connected');
      setError(null);
      // Cancel the fallback poll since SSE is live
      clearInterval(fallbackTimer.current);
    };

    es.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        // SSE sends { mode, zones } — shape the same as /api/admin/state
        setState({ mode: payload.mode, zones: payload.zones });
      } catch (e) {
        console.error('SSE parse error:', e);
      }
    };

    es.onerror = () => {
      es.close();
      esRef.current = null;
      setSseStatus('disconnected');
      setError('Live connection lost — reconnecting in 4s...');

      // Start a temporary fallback poll while disconnected
      fallbackTimer.current = setInterval(async () => {
        try {
          const res = await axios.get(`${API_URL}/admin/state`);
          setState(res.data);
        } catch (_) { /* silent */ }
      }, 4000);

      // Reconnect SSE after 4 seconds
      reconnectTimer.current = setTimeout(() => {
        clearInterval(fallbackTimer.current);
        connectSSE();
      }, 4000);
    };
  }, []);

  useEffect(() => {
    connectSSE();
    return () => {
      if (esRef.current) esRef.current.close();
      clearTimeout(reconnectTimer.current);
      clearInterval(fallbackTimer.current);
    };
  }, [connectSSE]);

  // ── Chat ────────────────────────────────────────────────────────────────

  const sendChatMessage = async (e) => {
    e.preventDefault();
    const sanitizedInput = chatInput.trim();
    if (!sanitizedInput) return;

    const userMsg = { role: 'user', content: sanitizedInput };
    setMessages((prev) => [...prev, userMsg]);
    setChatInput('');

    try {
      const res = await axios.post(`${API_URL}/admin/chat`, { message: userMsg.content });
      setMessages((prev) => [...prev, { role: 'ai', content: res.data.response || 'Understood.' }]);
    } catch (e) {
      setMessages((prev) => [...prev, { role: 'ai', content: e.response?.data?.detail || 'Connection Error.' }]);
    }
  };

  // ── Report ──────────────────────────────────────────────────────────────

  const generateReport = async () => {
    try {
      const res = await axios.post(`${API_URL}/admin/generate_report`);
      setMessages((prev) => [...prev, { role: 'ai', content: `✅ [SYSTEM] Daily Event Report generated! Saved as: ${res.data.file}` }]);
    } catch (e) {
      setMessages((prev) => [...prev, { role: 'ai', content: `❌ [ERROR] ${e.response?.data?.detail || 'Failed to generate report.'}` }]);
    }
  };

  // ── Zone Management ─────────────────────────────────────────────────────

  const handleAddZone = async (e) => {
    e.preventDefault();
    if (!newZoneName || !newZoneCap) return;
    try {
      await axios.post(`${API_URL}/admin/zones`, {
        zone_id: newZoneName,
        capacity: parseInt(newZoneCap),
        service_time_sec: 10
      });
      setNewZoneName('');
      setNewZoneCap('');
      // No manual fetchState needed — SSE push will arrive instantly
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to register zone.');
    }
  };

  const handleDeleteZone = async (zone_id) => {
    try {
      await axios.delete(`${API_URL}/admin/zones/${zone_id}`);
      // SSE push will update the UI instantly
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to delete zone.');
    }
  };

  const handleUpdateHeadcount = async (zone_id) => {
    const count = parseInt(headcountInputs[zone_id] ?? '');
    if (isNaN(count) || count < 0) return;
    try {
      await axios.post(`${API_URL}/admin/simulate_crowd`, null, {
        params: { zone_id, headcount: count }
      });
      setHeadcountInputs(prev => ({ ...prev, [zone_id]: '' }));
      // SSE push will update the UI instantly
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to update headcount.');
    }
  };

  const handleGetRoute = async (e) => {
    e.preventDefault();
    setRouteError(null);
    setRoutePath(null);
    if (!routeStart || !routeEnd) return;
    try {
      const res = await axios.get(`${API_URL}/attendee/route`, {
        params: { start: routeStart, end: routeEnd, accessible_only: accessibleOnly }
      });
      setRoutePath(res.data.route);
    } catch (e) {
      setRouteError(e.response?.data?.detail || 'Failed to calculate route.');
    }
  };

  // ── Render ──────────────────────────────────────────────────────────────

  return (
    <div className="dashboard-container" data-testid="app-dashboard">
      <main className="main-content">
        <header className="header-controls">
          <div>
            <h1>SmartVenue AI</h1>
            <p style={{ color: 'var(--text-muted)', margin: '0.25rem 0 0' }}>Universal Venue Operations Dashboard</p>
            {error && (
              <span role="alert" aria-live="assertive" style={{ color: '#ff5555', fontSize: '0.85rem', display: 'block', marginTop: '0.4rem' }}>
                {error}
              </span>
            )}
          </div>
          <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
            {/* SSE live status indicator */}
            <div
              title={`Live sync: ${sseStatus}`}
              aria-label={`Live connection status: ${sseStatus}`}
              style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.8rem', color: 'var(--text-muted)' }}
            >
              <span
                className={`sse-dot sse-dot--${sseStatus}`}
              />
              {sseStatus === 'connected' ? 'Live' : sseStatus === 'connecting' ? 'Connecting…' : 'Reconnecting…'}
            </div>
            <button className="report-btn" onClick={generateReport} aria-label="Generate Markdown report">
              Post-Event Report
            </button>
            <div className="mode-badge" role="status" aria-label={`Current Mode: ${state.mode}`}>
              {state.mode}
            </div>
          </div>
        </header>

        {/* Dynamic Heatmap */}
        <div
          className="glass-card map-container"
          aria-label="Dynamic Space Plot"
          style={{ marginTop: '2rem', padding: '2.5rem', display: 'flex', flexWrap: 'wrap', gap: '2rem', justifyContent: 'center', background: 'radial-gradient(circle at center, rgba(94, 106, 210, 0.1) 0%, transparent 70%)' }}
        >
          {Object.keys(state.zones).length === 0 ? (
            <h3 style={{ color: 'var(--text-muted)', fontWeight: 300, fontStyle: 'italic' }}>
              No spaces mapped. Deploy a zone to begin physical tracking!
            </h3>
          ) : (
            Object.entries(state.zones).map(([zoneName, data]) => {
              const util = Math.round((data.current_headcount / Math.max(1, data.capacity)) * 100);
              return (
                <div
                  key={`map-${zoneName}`}
                  style={{
                    background: getHeatmapColor(util),
                    padding: '2rem',
                    borderRadius: '1rem',
                    minWidth: '160px',
                    textAlign: 'center',
                    boxShadow: '0 10px 30px rgba(0,0,0,0.5)',
                    border: '2px solid rgba(255,255,255,0.7)',
                    transition: 'background 0.6s ease, transform 0.3s ease',
                    cursor: 'pointer'
                  }}
                  onMouseOver={(e) => e.currentTarget.style.transform = 'scale(1.05)'}
                  onMouseOut={(e) => e.currentTarget.style.transform = 'scale(1)'}
                >
                  <h4 style={{ margin: 0, fontWeight: 700, letterSpacing: '1px', color: '#1a1a2e', textShadow: '0 1px 2px rgba(255,255,255,0.3)' }}>
                    {zoneName.replace(/_/g, ' ').toUpperCase()}
                  </h4>
                  <span style={{ fontSize: '0.9rem', opacity: 0.9, color: '#1a1a2e', fontWeight: 600 }}>
                    {util}% Capacity
                  </span>
                </div>
              );
            })
          )}
        </div>

        {/* Zone Registration */}
        <div className="glass-card" style={{ marginTop: '1.5rem', border: '1px dashed var(--glass-border)', padding: '1.5rem' }}>
          <h3 style={{ marginTop: 0, marginBottom: '1rem', fontSize: '1.1rem' }}>➕ Topography Engine (Register Venue Element)</h3>
          <form onSubmit={handleAddZone} style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', alignItems: 'center' }}>
            <input
              type="text"
              placeholder="E.g. VIP Lounge"
              value={newZoneName}
              onChange={e => setNewZoneName(e.target.value)}
              style={{ flex: 1, padding: '0.8rem', borderRadius: '0.5rem', border: '1px solid var(--glass-border)', background: 'rgba(0,0,0,0.2)', color: 'white', fontFamily: 'Outfit' }}
              required
            />
            <input
              type="number"
              placeholder="Max Capacity (e.g. 500)"
              value={newZoneCap}
              onChange={e => setNewZoneCap(e.target.value)}
              style={{ width: '200px', padding: '0.8rem', borderRadius: '0.5rem', border: '1px solid var(--glass-border)', background: 'rgba(0,0,0,0.2)', color: 'white', fontFamily: 'Outfit' }}
              required
              min="1"
            />
            <button type="submit" className="report-btn" style={{ borderColor: 'var(--accent)', color: 'var(--text)' }}>
              Deploy Sensor
            </button>
          </form>
        </div>

        {/* Accessibility & Routing Tester */}
        <div className="glass-card" style={{ marginTop: '1.5rem', border: '1px solid var(--glass-border)', padding: '1.5rem' }}>
          <h3 style={{ marginTop: 0, marginBottom: '1rem', fontSize: '1.1rem', color: 'var(--accent)' }}>🗺 Accessibility & Routing Tester</h3>
          <form onSubmit={handleGetRoute} style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', alignItems: 'center' }}>
            <input
              type="text"
              placeholder="Start Zone (e.g. Gate A)"
              value={routeStart}
              onChange={e => setRouteStart(e.target.value)}
              style={{ flex: 1, padding: '0.8rem', borderRadius: '0.5rem', border: '1px solid var(--glass-border)', background: 'rgba(0,0,0,0.2)', color: 'white', fontFamily: 'Outfit' }}
              required
            />
            <span style={{color: 'var(--text-muted)'}}>→</span>
            <input
              type="text"
              placeholder="End Zone (e.g. Concourse)"
              value={routeEnd}
              onChange={e => setRouteEnd(e.target.value)}
              style={{ flex: 1, padding: '0.8rem', borderRadius: '0.5rem', border: '1px solid var(--glass-border)', background: 'rgba(0,0,0,0.2)', color: 'white', fontFamily: 'Outfit' }}
              required
            />
            <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', fontFamily: 'Outfit', color: 'var(--text)' }}>
              <input 
                type="checkbox" 
                checked={accessibleOnly} 
                onChange={e => setAccessibleOnly(e.target.checked)} 
                style={{ width: '1.2rem', height: '1.2rem', accentColor: 'var(--accent)' }}
              />
              Avoid Stairs (Accessible)
            </label>
            <button type="submit" className="report-btn">Compute Route</button>
          </form>
          {routePath && (
            <div style={{ marginTop: '1rem', padding: '1rem', background: 'rgba(76, 175, 80, 0.1)', border: '1px solid #4CAF50', borderRadius: '0.5rem' }}>
              <strong style={{color: '#4CAF50'}}>Success! Route taken:</strong> {routePath.join(' ➔ ')}
            </div>
          )}
          {routeError && (
             <div style={{ marginTop: '1rem', padding: '1rem', background: 'rgba(244, 67, 54, 0.1)', border: '1px solid #F44336', borderRadius: '0.5rem', color: '#ffaaaa' }}>
               {routeError}
             </div>
          )}
        </div>

        {/* Zone Cards */}
        <section className="zones-grid" aria-label="Venue Zones" style={{ marginTop: '1rem' }}>
          {Object.entries(state.zones).map(([zoneName, data]) => {
            const safeCapacity = data.capacity > 0 ? data.capacity : 1;
            const utilization = Math.round((data.current_headcount / safeCapacity) * 100);
            const isAlert = utilization > 80;

            return (
              <article className="glass-card zone-stat" key={`stat-${zoneName}`} data-testid={`zone-${zoneName}`}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                  <h3 style={{ margin: 0 }}>{zoneName.replace(/_/g, ' ')}</h3>
                  <button
                    onClick={() => handleDeleteZone(zoneName)}
                    style={{ background: 'transparent', border: 'none', color: '#ff5555', cursor: 'pointer', fontSize: '1.5rem', lineHeight: '1rem' }}
                    title="Decommission Node"
                  >×</button>
                </div>

                <div className="value" aria-label={`${data.current_headcount} out of ${data.capacity} people`}>
                  {data.current_headcount} <span style={{ fontSize: '1rem', color: 'var(--text-muted)' }} aria-hidden="true">/ {data.capacity}</span>
                </div>

                <div
                  role="progressbar"
                  aria-valuenow={utilization}
                  aria-valuemin="0"
                  aria-valuemax="100"
                  aria-label={`${zoneName} utilization at ${utilization}%`}
                  style={{ marginTop: '1rem', background: 'rgba(0,0,0,0.3)', height: '6px', borderRadius: '3px', overflow: 'hidden' }}
                >
                  <div style={{ width: `${utilization}%`, height: '100%', background: isAlert ? '#ff5555' : 'var(--accent)', transition: 'width 0.5s ease' }} />
                </div>

                {/* Inline headcount updater */}
                <div style={{ marginTop: '1rem', display: 'flex', gap: '0.5rem' }}>
                  <input
                    type="number"
                    min="0"
                    placeholder="New count"
                    value={headcountInputs[zoneName] ?? ''}
                    onChange={e => setHeadcountInputs(prev => ({ ...prev, [zoneName]: e.target.value }))}
                    aria-label={`Set headcount for ${zoneName}`}
                    style={{ flex: 1, padding: '0.4rem 0.6rem', borderRadius: '0.4rem', border: '1px solid var(--glass-border)', background: 'rgba(0,0,0,0.25)', color: 'white', fontFamily: 'Outfit', fontSize: '0.85rem' }}
                  />
                  <button
                    onClick={() => handleUpdateHeadcount(zoneName)}
                    style={{ padding: '0.4rem 0.8rem', borderRadius: '0.4rem', border: '1px solid var(--accent)', background: 'transparent', color: 'var(--accent)', cursor: 'pointer', fontFamily: 'Outfit', fontSize: '0.85rem', fontWeight: 600 }}
                    aria-label={`Update headcount for ${zoneName}`}
                  >Update</button>
                </div>
              </article>
            );
          })}
        </section>
      </main>

      {/* Chat Panel */}
      <aside className="glass-card chat-box" aria-label="Operations Co-Pilot Chat">
        <h3 style={{ marginTop: 0, paddingBottom: '1rem', borderBottom: '1px solid var(--glass-border)' }}>Ops Co-Pilot</h3>
        <div className="chat-messages" role="log" aria-live="polite" aria-atomic="false" data-testid="chat-messages">
          {messages.map((m, i) => (
            <div key={i} className={`message ${m.role}`} data-testid={`message-${i}`}>
              {m.content}
            </div>
          ))}
        </div>
        <form className="chat-input" onSubmit={sendChatMessage} aria-label="Chat input form">
          <label htmlFor="chat-input" style={{ position: 'absolute', width: '1px', height: '1px', padding: 0, margin: '-1px', overflow: 'hidden', clip: 'rect(0,0,0,0)', border: 0 }}>
            Ask anything about the venue
          </label>
          <input
            id="chat-input"
            type="text"
            value={chatInput}
            onChange={e => setChatInput(e.target.value)}
            placeholder="Ask anything about the venue or command me..."
            aria-required="true"
            data-testid="chat-input-field"
          />
          <button type="submit" aria-label="Send message" data-testid="chat-submit-btn">Execute</button>
        </form>
      </aside>
    </div>
  );
}

export default App;
