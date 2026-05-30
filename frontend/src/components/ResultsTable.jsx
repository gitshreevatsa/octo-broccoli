import { useMemo, useState } from 'react'
import {
  useReactTable, getCoreRowModel, getSortedRowModel,
  getFilteredRowModel, flexRender,
} from '@tanstack/react-table'

const SOURCE_COLORS = {
  linkedin: '#0a66c2', indeed: '#003a9b', glassdoor: '#0caa41',
  jobicy: '#e05d2b', remoteok: '#1a9e4a', weworkremotely: '#1f8ee1',
}

function ScoreBar({ score }) {
  if (score === null || score === undefined) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <div style={{ width: 60, height: 6, background: 'var(--surface2)', borderRadius: 3 }} />
        <span style={{ color: 'var(--text-dim)', fontSize: 12 }}>…</span>
      </div>
    )
  }
  const pct = score / 100
  const color = pct >= 0.75 ? 'var(--green)' : pct >= 0.5 ? 'var(--yellow)' : 'var(--red)'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{ width: 60, height: 6, background: 'var(--surface2)', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ width: `${pct * 100}%`, height: '100%', background: color, borderRadius: 3 }} />
      </div>
      <span style={{ color, fontWeight: 600, fontSize: 13 }}>{score}%</span>
    </div>
  )
}

function SourceBadge({ source }) {
  const color = SOURCE_COLORS[source] || '#555'
  return (
    <span style={{
      background: color + '22', color, border: `1px solid ${color}55`,
      borderRadius: 4, padding: '2px 7px', fontSize: 11, fontWeight: 600,
      textTransform: 'capitalize', whiteSpace: 'nowrap',
    }}>
      {source}
    </span>
  )
}

export default function ResultsTable({ jobs }) {
  const [globalFilter, setGlobalFilter] = useState('')
  const [sorting, setSorting] = useState([{ id: 'score', desc: true }])

  const columns = useMemo(() => [
    {
      id: 'rank',
      header: '#',
      accessorKey: 'rank',
      size: 44,
      cell: info => <span style={{ color: 'var(--text-dim)' }}>{info.getValue()}</span>,
    },
    {
      id: 'score',
      header: 'Score',
      accessorKey: 'score',
      size: 110,
      cell: info => <ScoreBar score={info.getValue()} />,
    },
    {
      id: 'title',
      header: 'Title',
      accessorKey: 'title',
      cell: info => (
        <a href={info.row.original.url} target="_blank" rel="noreferrer"
          style={{ fontWeight: 600, color: 'var(--text)' }}>
          {info.getValue()}
        </a>
      ),
    },
    {
      id: 'company',
      header: 'Company',
      accessorKey: 'company',
      size: 160,
    },
    {
      id: 'location',
      header: 'Location',
      accessorKey: 'location',
      size: 160,
      cell: info => (
        <span>
          {info.getValue()}
          {info.row.original.remote && (
            <span style={{ marginLeft: 6, color: 'var(--green)', fontSize: 11, fontWeight: 600 }}>remote</span>
          )}
        </span>
      ),
    },
    {
      id: 'salary',
      header: 'Salary',
      accessorFn: row => row.salary_min || 0,
      size: 140,
      cell: info => {
        const { salary_min: mn, salary_max: mx } = info.row.original
        if (!mn && !mx) return <span style={{ color: 'var(--text-dim)' }}>—</span>
        const fmt = n => `$${(n / 1000).toFixed(0)}k`
        return <span style={{ color: 'var(--green)', fontWeight: 500 }}>
          {mn && mx ? `${fmt(mn)} – ${fmt(mx)}` : mn ? `${fmt(mn)}+` : `up to ${fmt(mx)}`}
        </span>
      },
    },
    {
      id: 'posted',
      header: 'Posted',
      accessorFn: row => row.posted_days_ago ?? 9999,
      size: 90,
      cell: info => {
        const d = info.row.original.posted_days_ago
        if (d === null || d === undefined) return <span style={{ color: 'var(--text-dim)' }}>?</span>
        if (d === 0) return <span style={{ color: 'var(--green)', fontWeight: 600 }}>Today</span>
        if (d === 1) return <span style={{ color: 'var(--green)' }}>1d ago</span>
        return <span style={{ color: d > 14 ? 'var(--text-dim)' : 'var(--text)' }}>{d}d ago</span>
      },
    },
    {
      id: 'source',
      header: 'Source',
      accessorKey: 'source',
      size: 110,
      cell: info => <SourceBadge source={info.getValue()} />,
    },
    {
      id: 'apply',
      header: 'Apply',
      accessorKey: 'url',
      size: 70,
      enableSorting: false,
      cell: info => (
        <a href={info.getValue()} target="_blank" rel="noreferrer" style={styles.applyBtn}>
          Apply →
        </a>
      ),
    },
  ], [])

  const table = useReactTable({
    data: jobs,
    columns,
    state: { sorting, globalFilter },
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  })

  return (
    <div>
      <div style={styles.toolbar}>
        <span style={styles.count}>{table.getRowModel().rows.length} jobs</span>
        <input
          value={globalFilter}
          onChange={e => setGlobalFilter(e.target.value)}
          placeholder="Filter by title, company, location…"
          style={{ ...styles.filter }}
        />
      </div>

      <div style={styles.tableWrap}>
        <table style={styles.table}>
          <thead>
            {table.getHeaderGroups().map(hg => (
              <tr key={hg.id}>
                {hg.headers.map(h => (
                  <th
                    key={h.id}
                    style={{ ...styles.th, width: h.column.getSize(), cursor: h.column.getCanSort() ? 'pointer' : 'default' }}
                    onClick={h.column.getToggleSortingHandler()}
                  >
                    {flexRender(h.column.columnDef.header, h.getContext())}
                    {h.column.getIsSorted() === 'asc' ? ' ↑' : h.column.getIsSorted() === 'desc' ? ' ↓' : ''}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row, i) => (
              <tr key={row.id} style={{ background: i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.02)' }}>
                {row.getVisibleCells().map(cell => (
                  <td key={cell.id} style={styles.td}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

const styles = {
  toolbar: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    marginBottom: 12,
  },
  count: {
    color: 'var(--text-dim)',
    fontSize: 13,
    whiteSpace: 'nowrap',
  },
  filter: {
    maxWidth: 320,
    padding: '7px 12px',
  },
  tableWrap: {
    overflowX: 'auto',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius)',
  },
  table: {
    width: '100%',
    borderCollapse: 'collapse',
    fontSize: 13,
  },
  th: {
    padding: '10px 14px',
    textAlign: 'left',
    background: 'var(--surface)',
    color: 'var(--text-dim)',
    fontWeight: 600,
    fontSize: 11,
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
    borderBottom: '1px solid var(--border)',
    whiteSpace: 'nowrap',
    userSelect: 'none',
  },
  td: {
    padding: '10px 14px',
    borderBottom: '1px solid var(--border)',
    verticalAlign: 'middle',
    maxWidth: 280,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  applyBtn: {
    color: 'var(--accent)',
    fontWeight: 600,
    fontSize: 12,
    whiteSpace: 'nowrap',
  },
}
