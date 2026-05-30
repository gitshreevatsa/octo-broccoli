import { useState } from 'react'
import SearchForm from './components/SearchForm.jsx'
import ProgressStepper from './components/ProgressStepper.jsx'
import ResultsTable from './components/ResultsTable.jsx'

export default function App() {
  const [loading, setLoading]     = useState(false)
  const [events, setEvents]       = useState([])
  const [jobs, setJobs]           = useState(null)
  const [currentRole, setRole]    = useState('')
  // Session-only history — cleared on page refresh
  const [sessionHistory, setSessionHistory] = useState([])

  async function handleSearch(config) {
    setLoading(true)
    setEvents([])
    setJobs(null)
    setRole(config.role)

    let searchId
    try {
      const res = await fetch('/api/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      })
      const data = await res.json()
      searchId = data.search_id
    } catch (e) {
      setEvents([{ type: 'error', message: 'Failed to start search: ' + e.message }])
      setLoading(false)
      return
    }

    const es = new EventSource(`/api/search/${searchId}/stream`)
    es.onmessage = async (e) => {
      const event = JSON.parse(e.data)
      setEvents(prev => [...prev, event])

      if (event.type === 'done') {
        es.close()
        try {
          const res = await fetch(`/api/search/${searchId}/results`)
          const data = await res.json()
          const ranked = data.jobs || []
          setJobs(ranked)
          // Add to session history
          setSessionHistory(prev => [{
            id: searchId,
            role: config.role,
            count: ranked.length,
            time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
            jobs: ranked,
          }, ...prev])
        } catch {
          setEvents(prev => [...prev, { type: 'error', message: 'Failed to load results' }])
        }
        setLoading(false)
      }
      if (event.type === 'error') { es.close(); setLoading(false) }
    }
    es.onerror = () => { es.close(); setLoading(false) }
  }

  return (
    <div style={s.shell}>

      {/* ── Left sidebar ── */}
      <aside style={s.sidebar}>
        <div style={s.sidebarTop}>
          <div style={s.brand}>
            <span style={s.brandIcon}>⚡</span>
            <span style={s.brandName}>Job Searcher</span>
          </div>
          <SearchForm onSubmit={handleSearch} loading={loading} />
        </div>

        {/* Session history */}
        {sessionHistory.length > 0 && (
          <div style={s.history}>
            <div style={s.historyTitle}>This session</div>
            {sessionHistory.map(h => (
              <button
                key={h.id}
                onClick={() => { setJobs(h.jobs); setRole(h.role); setEvents([{ type: 'done', message: String(h.count) }]) }}
                style={s.historyItem}
              >
                <span style={s.historyRole}>{h.role}</span>
                <span style={s.historyMeta}>{h.count} jobs · {h.time}</span>
              </button>
            ))}
          </div>
        )}
      </aside>

      {/* ── Main content ── */}
      <main style={s.main}>
        {!jobs && events.length === 0 && (
          <div style={s.empty}>
            <div style={s.emptyIcon}>🔍</div>
            <div style={s.emptyTitle}>Start a search</div>
            <div style={s.emptyText}>Fill in the role and filters on the left, then hit Search Jobs.</div>
          </div>
        )}

        {events.length > 0 && (
          <ProgressStepper events={events} />
        )}

        {jobs && (
          <div style={{ animation: 'fadeIn 0.2s ease' }}>
            <div style={s.resultsHeader}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
                <span style={s.resultsTitle}>{currentRole}</span>
                <span style={s.resultsCount}>{jobs.length} jobs ranked</span>
              </div>
              <button
                onClick={() => { setJobs(null); setEvents([]) }}
                style={s.clearBtn}
              >
                ← New Search
              </button>
            </div>
            <ResultsTable jobs={jobs} />
          </div>
        )}
      </main>

    </div>
  )
}

const s = {
  shell: {
    display: 'flex',
    height: '100vh',
    overflow: 'hidden',
  },
  sidebar: {
    width: 280,
    minWidth: 280,
    background: 'var(--surface)',
    borderRight: '1px solid var(--border)',
    display: 'flex',
    flexDirection: 'column',
    overflowY: 'auto',
    flexShrink: 0,
  },
  sidebarTop: { flex: 1 },
  brand: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '16px 18px 14px',
    borderBottom: '1px solid var(--border)',
    marginBottom: 4,
  },
  brandIcon: { fontSize: 18 },
  brandName: { fontWeight: 700, fontSize: 15, letterSpacing: '-0.02em' },
  history: {
    borderTop: '1px solid var(--border)',
    padding: '12px 0',
  },
  historyTitle: {
    fontSize: 10,
    fontWeight: 700,
    letterSpacing: '0.07em',
    textTransform: 'uppercase',
    color: 'var(--text-dim)',
    padding: '0 18px 8px',
  },
  historyItem: {
    display: 'flex',
    flexDirection: 'column',
    gap: 2,
    width: '100%',
    padding: '8px 18px',
    background: 'transparent',
    color: 'var(--text)',
    textAlign: 'left',
    transition: 'background 0.12s',
    borderLeft: '2px solid transparent',
  },
  historyRole: { fontSize: 13, fontWeight: 500 },
  historyMeta: { fontSize: 11, color: 'var(--text-dim)' },
  main: {
    flex: 1,
    overflow: 'auto',
    padding: '28px 32px',
    background: 'var(--bg)',
  },
  empty: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    height: '70%',
    gap: 12,
    color: 'var(--text-dim)',
    textAlign: 'center',
  },
  emptyIcon: { fontSize: 40, marginBottom: 4 },
  emptyTitle: { fontSize: 18, fontWeight: 600, color: 'var(--text)' },
  emptyText: { fontSize: 14, maxWidth: 300, lineHeight: 1.6 },
  resultsHeader: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 16,
  },
  resultsTitle: { fontSize: 20, fontWeight: 700 },
  resultsCount: { fontSize: 13, color: 'var(--text-dim)' },
  clearBtn: {
    background: 'transparent',
    color: 'var(--text-dim)',
    fontSize: 13,
    padding: '5px 10px',
    borderRadius: 6,
    border: '1px solid var(--border)',
    transition: 'color 0.15s, border-color 0.15s',
  },
}
