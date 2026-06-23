import { useEffect, useMemo, useState } from 'react'

type Step = 1 | 2 | 3 | 4

type FeedBlob = { status: string; data: unknown } | null

type LocationFeed = { status: string; data: { locations: LocationOption[]; count: number }; count: number } | null

type RunResponse = {
  runId: number
  brand: string
  campaign: string
  status: 'running' | 'complete' | 'failed'
  error?: string
  feeds: {
    brand: FeedBlob
    context: FeedBlob
    trends: FeedBlob
    locations: LocationFeed
  }
}

type BriefPreviewResponse = {
  runId: number
  shared: {
    productName: string
    productDescription: string
    targetAudience: string
    toneOfScript: string
  }
  locations: { location: string; summary: string; payload: Record<string, unknown> }[]
}

type AudioResult = {
  location: string
  status: 'running' | 'complete' | 'timeout' | 'error'
  request?: { url: string; method: string; body: unknown }
  submitResponse?: { audioformId: string; raw: unknown } | null
  pollResponse?: {
    status: string
    raw: {
      data?: {
        result?: {
          assets?: Record<string, { uri?: string }>
        }
      }
    }
    deliveryUri?: string
    scriptText?: string
  } | null
  audioUrl?: string | null
  error?: string
}

type AudioStateResponse = {
  runId: number
  status: 'idle' | 'running' | 'complete' | 'failed'
  results: AudioResult[]
  error?: string
}

type LocationOption = {
  name: string
  type: string
  cta_suffix: string
  url: string | null
}

const rawApiBase = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim() || '/api'
const API_BASE = rawApiBase.endsWith('/') ? rawApiBase.slice(0, -1) : rawApiBase
const STEPS = ['Input', 'Feeds', 'Brief', 'Results']
const API_OFFLINE_HINT =
  `Cannot reach API (base: ${API_BASE}). ` +
  'If running locally, start it with: cd api && ../.venv/bin/uvicorn server:app --reload --port 8002. ' +
  'To use another host, set VITE_API_BASE_URL in ui/.env.'

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        'Content-Type': 'application/json',
        ...(init?.headers ?? {}),
      },
    })
  } catch {
    throw new Error(API_OFFLINE_HINT)
  }

  if (!res.ok) {
    const raw = await res.text()
    let detail = raw
    try {
      const json = JSON.parse(raw) as { detail?: string }
      if (typeof json.detail === 'string' && json.detail.trim().length > 0) {
        detail = json.detail
      }
    } catch {
      // Keep raw response text if it's not JSON.
    }
    throw new Error(detail || `Request failed with ${res.status}`)
  }
  return (await res.json()) as T
}

