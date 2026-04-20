import { useState, useEffect, useRef, useCallback } from 'react';
import axios from 'axios';
import './index.css';

// Universal relative API routing (Inherits host automatically)
const API_URL = '/api';
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

  // Google AI Hub State
  const [semanticResults, setSemanticResults] = useState([]);
  const [semanticQuery, setSemanticQuery] = useState('');
  const [groundingTopic, setGroundingTopic] = useState('');
  const [groundingResponse, setGroundingResponse] = useState('');
  const [lastAnalysis, setLastAnalysis] = useState('');
  const [isAnalyzing, setIsAnalyzing] = useState(false);

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

  // ── Google AI Handlers ──────────────────────────────────────────────────

  // SK-15: Semantic Note Search
  const handleSemanticSearch = async (e) => {
    e.preventDefault();
    if (!semanticQuery.trim()) return;
    try {
      const res = await axios.post(`${API_URL}/staff/notes/search`, { 
        query: semanticQuery,
        top_k: 5
      });
      setSemanticResults(res.data.results);
    } catch (e) {
      setError('Semantic search failed.');
    }
  };

  // SK-16: Function-Calling Agentic Chat
  const sendChatMessage = async (e) => {
    e.preventDefault();
    const sanitizedInput = chatInput.trim();
    if (!sanitizedInput) return;

    const userMsg = { role: 'user', content: sanitizedInput };
    setMessages((prev) => [...prev, userMsg]);
    setChatInput('');

    try {
      // Use the new AI action endpoint with function calling
      const res = await axios.post(`${API_URL}/admin/ai_action`, { message: userMsg.content });
      setMessages((prev) => [...prev, { 
        role: 'ai', 
        content: res.data.response,
        actions: res.data.actions_executed
      }]);
    } catch (e) {
      setMessages((prev) => [...prev, { role: 'ai', content: e.response?.data?.detail || 'AI Service Error.' }]);
    }
  };

  // SK-17: Gemini Files API Report Analysis
  const analyzeReport = async (filename) => {
    setIsAnalyzing(true);
    setLastAnalysis('');
    try {
      const res = await axios.post(`${API_URL}/admin/analyze_report`, null, {
        params: { report_filename: filename }
      });
      setLastAnalysis(res.data.ai_analysis);
    } catch (e) {
      setError('AI Report Analysis failed.');
    } finally {
      setIsAnalyzing(false);
    }
  };

  // SK-18: Real-time Grounded Search
  const handleGroundingSearch = async (e) => {
    e.preventDefault();
    if (!groundingTopic.trim()) return;
    setGroundingResponse('Consulting Google Search live results...');
    try {
      const res = await axios.post(`${API_URL}/admin/context/realtime`, { topic: groundingTopic });
      setGroundingResponse(res.data.grounded_response);
    } catch (e) {
      setGroundingResponse('Grounded search unavailable.');
    }
  };

  // ── Report ──────────────────────────────────────────────────────────────

  const generateReport = async () => {
    try {
      const res = await axios.post(`${API_URL}/admin/generate_report`);
      const filename = res.data.file;
      setMessages((prev) => [...prev, { 
        role: 'ai', 
        content: `✅ [SYSTEM] Report Generated: ${filename}`,
        reportFile: filename 
      }]);
    } catch (e) {
      setMessages((prev) => [...prev, { role: 'ai', content: `❌ [ERROR] Failed to generate report.` }]);
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
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to register zone.');
    }
  };

  const handleDeleteZone = async (zone_id) => {
    try {
      await axios.delete(`${API_URL}/admin/zones/${zone_id}`);
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
            <p style={{ color: 'var(--text-muted)', margin: '0.25rem 0 0' }}>Universal Venue Operations Dashboard <span className="ai-metric" style={{fontSize: '0.7rem', opacity: 0.6}}>v1.2 Google-AI Mode</span></p>
            {error && (
              <span role="alert" aria-live="assertive" style={{ color: '#ff5555', fontSize: '0.85rem', display: 'block', marginTop: '0.4rem' }}>
                {error}
              </span>
            )}
          </div>
          <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
            <div
              title={`Live sync: ${sseStatus}`}
              aria-label={`Live connection status: ${sseStatus}`}
              style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.8rem', color: 'var(--text-muted)' }}
            >
              <span className={`sse-dot sse-dot--${sseStatus}`} />
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

        {/* ── Google AI Hub Panel (SK-15, SK-17, SK-18) ── */}
        <section className="google-ai-panel glass-card">
          <h3>Google AI Operations Hub</h3>
          
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
            {/* Grounded Search (SK-18) */}
            <div className="grounding-section">
              <span className="grounding-badge">Live Context (SK-18)</span>
              <form onSubmit={handleGroundingSearch} style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem' }}>
                <input 
                  type="text" 
                  placeholder="Ask about weather, transport..." 
                  value={groundingTopic}
                  onChange={e => setGroundingTopic(e.target.value)}
                  style={{ flex: 1, padding: '0.6rem', borderRadius: '0.4rem', background: 'rgba(0,0,0,0.2)', color: 'white', border: '1px solid var(--glass-border)', fontSize: '0.85rem' }}
                />
                <button type="submit" className="report-btn" style={{fontSize: '0.75rem'}}>Check Web</button>
              </form>
              {groundingResponse && (
                <div className="grounding-response">{groundingResponse}</div>
              )}
            </div>

            {/* Semantic Note Search (SK-15) */}
            <div className="semantic-section">
              <span className="grounding-badge" style={{color: '#a5b4fc'}}>Semantic Note Search (SK-15)</span>
              <form onSubmit={handleSemanticSearch} style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem' }}>
                <input 
                  type="text" 
                  placeholder="Find incidents by meaning..." 
                  value={semanticQuery}
                  onChange={e => setSemanticQuery(e.target.value)}
                  style={{ flex: 1, padding: '0.6rem', borderRadius: '0.4rem', background: 'rgba(0,0,0,0.2)', color: 'white', border: '1px solid var(--glass-border)', fontSize: '0.85rem' }}
                />
                <button type="submit" className="report-btn" style={{fontSize: '0.75rem'}}>Search</button>
              </form>
              <div className="search-results" style={{maxHeight: '150px', overflowY: 'auto'}}>
                {semanticResults.map((r, i) => (
                  <div key={i} className="search-result-item">
                    <div className="search-result-text"><strong>{r.author}</strong> ({r.zone_id}): {r.note}</div>
                    <div className="similarity-score">Score: {r._similarity}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Report Analysis (SK-17) */}
          {lastAnalysis && (
            <div style={{ marginTop: '1.5rem', borderTop: '1px solid var(--glass-border)', paddingTop: '1rem' }}>
              <span className="grounding-badge" style={{color: '#fbbc05'}}>Report Intel (SK-17)</span>
              <div className="grounding-response" style={{whiteSpace: 'pre-line', maxHeight: '200px', overflowY: 'auto'}}>{lastAnalysis}</div>
            </div>
          )}
        </section>

        {/* Zone Registration */}
        <div className="glass-card" style={{ marginTop: '1.5rem', border: '1px dashed var(--glass-border)', padding: '1.5rem' }}>
          <h3 style={{ marginTop: 0, marginBottom: '1rem', fontSize: '1.1rem' }}>➕ Topography Engine (Register Venue Element)</h3>
          <form onSubmit={handleAddZone} style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', alignItems: 'center' }}>
            <input
              type="text"
              placeholder="E.g. VIP Lounge"
              value={newZoneName}
              onChange={e => setNewZoneName(e.target.value)}
              style={{ flex: 1, padding: '0.8rem', borderRadius: '0.5rem', border: '1px solid var(--glass-border)', background: 'rgba(0,0,0,0.2)', color: 'white' }}
              required
            />
            <input
              type="number"
              placeholder="Capacity"
              value={newZoneCap}
              onChange={e => setNewZoneCap(e.target.value)}
              style={{ width: '120px', padding: '0.8rem', borderRadius: '0.5rem', border: '1px solid var(--glass-border)', background: 'rgba(0,0,0,0.2)', color: 'white' }}
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
              placeholder="Start Zone"
              value={routeStart}
              onChange={e => setRouteStart(e.target.value)}
              style={{ flex: 1, padding: '0.8rem', borderRadius: '0.5rem', border: '1px solid var(--glass-border)', background: 'rgba(0,0,0,0.2)', color: 'white' }}
              required
            />
            <span style={{color: 'var(--text-muted)'}}>→</span>
            <input
              type="text"
              placeholder="End Zone"
              value={routeEnd}
              onChange={e => setRouteEnd(e.target.value)}
              style={{ flex: 1, padding: '0.8rem', borderRadius: '0.5rem', border: '1px solid var(--glass-border)', background: 'rgba(0,0,0,0.2)', color: 'white' }}
              required
            />
            <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', color: 'var(--text)' }}>
              <input type="checkbox" checked={accessibleOnly} onChange={e => setAccessibleOnly(e.target.checked)} style={{ accentColor: 'var(--accent)' }}/>
              Avoid Stairs
            </label>
            <button type="submit" className="report-btn">Compute Route</button>
          </form>
          {routePath && (
            <div style={{ marginTop: '1rem', padding: '1rem', background: 'rgba(76, 175, 80, 0.1)', border: '1px solid #4CAF50', borderRadius: '0.5rem' }}>
              <strong>Route:</strong> {routePath.join(' ➔ ')}
            </div>
          )}
        </div>

        {/* Zone Cards */}
        <section className="zones-grid" aria-label="Venue Zones" style={{ marginTop: '1rem' }}>
          {Object.entries(state.zones).map(([zoneName, data]) => {
            const usage = Math.round((data.current_headcount / Math.max(1, data.capacity)) * 100);
            return (
              <article className="glass-card zone-stat" key={`stat-${zoneName}`}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                  <h3 style={{ margin: 0 }}>{zoneName.replace(/_/g, ' ')}</h3>
                  <button onClick={() => handleDeleteZone(zoneName)} style={{ background: 'transparent', border: 'none', color: '#ff5555', cursor: 'pointer' }}>×</button>
                </div>
                <div className="value">{data.current_headcount} <span style={{ fontSize: '1rem', color: 'var(--text-muted)' }}>/ {data.capacity}</span></div>
                <div style={{ marginTop: '1rem', background: 'rgba(0,0,0,0.3)', height: '6px', borderRadius: '3px', overflow: 'hidden' }}>
                  <div style={{ width: `${usage}%`, height: '100%', background: usage > 80 ? '#ff5555' : 'var(--accent)', transition: 'width 0.5s ease' }} />
                </div>
                <div style={{ marginTop: '1rem', display: 'flex', gap: '0.5rem' }}>
                  <input
                    type="number"
                    min="0"
                    placeholder="Count"
                    value={headcountInputs[zoneName] ?? ''}
                    onChange={e => setHeadcountInputs(prev => ({ ...prev, [zoneName]: e.target.value }))}
                    style={{ flex: 1, padding: '0.4rem', borderRadius: '0.4rem', background: 'rgba(0,0,0,0.2)', color: 'white', border: '1px solid var(--glass-border)', fontSize: '0.85rem' }}
                  />
                  <button onClick={() => handleUpdateHeadcount(zoneName)} className="report-btn" style={{padding: '0.4rem', fontSize: '0.75rem'}}>Update</button>
                </div>
              </article>
            );
          })}
        </section>
      </main>

      {/* Chat Panel */}
      <aside className="glass-card chat-box" aria-label="Operations Co-Pilot Chat">
        <h3 style={{ marginTop: 0, paddingBottom: '1rem', borderBottom: '1px solid var(--glass-border)' }}>Ops Co-Pilot</h3>
        <div className="chat-messages" role="log" style={{flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '0.75rem'}}>
          {messages.map((m, i) => (
            <div key={i} className={`message ${m.role}`} style={{padding: '0.75rem', borderRadius: '0.75rem', background: m.role === 'user' ? 'var(--accent)' : 'rgba(255,255,255,0.05)', alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start', maxWidth: '85%', fontSize: '0.9rem'}}>
              {m.content}
              {m.actions && m.actions.map((act, ai) => (
                <div key={ai} className="function-call-tag" style={{marginTop: '0.5rem'}}>{act}</div>
              ))}
              {m.reportFile && (
                <button 
                  onClick={() => analyzeReport(m.reportFile)}
                  className="report-btn" 
                  disabled={isAnalyzing}
                  style={{marginTop: '0.5rem', fontSize: '0.75rem', color: '#fbbc05', borderColor: '#fbbc05'}}
                >
                  {isAnalyzing ? 'Analyzing…' : 'Analyze Report with Gemini'}
                </button>
              )}
            </div>
          ))}
        </div>
        <form className="chat-input" onSubmit={sendChatMessage} style={{display: 'flex', gap: '0.5rem', marginTop: '1rem'}}>
          <input
            type="text"
            value={chatInput}
            onChange={e => setChatInput(e.target.value)}
            placeholder="Ask or command Gemini AI…"
            style={{flex: 1, padding: '0.8rem', borderRadius: '0.5rem', background: 'rgba(0,0,0,0.25)', color: 'white', border: '1px solid var(--glass-border)'}}
          />
          <button type="submit" className="report-btn" style={{borderColor: 'var(--accent)'}}>OK</button>
        </form>
      </aside>
    </div>
  );
}

export default App;
