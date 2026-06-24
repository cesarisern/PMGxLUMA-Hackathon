import { useEffect, useRef, useState, type FC } from 'react'
import * as d3 from 'd3'
import * as topojson from 'topojson-client'

// ── Data (ported from analyze_state_trends.py + Maryland fix) ─────────────────
const SOCCER_PLAYERS: Record<string, number> = {
  California: 321000, Texas: 246863, 'New York': 183218, Massachusetts: 167402,
  Pennsylvania: 163423, 'New Jersey': 150978, Virginia: 144197, Florida: 113777,
  Washington: 110170, Maryland: 97268, Michigan: 92022, Ohio: 91505,
  Illinois: 80652, Georgia: 78943, Minnesota: 76668, Colorado: 73313,
  'North Carolina': 72999, Utah: 62972, Indiana: 61567, Wisconsin: 56474,
  Arizona: 51672, Tennessee: 49307, Kentucky: 37621, Oklahoma: 36222,
  Iowa: 32113, Missouri: 30147, Louisiana: 25782, Kansas: 25258,
  Arkansas: 25104, Oregon: 24811, 'Rhode Island': 22031, Nebraska: 21787,
  Mississippi: 21516, 'New Mexico': 20590, 'New Hampshire': 18949,
  Connecticut: 16841, Alabama: 15950, 'West Virginia': 15369,
  'South Dakota': 13752, Delaware: 13480, Idaho: 12645, Maine: 10867,
  Montana: 10635, Vermont: 7627, 'North Dakota': 7341, Wyoming: 5794,
  'South Carolina': 22372,
}

const NSCH_RATE: Record<string, number> = {
  Vermont: 71.5, 'South Dakota': 68.8, 'New Hampshire': 67.6,
  Massachusetts: 65.3, Iowa: 64.8,
  Texas: 49.0, 'West Virginia': 48.6, Florida: 48.4,
  Delaware: 47.7, Nevada: 43.3,
}

const NATIONAL_RATE = 55.4
const HIGH_VOL = 100_000
const MID_VOL = 50_000
const LOW_VOL = 25_000
const MAX_VOLUME = Math.max(...Object.values(SOCCER_PLAYERS))

function calcScore(state: string): number | null {
  const volume = SOCCER_PLAYERS[state]
  if (volume == null) return null
  const rate = NSCH_RATE[state]
  const volumeNorm = (volume / MAX_VOLUME) * 100
  const rateFactor = rate != null ? NATIONAL_RATE / rate : 1.0
  return volumeNorm * rateFactor
}

function calcTier(state: string): string {
  const volume = SOCCER_PLAYERS[state]
  if (volume == null) return ''
  const rate = NSCH_RATE[state]
  if (volume >= HIGH_VOL) {
    if (rate == null) return 'P1 launch'
    return rate < NATIONAL_RATE ? 'P1 launch · upside' : 'P1 showcase'
  }
  if (rate != null && rate >= NATIONAL_RATE) return 'efficient / skip'
  if (volume >= MID_VOL) return 'P2 core'
  if (volume >= LOW_VOL) return 'P3 secondary'
  return 'P4 long-tail'
}

const TOP_TABLE = Object.keys(SOCCER_PLAYERS)
  .map(state => ({
    state,
    volume: SOCCER_PLAYERS[state],
    rate: NSCH_RATE[state] as number | undefined,
    score: calcScore(state) ?? 0,
    tier: calcTier(state),
  }))
  .sort((a, b) => b.score - a.score)
  .slice(0, 12)

const TOTAL_PLAYERS = Object.values(SOCCER_PLAYERS).reduce((a, b) => a + b, 0)
const P1_COUNT = Object.keys(SOCCER_PLAYERS).filter(s => calcTier(s).startsWith('P1')).length