function App() {
  const [step, setStep] = useState<Step>(1)
  const [brand, setBrand] = useState('')
  const [campaign, setCampaign] = useState('')
  const [runId, setRunId] = useState<number | null>(null)
  const [runData, setRunData] = useState<RunResponse | null>(null)
  const [runError, setRunError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [selectedLocations, setSelectedLocations] = useState<string[]>([])
  const [briefPreview, setBriefPreview] = useState<BriefPreviewResponse | null>(null)
  const [briefError, setBriefError] = useState<string | null>(null)
  const [audioState, setAudioState] = useState<AudioStateResponse | null>(null)
  const [audioError, setAudioError] = useState<string | null>(null)

  const locationOptions = useMemo<LocationOption[]>(() => {
    const data = runData?.feeds.locations?.data
    return data?.locations ?? []
  }, [runData])

  useEffect(() => {
    if (step !== 2 || runId === null) {
      return
    }

    const load = async () => {
      try {
        const data = await apiFetch<RunResponse>(`/runs/${runId}`)
        setRunData(data)
        setRunError(data.error ?? null)
      } catch (error) {
        setRunError((error as Error).message)
      }
    }

    void load()
    const interval = window.setInterval(load, 2000)
    return () => window.clearInterval(interval)
  }, [runId, step])

  useEffect(() => {
    if (step !== 3 || runId === null || selectedLocations.length === 0) {
      return
    }

    const params = new URLSearchParams({ locations: selectedLocations.join(',') })
    apiFetch<BriefPreviewResponse>(`/runs/${runId}/brief-preview?${params.toString()}`)
      .then((data) => {
        setBriefPreview(data)
        setBriefError(null)
      })
      .catch((error) => {
        setBriefError((error as Error).message)
      })
  }, [runId, selectedLocations, step])

  useEffect(() => {
    if (step !== 4 || runId === null) {
      return
    }

    const load = async () => {
      try {
        const state = await apiFetch<AudioStateResponse>(`/runs/${runId}/audio`)
        setAudioState(state)
        setAudioError(state.error ?? null)
      } catch (error) {
        setAudioError((error as Error).message)
      }
    }

    void load()
    const interval = window.setInterval(load, 2000)
    return () => window.clearInterval(interval)
  }, [runId, step])

  const onSubmitRun = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (brand.trim().length < 3 || campaign.trim().length < 3) {
      setRunError('Brand and campaign must both be at least 3 characters.')
      return
    }

    try {
      setIsSubmitting(true)
      setRunError(null)
      const result = await apiFetch<{ runId: number; status: string }>('/runs', {
        method: 'POST',
        body: JSON.stringify({ brand: brand.trim(), campaign: campaign.trim() }),
      })
      setRunId(result.runId)
      setStep(2)
    } catch (error) {
      setRunError((error as Error).message)
    } finally {
      setIsSubmitting(false)
    }
  }

  const isContextWarning = useMemo(() => {
    const context = runData?.feeds.context?.data
    if (!context) return false
    const text = JSON.stringify(context).toLowerCase()
    return text.includes('api key') || text.includes('unavailable')
  }, [runData])

  const canContinueToStep3 =
    Boolean(runData?.feeds.brand?.data) &&
    Boolean(runData?.feeds.context?.data) &&
    Boolean(runData?.feeds.trends?.data) &&
    (runData?.feeds.locations?.count ?? 0) >= 1

  const goToStep3 = () => {
    const all = locationOptions.map((loc) => loc.name)
    setSelectedLocations(all)
    setStep(3)
  }

  const toggleLocation = (name: string) => {
    setSelectedLocations((current) =>
      current.includes(name) ? current.filter((item) => item !== name) : [...current, name],
    )
  }

  const startGeneration = async () => {
    if (!runId || selectedLocations.length === 0) return
    try {
      setAudioError(null)
      setAudioState({ runId, status: 'running', results: [] })
      await apiFetch(`/runs/${runId}/generate`, {
        method: 'POST',
        body: JSON.stringify({ locations: selectedLocations }),
      })
      setStep(4)
    } catch (error) {
      setAudioError((error as Error).message)
    }
  }

  const resetWizard = () => {
    setStep(1)
    setRunId(null)
    setRunData(null)
    setRunError(null)
    setSelectedLocations([])
    setBriefPreview(null)
    setBriefError(null)
    setAudioState(null)
    setAudioError(null)
  }

  return (
    <main className="mx-auto min-h-screen max-w-6xl bg-slate-50 px-6 py-8 text-slate-900">
      <h1 className="text-2xl font-semibold">Dynamic Voice Local Wizard</h1>
      <p className="mt-2 text-sm text-slate-600">Input - Feeds - Brief - Results</p>

      <div className="mt-6 flex flex-wrap gap-2">
        {STEPS.map((label, index) => {
          const current = index + 1 === step
          const complete = index + 1 < step
          return (
            <div
              key={label}
              className={`rounded-md border px-3 py-2 text-sm ${
                current
                  ? 'border-indigo-600 bg-indigo-50 text-indigo-700'
                  : complete
                    ? 'border-emerald-600 bg-emerald-50 text-emerald-700'
                    : 'border-slate-300 bg-white text-slate-500'
              }`}
            >
              {index + 1}. {label}
            </div>
          )
        })}
      </div>

      {step === 1 && (
        <section className="mt-8 rounded-lg border bg-white p-6 shadow-sm">
          <h2 className="text-lg font-medium">Step 1 - Campaign input</h2>
          <form className="mt-4 space-y-4" onSubmit={onSubmitRun}>
            <label className="block">
              <span className="mb-1 block text-sm font-medium">Brand (URL or name)</span>
              <input
                value={brand}
                onChange={(event) => {
                  setBrand(event.target.value)
                  if (runError) setRunError(null)
                }}
                className="w-full rounded-md border border-slate-300 px-3 py-2"
                placeholder="https://www.usyouthsoccer.org/"
                autoComplete="url"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-sm font-medium">Campaign</span>
              <textarea
                value={campaign}
                onChange={(event) => {
                  setCampaign(event.target.value)
                  if (runError) setRunError(null)
                }}
                className="min-h-28 w-full rounded-md border border-slate-300 px-3 py-2"
                placeholder="Spring youth soccer registration..."
              />
            </label>
            <p className="text-sm text-slate-500">
              Be specific - avoid generic phrases like &quot;Enroll now!&quot;
            </p>
            {runError ? <p className="text-sm text-rose-600">{runError}</p> : null}
            <button
              type="submit"
              disabled={isSubmitting}
              className="rounded-md bg-indigo-600 px-4 py-2 text-white disabled:opacity-50"
            >
              {isSubmitting ? 'Starting...' : 'Run feeds'}
            </button>
          </form>
        </section>
      )}

      {step === 2 && (
        <section className="mt-8 space-y-4">
          <h2 className="text-lg font-medium">Step 2 - Feed results</h2>
          <p className="text-sm text-slate-600">Polling run #{runId} every 2 seconds.</p>
          {runError ? <p className="text-sm text-rose-600">{runError}</p> : null}
          <div className="grid gap-4 md:grid-cols-2">
            <FeedCard title="Brand" feed={runData?.feeds.brand} summaryKeys={['brand_name', 'mission', 'tone_of_voice', 'cta']} />
            <FeedCard title="Campaign Context" feed={runData?.feeds.context} summaryKeys={['live_moment', 'campaign_angle']} warning={isContextWarning} />
            <FeedCard title="Trends" feed={runData?.feeds.trends} summaryKeys={['traffic_signal', 'website_traffic', 'search_trends']} />
            <FeedCard
              title="Locations"
              feed={runData?.feeds.locations}
              summaryKeys={[]}
              locationCount={runData?.feeds.locations?.count ?? 0}
            />
          </div>
          <button
            type="button"
            disabled={!canContinueToStep3}
            onClick={goToStep3}
            className="rounded-md bg-indigo-600 px-4 py-2 text-white disabled:cursor-not-allowed disabled:opacity-50"
          >
            Continue
          </button>
        </section>
      )}

      {step === 3 && (
        <section className="mt-8 grid gap-6 lg:grid-cols-[320px_1fr]">
          <div className="rounded-lg border bg-white p-4">
            <h2 className="text-lg font-medium">Step 3 - Select locations</h2>
            <p className="mt-1 text-sm text-slate-600">Choose one or more locations to generate.</p>
            <div className="mt-3 flex gap-2">
              <button
                type="button"
                className="rounded border px-2 py-1 text-xs"
                onClick={() => setSelectedLocations(locationOptions.map((loc) => loc.name))}
              >
                Select all
              </button>
              <button
                type="button"
                className="rounded border px-2 py-1 text-xs"
                onClick={() => setSelectedLocations([])}
              >
                Clear
              </button>
            </div>
            <div className="mt-3 max-h-80 space-y-2 overflow-y-auto rounded border p-2">
              {locationOptions.map((loc) => (
                <label key={loc.name} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={selectedLocations.includes(loc.name)}
                    onChange={() => toggleLocation(loc.name)}
                  />
                  <span>{loc.name}</span>
                  <span className="text-slate-400">({loc.cta_suffix})</span>
                </label>
              ))}
            </div>
            {selectedLocations.length === 0 && (
              <p className="mt-2 text-sm text-amber-700">Select at least one location.</p>
            )}
            <button
              type="button"
              disabled={selectedLocations.length === 0}
              onClick={() => {
                void startGeneration()
              }}
              className="mt-4 rounded-md bg-indigo-600 px-4 py-2 text-white disabled:opacity-50"
            >
              Generate ads
            </button>
          </div>
          <div className="rounded-lg border bg-white p-4">
            <h3 className="text-base font-medium">Brief preview (read-only)</h3>
            {briefError ? <p className="mt-2 text-sm text-rose-600">{briefError}</p> : null}
            {!briefPreview ? (
              <p className="mt-2 text-sm text-slate-500">Select locations to load preview.</p>
            ) : (
              <div className="mt-3 space-y-4">
                <div className="grid gap-2 text-sm md:grid-cols-2">
                  <Field label="productName" value={briefPreview.shared.productName} />
                  <Field label="targetAudience" value={briefPreview.shared.targetAudience} />
                  <Field label="toneOfScript" value={briefPreview.shared.toneOfScript} />
                </div>
                <Field label="productDescription" value={briefPreview.shared.productDescription} />
                {briefPreview.locations.map((loc) => (
                  <details key={loc.location} className="rounded border p-3">
                    <summary className="cursor-pointer text-sm font-medium">
                      {loc.location} - {loc.summary}
                    </summary>
                  </details>
                ))}
              </div>
            )}
          </div>
        </section>
      )}

      {step === 4 && (
        <section className="mt-8 space-y-4">
          <h2 className="text-lg font-medium">Step 4 - Generation results</h2>
          <p className="text-sm text-slate-600">Status: {audioState?.status ?? 'loading'}</p>
          {audioError ? <p className="text-sm text-rose-600">{audioError}</p> : null}
          <div className="space-y-4">
            {(audioState?.results ?? []).map((result) => (
              <article key={result.location} className="rounded-lg border bg-white p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="font-medium">{result.location}</h3>
                  <span className="rounded-full bg-slate-100 px-2 py-1 text-xs uppercase">
                    {result.status}
                  </span>
                </div>
                {result.error ? <p className="mt-2 text-sm text-rose-600">{result.error}</p> : null}
                {result.pollResponse?.scriptText ? (
                  <p className="mt-3 rounded bg-slate-100 p-2 text-sm">{result.pollResponse.scriptText}</p>
                ) : null}
                {result.audioUrl ? <audio controls src={result.audioUrl} className="mt-3 w-full" /> : null}
                {getAssetUris(result.pollResponse?.raw).map((uri) => (
                  <audio key={uri} controls src={uri} className="mt-2 w-full" />
                ))}
              </article>
            ))}
          </div>
          <button
            type="button"
            className="rounded-md border border-slate-300 px-4 py-2 text-slate-700"
            onClick={resetWizard}
          >
            Start over
          </button>
        </section>
      )}
    </main>
  )
}

