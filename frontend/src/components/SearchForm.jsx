import { useState } from 'react'

const SOURCES = ['linkedin', 'glassdoor', 'indeed', 'jobicy', 'remoteok', 'weworkremotely']
const SOURCE_LABELS = {
  linkedin: 'LinkedIn', glassdoor: 'Glassdoor', indeed: 'Indeed',
  jobicy: 'Jobicy', remoteok: 'RemoteOK', weworkremotely: 'WeWorkRemotely',
}

const CURRENCIES = ['USD', 'INR', 'GBP', 'EUR', 'CAD', 'AUD', 'SGD', 'AED']

const defaults = {
  role: '',
  location: 'Remote',
  prefer_remote: false,
  experience_years: '',
  salary_min: '',
  salary_currency: 'USD',
  results_per_source: '',
  posted_within_hours: '',
  sources: Object.fromEntries(SOURCES.map(s => [s, true])),
}

function Field({ label, hint, children, style }) {
  return (
    <div style={{ ...s.field, ...style }}>
      <label style={s.label}>{label}</label>
      {children}
      {hint && <span style={s.hint}>{hint}</span>}
    </div>
  )
}

function NumInput({ value, onChange, placeholder, min = 0, max, step, commas = false }) {
  if (commas) {
    // Text input that accepts commas — strips them before storing
    return (
      <input
        type="text"
        inputMode="numeric"
        value={value === '' ? '' : String(value).replace(/\B(?=(\d{3})+(?!\d))/g, ',')}
        placeholder={placeholder ?? '0'}
        onChange={e => {
          const raw = e.target.value.replace(/,/g, '').replace(/[^0-9]/g, '')
          onChange(raw === '' ? '' : Number(raw))
        }}
      />
    )
  }
  return (
    <input
      type="number"
      value={value}
      min={min} max={max} step={step}
      placeholder={placeholder ?? '0'}
      onChange={e => onChange(e.target.value === '' ? '' : Number(e.target.value))}
    />
  )
}

function Toggle({ checked, onChange, label }) {
  return (
    <div style={s.toggleRow} onClick={() => onChange(!checked)}>
      <div style={{ ...s.track, background: checked ? 'var(--accent)' : 'var(--surface3)', borderColor: checked ? 'var(--accent)' : 'var(--border2)' }}>
        <div style={{ ...s.thumb, transform: checked ? 'translateX(16px)' : 'translateX(1px)' }} />
      </div>
      <span style={{ fontSize: 13, color: checked ? 'var(--text)' : 'var(--text-dim)', userSelect: 'none' }}>
        {label}
      </span>
    </div>
  )
}

