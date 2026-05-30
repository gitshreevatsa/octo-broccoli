export default function ProgressStepper({ events }) {
  if (!events.length) return null

  const last    = events[events.length - 1]
  const isDone  = last?.type === 'done'
  const isError = last?.type === 'error'

  return (
    <div style={s.wrap}>
      <div style={s.header}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {!isDone && !isError && <span style={s.spinner} />}
          <span style={s.title}>
            {isDone ? 'Search complete' : isError ? 'Error' : 'Searching…'}
          </span>
        </div>
        {isDone && (
          <span style={s.badge}>{last.message} jobs ranked</span>
        )}
      </div>

      <div style={s.log}>
        {events.map((e, i) => (
          <div key={i} style={{ ...s.line, color: color(e.type), opacity: i < events.length - 1 ? 0.6 : 1 }}>
            <span style={s.icon}>{icon(e.type)}</span>
            <span>{label(e)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function color(type) {
  if (type === 'done')    return 'var(--green)'
  if (type === 'error')   return 'var(--red)'
  if (type === 'scraped') return 'var(--accent2)'
  if (type === 'total')   return 'var(--accent2)'
  return 'var(--text-dim)'
}
function icon(type) {
  if (type === 'done')  return '✓'
  if (type === 'error') return '✗'
  if (type === 'step')  return '›'
  return '›'
}
function label(e) {
  if (e.type === 'done')  return `Ranked ${e.message} jobs`
  if (e.type === 'total') return `${e.message} total listings scraped`
  return e.message
}

const s = {
  wrap: {
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius)',
    padding: '18px 22px',
    marginBottom: 20,
    animation: 'fadeIn 0.2s ease',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 14,
  },
  spinner: {
    display: 'inline-block',
    width: 14, height: 14,
    borderRadius: '50%',
    border: '2px solid var(--border2)',
    borderTopColor: 'var(--accent)',

    animation: 'spin 0.7s linear infinite',
    flexShrink: 0,
  },
  title: { fontWeight: 600, fontSize: 14 },
  badge: {
    background: 'rgba(52,211,153,0.1)',
    color: 'var(--green)',
    border: '1px solid rgba(52,211,153,0.25)',
    borderRadius: 20,
    padding: '3px 12px',
    fontSize: 12,
    fontWeight: 600,
  },
  log: {
    display: 'flex',
    flexDirection: 'column',
    gap: 4,
    fontFamily: 'ui-monospace, monospace',
    fontSize: 12,
  },
  line: { display: 'flex', gap: 9, alignItems: 'flex-start' },
  icon: { width: 12, flexShrink: 0, marginTop: 1, fontWeight: 700 },
}