function FeedCard({
  title,
  feed,
  summaryKeys,
  warning = false,
  locationCount,
}: {
  title: string
  feed: FeedBlob | LocationFeed | undefined
  summaryKeys: string[]
  warning?: boolean
  locationCount?: number
}) {
  const data = feed?.data as Record<string, unknown> | undefined
  return (
    <article className="rounded-lg border bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between gap-2">
        <h3 className="font-medium">{title}</h3>
        <span className="rounded bg-slate-100 px-2 py-1 text-xs">{feed?.status ?? 'pending'}</span>
      </div>
      {typeof locationCount === 'number' ? (
        <p className="mt-2 text-sm text-slate-600">Location count: {locationCount}</p>
      ) : null}
      {warning ? (
        <p className="mt-2 rounded bg-amber-100 px-2 py-1 text-xs text-amber-800">
          Warning: feed mentions API key or unavailable text.
        </p>
      ) : null}
      <div className="mt-3 space-y-1 text-sm">
        {summaryKeys.map((key) => (
          <p key={key}>
            <span className="font-medium">{key}:</span> {stringifyValue(data?.[key])}
          </p>
        ))}
      </div>
    </article>
  )
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <p className="text-sm">
      <span className="font-medium">{label}: </span>
      <span>{value || '-'}</span>
    </p>
  )
}

function stringifyValue(value: unknown): string {
  if (value === undefined || value === null) return '-'
  if (typeof value === 'string') return value
  if (Array.isArray(value)) return value.join(', ')
  return JSON.stringify(value)
}

function getAssetUris(raw: unknown): string[] {
  const assetMap = (raw as { data?: { result?: { assets?: Record<string, { uri?: string }> } } })?.data?.result
    ?.assets
  if (!assetMap) return []
  return Object.values(assetMap)
    .map((asset) => asset?.uri)
    .filter((uri): uri is string => Boolean(uri))
}

export default App