export default function SearchForm({ onSubmit, loading }) {
  const [form, setForm] = useState(defaults)
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))
  const toggleSource = src => setForm(f => ({ ...f, sources: { ...f.sources, [src]: !f.sources[src] } }))
  const allOn = SOURCES.every(src => form.sources[src])

  const handleSubmit = e => {
    e.preventDefault()
    if (!form.role.trim()) return
    onSubmit({
      ...form,
      experience_years:    form.experience_years    === '' ? 0  : form.experience_years,
      salary_min:          form.salary_min          === '' ? 0  : form.salary_min,
      salary_currency:     form.salary_currency,
      results_per_source:  form.results_per_source  === '' ? 15 : form.results_per_source,
      posted_within_hours: form.posted_within_hours === '' ? 0  : form.posted_within_hours,
    })
  }

  return (
    <form onSubmit={handleSubmit}>

      {/* ── Role & Location ── */}
      <div style={s.group}>
        <div style={s.groupTitle}>Search</div>
        <Field label="Job Role">
          <input
            type="text"
            value={form.role}
            placeholder="e.g. ML Engineer"
            required
            onChange={e => set('role', e.target.value)}
          />
        </Field>
        <Field label="Location">
          <input
            type="text"
            value={form.location}
            placeholder="Remote, New York…"
            onChange={e => set('location', e.target.value)}
          />
        </Field>
      </div>

      <div style={s.hr} />

      {/* ── Filters ── */}
      <div style={s.group}>
        <div style={s.groupTitle}>Filters</div>
        <div style={s.cols2}>
          <Field label="Experience (yrs)" hint="0 = any">
            <NumInput value={form.experience_years} placeholder="3" max={40}
              onChange={v => set('experience_years', v)} />
          </Field>
          <Field label="Min Salary" hint="0 = any" style={{ gridColumn: 'span 2' }}>
            <div style={{ display: 'flex', gap: 6 }}>
              <NumInput value={form.salary_min} placeholder="e.g. 20,00,000" commas
                onChange={v => set('salary_min', v)} />
              <select
                value={form.salary_currency}
                onChange={e => set('salary_currency', e.target.value)}
                style={{ width: 76, flexShrink: 0, padding: '8px 6px' }}
              >
                {CURRENCIES.map(c => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
          </Field>
          <Field label="Per Source">
            <NumInput value={form.results_per_source} placeholder="15" min={5} max={50}
              onChange={v => set('results_per_source', v)} />
          </Field>
          <Field label="Posted (hrs)" hint="0 = any">
            <NumInput value={form.posted_within_hours} placeholder="24"
              onChange={v => set('posted_within_hours', v)} />
          </Field>
        </div>
        <div style={{ marginTop: 12 }}>
          <Toggle
            checked={form.prefer_remote}
            onChange={v => set('prefer_remote', v)}
            label="Prefer remote"
          />
        </div>
      </div>

      <div style={s.hr} />

      {/* ── Sources ── */}
      <div style={s.group}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
          <div style={s.groupTitle}>Sources</div>
          <button
            type="button"
            onClick={() => {
              const next = !allOn
              setForm(f => ({ ...f, sources: Object.fromEntries(SOURCES.map(src => [src, next])) }))
            }}
            style={s.textBtn}
          >
            {allOn ? 'Deselect all' : 'Select all'}
          </button>
        </div>
        <div style={s.chips}>
          {SOURCES.map(src => {
            const on = form.sources[src]
            return (
              <button key={src} type="button" onClick={() => toggleSource(src)}
                style={{
                  ...s.chip,
                  background: on ? 'rgba(96,165,250,0.1)' : 'transparent',
                  color: on ? 'var(--accent)' : 'var(--text-dim)',
                  borderColor: on ? 'rgba(96,165,250,0.35)' : 'var(--border)',
                  fontWeight: on ? 600 : 400,
                }}>
                {SOURCE_LABELS[src]}
              </button>
            )
          })}
        </div>
      </div>

      {/* ── Submit ── */}
      <div style={s.footer}>
        <button
          type="submit"
          disabled={loading || !form.role.trim()}
          style={{
            ...s.submit,
            opacity: loading || !form.role.trim() ? 0.5 : 1,
            cursor: loading || !form.role.trim() ? 'not-allowed' : 'pointer',
          }}
        >
          {loading
            ? <><span style={s.spinner} /> Searching…</>
            : 'Search Jobs'
          }
        </button>
      </div>
    </form>
  )
}

const s = {
  group: { padding: '16px 18px' },
  groupTitle: {
    fontSize: 10,
    fontWeight: 700,
    letterSpacing: '0.08em',
    textTransform: 'uppercase',
    color: 'var(--text-dim)',
    marginBottom: 12,
  },
  hr: { height: 1, background: 'var(--border)' },
  cols2: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 },
  field: { display: 'flex', flexDirection: 'column', gap: 5, marginBottom: 10 },
  label: { fontSize: 11, color: 'var(--text-dim)', fontWeight: 500 },
  hint:  { fontSize: 11, color: 'var(--text-dim2)' },
  toggleRow: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 9,
    cursor: 'pointer',
  },
  track: {
    position: 'relative',
    width: 34,
    height: 19,
    borderRadius: 10,
    border: '1px solid',
    transition: 'background 0.2s, border-color 0.2s',
    flexShrink: 0,
  },
  thumb: {
    position: 'absolute',
    top: 2,
    width: 13,
    height: 13,
    borderRadius: '50%',
    background: '#fff',
    transition: 'transform 0.18s',
    boxShadow: '0 1px 2px rgba(0,0,0,0.4)',
  },
  chips: { display: 'flex', flexWrap: 'wrap', gap: 6 },
  chip: {
    padding: '5px 11px',
    borderRadius: 16,
    border: '1px solid',
    fontSize: 12,
    transition: 'all 0.12s',
  },
  textBtn: {
    background: 'transparent',
    color: 'var(--text-dim)',
    fontSize: 11,
    padding: 0,
    border: 'none',
    textDecoration: 'underline',
    textUnderlineOffset: 2,
  },
  footer: {
    padding: '12px 18px 16px',
  },
  submit: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 7,
    width: '100%',
    padding: '10px',
    background: 'var(--accent)',
    color: '#0a0d14',
    fontSize: 13,
    fontWeight: 700,
    borderRadius: 'var(--radius-sm)',
    transition: 'background 0.15s',
    letterSpacing: '0.01em',
  },
  spinner: {
    display: 'inline-block',
    width: 12, height: 12,
    borderRadius: '50%',
    border: '2px solid rgba(10,13,20,0.25)',
    borderTopColor: '#0a0d14',
    animation: 'spin 0.65s linear infinite',
    flexShrink: 0,
  },
}