// ── Color helpers ─────────────────────────────────────────────────────────────
function scoreToColor(score: number | null): string {
  if (score == null) return '#3e404f'
  if (score >= 40) return '#1a3d72'
  if (score >= 20) return '#2b5ea7'
  if (score >= 10) return '#5b90cc'
  return '#8db8df'
}

function tierChipClass(tier: string): string {
  if (tier === 'P1 launch · upside') return 'pmg-status-chip pmg-status-running'
  if (tier === 'P1 showcase') return 'pmg-status-chip pmg-status-complete'
  if (tier.startsWith('P1')) return 'pmg-status-chip pmg-status-idle'
  if (tier === 'efficient / skip') return 'pmg-status-chip pmg-status-failed'
  return 'pmg-badge'
}

// ── Component ─────────────────────────────────────────────────────────────────
interface TooltipState { x: number; y: number; text: string }

export const CampaignAnalytics: FC = () => {
  const containerRef = useRef<HTMLDivElement>(null)
  const svgRef = useRef<SVGSVGElement>(null)
  const [tooltip, setTooltip] = useState<TooltipState | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    const W = 960, H = 600

    d3.json<Record<string, unknown>>('https://cdn.jsdelivr.net/npm/us-atlas@3/states-10m.json').then(topology => {
      if (controller.signal.aborted || !svgRef.current || !topology) return

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const states = topojson.feature(topology as any, (topology as any).objects.states) as GeoJSON.FeatureCollection
      const projection = d3.geoAlbersUsa().fitSize([W, H], states)
      const path = d3.geoPath().projection(projection)
      const svg = d3.select(svgRef.current)

      svg
        .selectAll<SVGPathElement, GeoJSON.Feature>('path.state')
        .data(states.features)
        .join('path')
        .attr('class', 'state')
        .attr('d', path)
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        .attr('fill', d => scoreToColor(calcScore((d.properties as any).name as string)))
        .attr('stroke', '#151824')
        .attr('stroke-width', 0.6)
        .on('mousemove', (event: MouseEvent, d) => {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const name = (d.properties as any).name as string
          const score = calcScore(name)
          const volume = SOCCER_PLAYERS[name]
          const rate = NSCH_RATE[name]
          const rect = containerRef.current?.getBoundingClientRect()
          setTooltip({
            x: event.clientX - (rect?.left ?? 0),
            y: event.clientY - (rect?.top ?? 0),
            text: [
              name,
              score != null ? `Score: ${score.toFixed(1)}` : 'Score: n/a',
              volume ? `${volume.toLocaleString()} players` : '',
              rate != null ? `${rate}% rate` : '',
            ].filter(Boolean).join(' · '),
          })
        })
        .on('mouseleave', () => setTooltip(null))
    }).catch(() => {/* map fails silently */})

    return () => controller.abort()
  }, [])

  const playerBase = TOTAL_PLAYERS >= 1_000_000
    ? `${(TOTAL_PLAYERS / 1_000_000).toFixed(2)}M`
    : TOTAL_PLAYERS.toLocaleString()

  return (
    <div className="space-y-6">
      {/* KPI cards */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {([
          { label: 'Start here', value: 'Texas + Florida' },
          { label: 'Player base', value: playerBase },
          { label: 'National rate', value: `${NATIONAL_RATE}%` },
          { label: 'P1 launch states', value: String(P1_COUNT) },
        ] as const).map(({ label, value }) => (
          <div key={label} className="pmg-panel p-4">
            <p className="text-xs text-[var(--pmg-muted)]">{label}</p>
            <p className="mt-1 text-xl font-semibold tracking-tight text-[var(--pmg-text)]">{value}</p>
          </div>
        ))}
      </div>

      {/* Choropleth map */}
      <div className="pmg-panel p-4">
        <div className="mb-3 flex flex-wrap gap-4 text-xs text-[var(--pmg-muted)]">
          {([
            { label: 'Highest (40+)', color: '#1a3d72' },
            { label: 'High (20–40)', color: '#2b5ea7' },
            { label: 'Medium (10–20)', color: '#5b90cc' },
            { label: 'Low (<10)', color: '#8db8df' },
            { label: 'No data', color: '#3e404f' },
          ] as const).map(({ label, color }) => (
            <span key={label} className="flex items-center gap-1.5">
              <span className="inline-block h-2.5 w-2.5 flex-shrink-0 rounded-sm" style={{ background: color }} />
              {label}
            </span>
          ))}
        </div>
        <div ref={containerRef} className="relative">
          <svg
            ref={svgRef}
            viewBox="0 0 960 600"
            preserveAspectRatio="xMidYMid meet"
            className="w-full"
            style={{ display: 'block' }}
          />
          {tooltip && (
            <div
              className="pointer-events-none absolute z-10 whitespace-nowrap rounded-lg px-3 py-1.5 text-xs shadow-lg"
              style={{
                background: 'var(--pmg-surface-2)',
                color: 'var(--pmg-text)',
                left: tooltip.x + 14,
                top: tooltip.y - 10,
              }}
            >
              {tooltip.text}
            </div>
          )}
        </div>
      </div>

      {/* Priority table */}
      <div className="pmg-panel p-4">
        <h2 className="mb-4 text-sm font-medium text-[var(--pmg-muted)]">Top launch markets</h2>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[520px] text-sm">
            <thead>
              <tr className="text-left text-xs text-[var(--pmg-muted)]">
                <th className="pb-3 pr-6 font-medium">#</th>
                <th className="pb-3 pr-6 font-medium">State</th>
                <th className="pb-3 pr-6 text-right font-medium">Players</th>
                <th className="pb-3 pr-6 text-right font-medium">Rate</th>
                <th className="pb-3 pr-6 text-right font-medium">Score</th>
                <th className="pb-3 font-medium">Tier</th>
              </tr>
            </thead>
            <tbody>
              {TOP_TABLE.map((row, i) => (
                <tr key={row.state} className="border-t border-[var(--pmg-border)]">
                  <td className="py-2.5 pr-6 text-[var(--pmg-muted)]">{i + 1}</td>
                  <td className="py-2.5 pr-6 font-medium text-[var(--pmg-text)]">{row.state}</td>
                  <td className="py-2.5 pr-6 text-right tabular-nums text-[var(--pmg-muted)]">
                    {row.volume.toLocaleString()}
                  </td>
                  <td className="py-2.5 pr-6 text-right tabular-nums text-[var(--pmg-muted)]">
                    {row.rate != null ? `${row.rate}%` : '—'}
                  </td>
                  <td className="py-2.5 pr-6 text-right tabular-nums font-semibold text-[var(--pmg-text)]">
                    {row.score.toFixed(1)}
                  </td>
                  <td className="py-2.5">
                    <span className={tierChipClass(row.tier)}>{row.tier}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Recommendation */}
      <div
        className="pmg-panel p-5"
        style={{ background: 'rgba(0,98,107,0.15)', borderLeft: '3px solid var(--pmg-accent-2)' }}
      >
        <h3
          className="mb-2 text-xs font-medium uppercase tracking-wider"
          style={{ color: 'var(--pmg-accent-2)' }}
        >
          Recommendation
        </h3>
        <p className="text-sm leading-relaxed text-[var(--pmg-text)]">
          Launch in <strong>Texas and Florida</strong>. They are the only large markets whose participation rate
          sits below the national average — a 113k–247k player base that is demonstrably under-converting, which
          is exactly the gap a localized "find a club in your state" message is built to close. Anchor paid spend
          and the first wave of dynamic-voice variants there, use{' '}
          <strong>Massachusetts, California and New York</strong> as high-volume showcase markets for social
          proof, and treat the small high-rate states (Vermont, the Dakotas, Maine) as efficiency skips — they
          are near participation ceiling and don't justify bespoke creative.
        </p>
      </div>
    </div>
  )
}
