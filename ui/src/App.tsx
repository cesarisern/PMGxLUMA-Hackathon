import { type ReactNode, useEffect, useMemo, useState } from 'react'
import { CampaignAnalytics } from './CampaignAnalytics'

type Step = 1 | 2 | 3 | 4
type BriefTab = 'brief' | 'targeting'

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

type ImageStateResponse = {
  runId: number
  status: 'idle' | 'running' | 'generating_clips' | 'complete' | 'failed' | 'clips_failed'
  imageUrl: string | null
  imageUrl1x1: string | null
  clipUrls: string[] | null
  prompt: string | null
  error?: string
}

type VideoResult = {
  location: string
  audioform_id: string
  video_filename: string
  videoUrl: string | null
  status: 'complete' | 'failed'
  error?: string
}

type VideoStateResponse = {
  runId: number
  status: 'idle' | 'running' | 'complete' | 'failed'
  results: VideoResult[]
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
const FEED_ORDER = ['Brand', 'Campaign Context', 'Trends', 'Locations'] as const
const FEED_LOADING_TEXT = {
  brand: [
    'Reading website...',
    'Understanding brand...',
    'Extracting insights...',
    'Identifying strengths...',
    'Building profile...',
  ],
  context: [
    'Reading brief...',
    'Understanding goals...',
    'Identifying audience...',
    'Mapping objectives...',
    'Building strategy...',
  ],
  trends: [
    'Scanning signals...',
    'Analyzing trends...',
    'Finding opportunities...',
    'Tracking momentum...',
    'Ranking insights...',
  ],
  locations: [
    'Discovering markets...',
    'Mapping regions...',
    'Finding locations...',
    'Evaluating reach...',
    'Prioritizing targets...',
  ],
} as const
const FIELD_LABEL_OVERRIDES: Record<string, string> = {
  cta: 'CTA',
  cta_suffix: 'CTA Suffix',
  geo: 'Region',
  brand_url: 'Brand URL',
}
const API_OFFLINE_HINT =
  `Cannot reach API (base: ${API_BASE}). ` +
  'If running locally, start it with: cd api && uvicorn server:app --reload --port 8002. ' +
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
  const [briefTab, setBriefTab] = useState<BriefTab>('brief')
  const [brand, setBrand] = useState('')
  const [campaign, setCampaign] = useState('')
  const [runId, setRunId] = useState<number | null>(null)
  const [runData, setRunData] = useState<RunResponse | null>(null)
  const [runError, setRunError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isSuggestingCampaign, setIsSuggestingCampaign] = useState(false)
  const [selectedLocations, setSelectedLocations] = useState<string[]>([])
  const [briefPreview, setBriefPreview] = useState<BriefPreviewResponse | null>(null)
  const [briefError, setBriefError] = useState<string | null>(null)
  const [audioState, setAudioState] = useState<AudioStateResponse | null>(null)
  const [audioError, setAudioError] = useState<string | null>(null)
  const [imageState, setImageState] = useState<ImageStateResponse | null>(null)
  const [videoState, setVideoState] = useState<VideoStateResponse | null>(null)

  const locationOptions = useMemo<LocationOption[]>(() => {
    const data = runData?.feeds.locations?.data
    return data?.locations ?? []
  }, [runData])

  // Poll run feeds in Step 2
  useEffect(() => {
    if (step !== 2 || runId === null) return
    const load = async () => {
      const currentRunId = runId
      try {
        const data = await apiFetch<RunResponse>(`/runs/${runId}`)
        if (runId !== currentRunId) return
        setRunData(data)
        setRunError(data.error ?? null)
      } catch (error) {
        if (runId !== currentRunId) return
        setRunError((error as Error).message)
      }
    }
    void load()
    const interval = window.setInterval(load, 2000)
    return () => window.clearInterval(interval)
  }, [runId, step])

  // Poll image/clip state in Steps 2–4
  useEffect(() => {
    if ((step !== 2 && step !== 4) || runId === null) return
    const load = async () => {
      try {
        const state = await apiFetch<ImageStateResponse>(`/runs/${runId}/image`)
        setImageState(state)
      } catch {
        // non-fatal
      }
    }
    void load()
    const interval = window.setInterval(load, 3000)
    return () => window.clearInterval(interval)
  }, [runId, step])

  // Load brief preview in Step 3
  useEffect(() => {
    if (step !== 3 || runId === null || selectedLocations.length === 0) return
    const currentRunId = runId
    const params = new URLSearchParams({ locations: selectedLocations.join(',') })
    apiFetch<BriefPreviewResponse>(`/runs/${runId}/brief-preview?${params.toString()}`)
      .then((data) => {
        if (runId !== currentRunId) return
        setBriefPreview(data)
        setBriefError(null)
      })
      .catch((error) => {
        if (runId !== currentRunId) return
        setBriefError((error as Error).message)
      })
  }, [runId, selectedLocations, step])

  // Poll audio and video state in Step 4
  useEffect(() => {
    if (step !== 4 || runId === null) return

    const loadAudio = async () => {
      const currentRunId = runId
      try {
        const state = await apiFetch<AudioStateResponse>(`/runs/${runId}/audio`)
        if (runId !== currentRunId) return
        setAudioState(state)
        setAudioError(state.error ?? null)
      } catch (error) {
        if (runId !== currentRunId) return
        setAudioError((error as Error).message)
      }
    }
    const loadVideo = async () => {
      try {
        const state = await apiFetch<VideoStateResponse>(`/runs/${runId}/video`)
        setVideoState(state)
      } catch {
        // non-fatal
      }
    }

    void loadAudio()
    void loadVideo()
    const audioInterval = window.setInterval(loadAudio, 2000)
    const videoInterval = window.setInterval(loadVideo, 3000)
    return () => {
      window.clearInterval(audioInterval)
      window.clearInterval(videoInterval)
    }
  }, [runId, step])

  const suggestCampaign = async () => {
    if (brand.trim().length < 3) return
    setIsSuggestingCampaign(true)
    try {
      const result = await apiFetch<{ suggestion: string }>('/suggest-campaign-name', {
        method: 'POST',
        body: JSON.stringify({ brand: brand.trim() }),
      })
      setCampaign(result.suggestion)
    } catch (error) {
      setRunError((error as Error).message)
    } finally {
      setIsSuggestingCampaign(false)
    }
  }

  const onSubmitRun = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (brand.trim().length < 3 || campaign.trim().length < 3) {
      setRunError('Brand and campaign must both be at least 3 characters.')
      return
    }

    try {
      setIsSubmitting(true)
      setRunError(null)
      setRunData(null)
      setSelectedLocations([])
      setBriefPreview(null)
      setBriefError(null)
      setAudioState(null)
      setAudioError(null)
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

  const isFeedsReady = runData?.status === 'complete'
  const runFailed = runData?.status === 'failed'
  const brandReady = Boolean(runData?.feeds.brand?.data)
  const contextReady = Boolean(runData?.feeds.context?.data)
  const trendsReady = Boolean(runData?.feeds.trends?.data)
  const locationsReady = (runData?.feeds.locations?.count ?? 0) > 0
  const feedProgress = [
    { label: 'Brand', ready: brandReady },
    { label: 'Campaign Context', ready: contextReady },
    { label: 'Trends', ready: trendsReady },
    { label: 'Locations', ready: locationsReady },
  ]
  const readyFeedCount = feedProgress.filter((feed) => feed.ready).length

  const canContinueToStep3 =
    isFeedsReady &&
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
    setImageState(null)
    setVideoState(null)
  }

  const productName = briefPreview?.shared.productName || runData?.brand || ''

  return (
    <main className="mx-auto min-h-screen max-w-6xl px-6 py-10">
      <section className="pmg-panel p-6 md:p-8">
        <p className="pmg-kicker">RESONATE</p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight text-[var(--pmg-text)] md:text-4xl">
          Dynamic Localization
        </h1>
        <p className="mt-3 max-w-2xl text-sm text-[var(--pmg-muted)] md:text-base">
          Build localized voice creative through a guided flow: collect feed intelligence, review brief data, and
          generate location-specific audio results.
        </p>
      </section>

      <div className="mt-6 flex flex-wrap gap-2">
        {STEPS.map((label, index) => {
          const current = index + 1 === step
          const complete = index + 1 < step
          return (
            <div
              key={label}
              className={`pmg-step ${current ? 'pmg-step-current' : complete ? 'pmg-step-complete' : 'pmg-step-idle'}`}
            >
              {index + 1}. {label}
            </div>
          )
        })}
      </div>

      {step === 1 && (
        <section className="pmg-panel mt-8 p-6">
          <h2 className="text-lg font-medium text-[var(--pmg-text)]">Step 1 - Campaign input</h2>
          <form className="mt-4 space-y-4" onSubmit={onSubmitRun}>
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-[var(--pmg-muted)]">Brand (URL or name)</span>
              <input
                value={brand}
                onChange={(event) => {
                  setBrand(event.target.value)
                  if (runError) setRunError(null)
                }}
                className="pmg-input px-3 py-2"
                placeholder="https://www.usyouthsoccer.org/"
                autoComplete="url"
              />
            </label>
            <label className="block">
              <div className="mb-1 flex items-center justify-between gap-2">
                <span className="text-sm font-medium text-[var(--pmg-muted)]">Campaign description</span>
                <button
                  type="button"
                  disabled={brand.trim().length < 3 || isSuggestingCampaign}
                  onClick={() => { void suggestCampaign() }}
                  className="pmg-button-secondary px-2 py-0.5 text-xs"
                >
                  {isSuggestingCampaign ? 'Generating...' : 'Suggest'}
                </button>
              </div>
              <textarea
                value={campaign}
                onChange={(event) => {
                  setCampaign(event.target.value)
                  if (runError) setRunError(null)
                }}
                className="pmg-input min-h-28 px-3 py-2"
                placeholder="Spring youth soccer registration..."
              />
            </label>

            {runError ? <p className="pmg-alert-error rounded-xl px-3 py-2 text-sm">{runError}</p> : null}
            <button
              type="submit"
              disabled={isSubmitting}
              className="pmg-button-primary px-4 py-2 text-sm font-medium"
            >
              {isSubmitting ? 'Starting...' : 'Run feeds'}
            </button>
          </form>
        </section>
      )}

      {step === 2 && (
        <section className="mt-8 space-y-4" key={runId ?? 'no-run'}>
          <h2 className="text-lg font-medium text-[var(--pmg-text)]">Step 2 - Feed results</h2>
          <FeedStatusPanel
            feedProgress={feedProgress}
            isFeedsReady={isFeedsReady}
            runFailed={runFailed}
            locationCount={runData?.feeds.locations?.count ?? 0}
          />
          {runError ? <p className="pmg-alert-error rounded-xl px-3 py-2 text-sm">{runError}</p> : null}
          <div className="grid gap-4 md:grid-cols-2">
            <FeedCard
              title={`1. ${FEED_ORDER[0]}`}
              feed={runData?.feeds.brand}
              summaryKeys={['brand_name', 'mission', 'tone_of_voice', 'cta']}
              revealData={isFeedsReady && brandReady}
              statusOverride={runFailed ? 'failed' : isFeedsReady && brandReady ? 'complete' : 'running'}
              loadingTexts={FEED_LOADING_TEXT.brand}
            />
            <FeedCard
              title={`2. ${FEED_ORDER[1]}`}
              feed={runData?.feeds.context}
              summaryKeys={['live_moment', 'campaign_angle']}
              warning={isFeedsReady && contextReady && isContextWarning}
              revealData={isFeedsReady && contextReady}
              statusOverride={runFailed ? 'failed' : isFeedsReady && contextReady ? 'complete' : 'running'}
              loadingTexts={FEED_LOADING_TEXT.context}
            />
            <FeedCard
              title={`3. ${FEED_ORDER[2]}`}
              feed={runData?.feeds.trends}
              summaryKeys={['traffic_signal', 'website_traffic', 'search_trends']}
              revealData={isFeedsReady && trendsReady}
              statusOverride={runFailed ? 'failed' : isFeedsReady && trendsReady ? 'complete' : 'running'}
              loadingTexts={FEED_LOADING_TEXT.trends}
            />
            <FeedCard
              title={`4. ${FEED_ORDER[3]}`}
              feed={runData?.feeds.locations}
              summaryKeys={[]}
              locationCount={runData?.feeds.locations?.count ?? 0}
              locationNames={locationOptions.slice(0, 20).map((location) => location.name)}
              revealData={isFeedsReady && locationsReady}
              statusOverride={runFailed ? 'failed' : isFeedsReady && locationsReady ? 'complete' : 'running'}
              loadingTexts={FEED_LOADING_TEXT.locations}
            />
          </div>
          {imageState && imageState.status !== 'idle' && (
            <div className="pmg-panel-muted p-4 text-sm">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2.5">
                  {imageState.status === 'failed' ? (
                    <div
                      className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full"
                      style={{ background: 'rgba(234, 120, 122, 0.15)' }}
                    >
                      <svg viewBox="0 0 16 16" fill="none" className="h-4 w-4" style={{ color: 'var(--pmg-danger)' }}>
                        <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                      </svg>
                    </div>
                  ) : imageState.imageUrl ? (
                    <div
                      className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full"
                      style={{ background: 'rgba(120, 192, 166, 0.18)' }}
                    >
                      <svg viewBox="0 0 16 16" fill="none" className="h-4 w-4" style={{ color: 'var(--pmg-success)' }}>
                        <path d="M3 8.5l3.5 3L13 5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    </div>
                  ) : (
                    <div className="relative h-8 w-8 flex-shrink-0">
                      <div
                        className="pmg-spin-slow absolute inset-0 rounded-full"
                        style={{ background: 'conic-gradient(from 0deg, var(--pmg-accent) 0%, var(--pmg-accent-2) 35%, transparent 65%)' }}
                      />
                      <div className="absolute inset-[2px] flex items-center justify-center rounded-full" style={{ background: 'var(--pmg-surface-2)' }}>
                        <svg viewBox="0 0 16 16" fill="none" className="h-3.5 w-3.5" style={{ color: 'var(--pmg-accent)' }}>
                          <rect x="1" y="3" width="14" height="10" rx="2" stroke="currentColor" strokeWidth="1.4" />
                          <circle cx="5.5" cy="7" r="1.1" fill="currentColor" opacity="0.7" />
                          <path d="M1.5 11l3.5-3 2.5 2.5 2-2 4.5 3" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                      </div>
                    </div>
                  )}
                  <span className="text-xs" style={{ color: imageState.imageUrl ? 'var(--pmg-success)' : imageState.status === 'failed' ? 'var(--pmg-danger)' : 'var(--pmg-muted)' }}>
                    {imageState.status === 'failed' ? 'Image failed'
                      : imageState.imageUrl ? 'Image ready'
                      : 'Generating image...'}
                  </span>
                </div>
                {(imageState.status === 'generating_clips' || imageState.status === 'complete' || imageState.status === 'clips_failed') && (
                  <span className="text-xs" style={{ color: imageState.status === 'clips_failed' ? 'var(--pmg-danger)' : imageState.status === 'complete' ? 'var(--pmg-success)' : 'var(--pmg-muted)' }}>
                    {imageState.status === 'complete' ? `${imageState.clipUrls?.length ?? 0} clips ready`
                      : imageState.status === 'clips_failed' ? 'Clips failed'
                      : 'Generating clips...'}
                  </span>
                )}
              </div>
              {imageState.error && (
                <p className="pmg-alert-error mt-2 rounded-xl px-3 py-2 text-xs">{imageState.error}</p>
              )}
            </div>
          )}
          <button
            type="button"
            disabled={!canContinueToStep3}
            onClick={goToStep3}
            className="pmg-button-primary px-4 py-2 text-sm font-medium"
          >
            {isFeedsReady ? 'Continue' : 'Continue (waiting for feeds...)'}
          </button>
        </section>
      )}

      {step === 3 && (
        <section className="mt-8 grid gap-6 lg:grid-cols-[320px_1fr]">
          <div className="pmg-panel p-4">
            <h2 className="text-lg font-medium text-[var(--pmg-text)]">Step 3 - Select locations</h2>
            <p className="mt-1 text-sm text-[var(--pmg-muted)]">Choose one or more locations to generate.</p>
            <div className="mt-3 flex gap-2">
              <button
                type="button"
                className="pmg-button-secondary px-2 py-1 text-xs"
                onClick={() => setSelectedLocations(locationOptions.map((loc) => loc.name))}
              >
                Select all
              </button>
              <button
                type="button"
                className="pmg-button-secondary px-2 py-1 text-xs"
                onClick={() => setSelectedLocations([])}
              >
                Clear
              </button>
            </div>
            <div className="pmg-panel-muted mt-3 max-h-80 space-y-2 overflow-y-auto p-2">
              {locationOptions.map((loc) => (
                <label key={loc.name} className="flex items-center gap-2 rounded-lg px-2 py-1 text-sm hover:bg-white/5">
                  <input
                    type="checkbox"
                    checked={selectedLocations.includes(loc.name)}
                    onChange={() => toggleLocation(loc.name)}
                    className="accent-[var(--pmg-accent)]"
                  />
                  <span>{loc.name}</span>
                  <span className="text-[var(--pmg-muted)]">({loc.cta_suffix})</span>
                </label>
              ))}
            </div>
            {selectedLocations.length === 0 && (
              <p className="pmg-alert-warning mt-2 rounded-xl px-3 py-2 text-sm">Select at least one location.</p>
            )}
            <button
              type="button"
              disabled={selectedLocations.length === 0}
              onClick={() => { void startGeneration() }}
              className="pmg-button-primary mt-4 px-4 py-2 text-sm font-medium"
            >
              Generate ads
            </button>
          </div>
          <div className="pmg-panel overflow-hidden">
            <div className="flex items-center justify-between border-b border-[var(--pmg-border)] px-4 py-3">
              <h3 className="text-sm font-semibold text-[var(--pmg-text)]">Campaign intelligence</h3>
              <div className="pmg-tab-bar">
                <button
                  type="button"
                  className={briefTab === 'brief' ? 'pmg-tab-active' : 'pmg-tab'}
                  onClick={() => setBriefTab('brief')}
                >
                  Creative brief
                </button>
                <button
                  type="button"
                  className={briefTab === 'targeting' ? 'pmg-tab-active' : 'pmg-tab'}
                  onClick={() => setBriefTab('targeting')}
                >
                  Targeting recommendation
                </button>
              </div>
            </div>
            <div className="p-4">
              {briefTab === 'targeting' ? (
                <CampaignAnalytics />
              ) : briefError ? (
                <p className="pmg-alert-error rounded-xl px-3 py-2 text-sm">{briefError}</p>
              ) : !briefPreview ? (
                <p className="mt-2 text-sm text-[var(--pmg-muted)]">Select locations to load preview.</p>
              ) : (
                <div className="space-y-4">
                  <div className="grid gap-2 text-sm md:grid-cols-2">
                    <Field label="productName" value={briefPreview.shared.productName} />
                    <Field label="targetAudience" value={briefPreview.shared.targetAudience} />
                    <Field label="toneOfScript" value={briefPreview.shared.toneOfScript} />
                  </div>
                  <Field label="productDescription" value={briefPreview.shared.productDescription} />
                  {briefPreview.locations.map((loc) => (
                    <details key={loc.location} className="pmg-panel-muted">
                      <summary className="cursor-pointer list-none px-3 py-2.5 text-sm font-medium text-[var(--pmg-text)]">
                        {loc.location}
                      </summary>
                      <p className="px-3 pb-3 text-sm text-[var(--pmg-muted)]">{loc.summary}</p>
                    </details>
                  ))}
                </div>
              )}
            </div>
          </div>
        </section>
      )}

      {step === 4 && (
        <section className="mt-8 space-y-6">
          <h2 className="text-lg font-medium text-[var(--pmg-text)]">Step 4 - Generation results</h2>

          {<>
          {/* Full-screen loading hero — shown before any results arrive */}
          {audioState?.status === 'running' && audioState.results.length === 0 && (
            <GenerationLoadingHero
              locationCount={selectedLocations.length}
              imageState={imageState}
              audioState={audioState}
            />
          )}

          {/* Campaign visual card */}
          {imageState && imageState.status !== 'idle' && (
            <div className="pmg-panel overflow-hidden">
              <div className="flex items-start gap-5 p-5">
                {/* Image thumbnail or skeleton */}
                <div
                  className="relative flex-shrink-0 overflow-hidden rounded-xl"
                  style={{ width: '7rem', aspectRatio: '9 / 16' }}
                >
                  {imageState.imageUrl ? (
                    <img
                      src={imageState.imageUrl}
                      alt="Campaign visual"
                      className="absolute inset-0 h-full w-full object-cover"
                    />
                  ) : (
                    <div className="pmg-shimmer absolute inset-0 rounded-xl" />
                  )}
                </div>

                <div className="flex min-w-0 flex-1 flex-col gap-3 py-1">
                  <div>
                    {imageState.imageUrl ? (
                      <>
                        <p className="pmg-kicker">Campaign visual</p>
                        <h3 className="mt-1.5 text-xl font-semibold tracking-tight text-[var(--pmg-text)]">
                          {productName}
                        </h3>
                        {runData?.campaign && (
                          <p className="mt-1.5 line-clamp-3 text-sm text-[var(--pmg-muted)]">{runData.campaign}</p>
                        )}
                      </>
                    ) : (
                      <>
                        <div className="pmg-shimmer h-3 w-20 rounded-full" />
                        <div className="pmg-shimmer mt-2.5 h-5 w-40 rounded-full" />
                        <div className="pmg-shimmer mt-2 h-3 w-56 rounded-full" />
                        <div className="pmg-shimmer mt-1.5 h-3 w-48 rounded-full" />
                      </>
                    )}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {imageState.imageUrl ? (
                      <>
                        <DownloadLink
                          href={`${API_BASE}/proxy-download?url=${encodeURIComponent(imageState.imageUrl)}&filename=campaign-visual-9x16.jpg`}
                          filename="campaign-visual-9x16.jpg"
                        >
                          Download 9:16 (Social)
                        </DownloadLink>
                        {imageState.imageUrl1x1 && (
                          <DownloadLink
                            href={`${API_BASE}${imageState.imageUrl1x1}`}
                            filename="campaign-visual-1x1.jpg"
                          >
                            Download 1:1 (Spotify)
                          </DownloadLink>
                        )}
                      </>
                    ) : (
                      <>
                        <div className="pmg-shimmer h-8 w-36 rounded-xl" />
                        <div className="pmg-shimmer h-8 w-32 rounded-xl" />
                      </>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Video generation status banner */}
          {videoState && videoState.status !== 'idle' && (
            <div className="pmg-panel-muted flex items-center gap-3 px-4 py-3 text-sm">
              <span className={`pmg-status-chip inline-flex items-center gap-1.5 ${statusChipClass(videoState.status)}`}>
                {videoState.status === 'running' && (
                  <span className="relative flex h-1.5 w-1.5 flex-shrink-0">
                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#b8d8fa] opacity-75" />
                    <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-[#b8d8fa]" />
                  </span>
                )}
                {videoState.status}
              </span>
              <span className="text-[var(--pmg-muted)]">
                {videoState.status === 'running'
                  ? 'Video generation in progress — assembling clips and audio...'
                  : videoState.status === 'complete'
                    ? `${videoState.results.filter((r) => r.status === 'complete').length} video(s) ready`
                    : videoState.error ?? 'Video generation failed'}
              </span>
            </div>
          )}

          {/* Per-location audio + video results */}
          {audioError ? <p className="pmg-alert-error rounded-xl px-3 py-2 text-sm">{audioError}</p> : null}
          <div className="space-y-4">
            {(audioState?.results ?? []).map((result) => {
              const videoResult = videoState?.results.find((v) => v.location === result.location) ?? null
              return (
                <LocationResultCard
                  key={result.location}
                  audioResult={result}
                  videoResult={videoResult}
                  videoGenerating={videoState?.status === 'running'}
                  apiBase={API_BASE}
                />
              )
            })}
          </div>

          <button
            type="button"
            className="pmg-button-secondary px-4 py-2 text-sm"
            onClick={resetWizard}
          >
            Start over
          </button>
          </>}
        </section>
      )}
    </main>
  )
}

function GenerationLoadingHero({
  locationCount,
  imageState,
  audioState,
}: {
  locationCount: number
  imageState: ImageStateResponse | null
  audioState: AudioStateResponse | null
}) {
  const [statusIndex, setStatusIndex] = useState(0)

  const STATUS_MESSAGES = [
    'Analyzing campaign brief...',
    'Writing location-specific scripts...',
    'Producing audio with AudioStack...',
    'Preparing visual assets...',
  ]

  useEffect(() => {
    const timer = setInterval(() => {
      setStatusIndex((i) => (i + 1) % STATUS_MESSAGES.length)
    }, 2600)
    return () => clearInterval(timer)
  }, [STATUS_MESSAGES.length])

  const completedAudio = (audioState?.results ?? []).filter((r) => r.status === 'complete').length

  const stages: { label: string; sub: string; status: 'complete' | 'running' | 'pending' }[] = [
    {
      label: 'Campaign image',
      sub: imageState?.imageUrl ? 'Ready' : 'Generating',
      status: imageState?.imageUrl ? 'complete' : 'running',
    },
    {
      label: 'Audio',
      sub: `${completedAudio} / ${locationCount} locations`,
      status: completedAudio === locationCount && locationCount > 0 ? 'complete' : 'running',
    },
    {
      label: 'Video',
      sub: 'Awaiting audio',
      status: 'pending',
    },
  ]

  const BARS = Array.from({ length: 30 }, (_, i) => ({
    height: 12 + Math.abs(Math.sin(i * 0.65) * Math.cos(i * 0.45)) * 46,
    duration: 0.6 + ((i * 0.13) % 0.75),
    delay: (i * 0.09) % 1.15,
    isAccent2: i % 5 === 2,
    opacity: 0.45 + Math.abs(Math.sin(i * 0.9)) * 0.55,
  }))

  return (
    <div
      className="pmg-panel relative overflow-hidden p-10"
      style={{
        background:
          'radial-gradient(ellipse 80% 55% at 50% 70%, rgba(42, 85, 131, 0.22) 0%, var(--pmg-surface) 70%)',
      }}
    >
      <div className="relative flex flex-col items-center gap-7">
        {/* live indicator */}
        <div className="flex items-center gap-2">
          <span className="pmg-live-dot" />
          <span
            className="text-xs font-semibold uppercase tracking-widest"
            style={{ color: 'var(--pmg-success)' }}
          >
            Live
          </span>
        </div>

        {/* animated waveform */}
        <div
          className="flex items-end justify-center gap-[3px]"
          style={{ height: '68px' }}
          aria-hidden
        >
          {BARS.map((bar, i) => (
            <div
              key={i}
              className="pmg-waveform-bar"
              style={{
                height: `${bar.height}px`,
                background: bar.isAccent2
                  ? 'linear-gradient(to top, var(--pmg-accent-2), rgba(0, 98, 107, 0.3))'
                  : 'linear-gradient(to top, var(--pmg-accent), rgba(42, 85, 131, 0.3))',
                opacity: bar.opacity,
                '--pmg-wave-dur': `${bar.duration}s`,
                '--pmg-wave-delay': `${bar.delay}s`,
              } as React.CSSProperties}
            />
          ))}
        </div>

        {/* title + cycling status */}
        <div className="text-center">
          <h3 className="text-xl font-semibold tracking-tight text-[var(--pmg-text)]">
            Generating {locationCount} ad{locationCount !== 1 ? 's' : ''}
          </h3>
          <div className="mt-2 h-5 overflow-hidden">
            <p
              key={statusIndex}
              className="text-sm text-[var(--pmg-muted)]"
              style={{ animation: 'pmg-status-fade 2.6s ease-in-out forwards' }}
            >
              {STATUS_MESSAGES[statusIndex]}
            </p>
          </div>
        </div>

        {/* pipeline stage pills */}
        <div className="flex flex-wrap items-stretch justify-center gap-3">
          {stages.map((stage) => (
            <div
              key={stage.label}
              className="flex items-center gap-3 rounded-2xl px-4 py-2.5"
              style={{ background: 'var(--pmg-surface-2)' }}
            >
              <div
                className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full"
                style={{
                  background:
                    stage.status === 'complete'
                      ? 'rgba(120, 192, 166, 0.2)'
                      : stage.status === 'running'
                        ? 'rgba(42, 85, 131, 0.4)'
                        : 'rgba(255,255,255,0.04)',
                }}
              >
                {stage.status === 'complete' ? (
                  <svg viewBox="0 0 12 12" fill="none" className="h-3.5 w-3.5" style={{ color: 'var(--pmg-success)' }}>
                    <path d="M2 6l3 3 5-5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                ) : stage.status === 'running' ? (
                  <span className="pmg-live-dot" style={{ width: '6px', height: '6px' }} />
                ) : (
                  <svg viewBox="0 0 12 12" fill="currentColor" className="h-3 w-3 opacity-30" style={{ color: 'var(--pmg-muted)' }}>
                    <circle cx="6" cy="6" r="3" />
                  </svg>
                )}
              </div>
              <div>
                <p
                  className="text-xs font-medium"
                  style={{
                    color: stage.status === 'pending' ? 'var(--pmg-muted)' : 'var(--pmg-text)',
                    opacity: stage.status === 'pending' ? 0.5 : 1,
                  }}
                >
                  {stage.label}
                </p>
                <p className="text-xs" style={{ color: 'var(--pmg-muted)', opacity: stage.status === 'pending' ? 0.4 : 0.8 }}>
                  {stage.sub}
                </p>
              </div>
            </div>
          ))}
        </div>

        <p className="text-xs" style={{ color: 'var(--pmg-muted)', opacity: 0.6 }}>
          Generation typically takes 1–3 minutes
        </p>
      </div>
    </div>
  )
}

function LocationResultCard({
  audioResult,
  videoResult,
  videoGenerating,
  apiBase,
}: {
  audioResult: AudioResult
  videoResult: VideoResult | null
  videoGenerating: boolean
  apiBase: string
}) {
  const audioUrl = audioResult.audioUrl ?? getAssetUris(audioResult.pollResponse?.raw)[0] ?? null
  const videoUrl = videoResult?.videoUrl ?? null

  const videoSectionLabel =
    videoResult?.status === 'complete'
      ? 'Video ready'
      : videoResult?.status === 'failed'
        ? 'Video failed'
        : videoGenerating
          ? 'Video generating...'
          : 'Video pending'

  const videoChipClass =
    videoResult?.status === 'complete'
      ? 'pmg-status-complete'
      : videoResult?.status === 'failed'
        ? 'pmg-status-failed'
        : 'pmg-status-running'

  return (
    <article className="pmg-panel overflow-hidden">
      {/* Audio row */}
      <div className="p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="font-medium text-[var(--pmg-text)]">{audioResult.location}</h3>
          <span className={`pmg-status-chip ${statusChipClass(audioResult.status)}`}>
            {audioResult.status}
          </span>
        </div>
        {audioResult.error ? (
          <p className="pmg-alert-error mt-2 rounded-xl px-3 py-2 text-sm">{audioResult.error}</p>
        ) : null}
        {audioResult.pollResponse?.scriptText ? (
          <p className="pmg-panel-muted mt-3 px-3 py-2 text-sm text-[var(--pmg-muted)]">
            {audioResult.pollResponse.scriptText}
          </p>
        ) : audioResult.status === 'running' ? (
          <div className="mt-3 space-y-1.5">
            <div className="pmg-shimmer h-3 w-4/5 rounded-full" />
            <div className="pmg-shimmer h-3 w-3/5 rounded-full" />
          </div>
        ) : null}
        {audioUrl ? (
          <div className="mt-3 flex flex-col gap-2">
            <audio controls src={audioUrl} className="w-full" />
            <DownloadLink href={audioUrl} filename={`${audioResult.location.replace(/\s+/g, '-')}.wav`}>
              Download audio
            </DownloadLink>
          </div>
        ) : audioResult.status === 'running' ? (
          <div className="mt-3 flex items-center gap-3">
            <div className="pmg-shimmer h-10 flex-1 rounded-full" />
          </div>
        ) : null}
      </div>

      {/* Video expandable section */}
      <details className="group border-t border-[var(--pmg-border)]" open={videoResult?.status === 'complete'}>
        <summary className="flex cursor-pointer select-none items-center gap-2 px-4 py-3 text-sm text-[var(--pmg-muted)] hover:text-[var(--pmg-text)]">
          <svg
            className="h-3.5 w-3.5 flex-shrink-0 rotate-0 transition-transform group-open:rotate-90"
            viewBox="0 0 12 12" fill="currentColor"
          >
            <path d="M4.5 2L9 6l-4.5 4V2z" />
          </svg>
          <span className={`pmg-status-chip ${videoChipClass}`}>{videoSectionLabel}</span>
        </summary>
        <div className="px-4 pb-4">
          {videoResult?.status === 'complete' && videoUrl ? (
            <div className="space-y-2">
              <video
                controls
                src={`${apiBase}${videoUrl}`}
                className="w-full rounded-xl"
                style={{ maxHeight: '480px' }}
              />
              <DownloadLink
                href={`${apiBase}${videoUrl}`}
                filename={videoResult.video_filename}
              >
                Download video
              </DownloadLink>
            </div>
          ) : videoResult?.status === 'failed' ? (
            <p className="pmg-alert-error rounded-xl px-3 py-2 text-sm">{videoResult.error ?? 'Video generation failed'}</p>
          ) : videoGenerating ? (
            <div className="space-y-2 py-1">
              <div className="pmg-shimmer h-40 w-full rounded-xl" />
              <p className="text-xs text-[var(--pmg-muted)]">Assembling video — this may take a few minutes.</p>
            </div>
          ) : (
            <p className="py-2 text-sm text-[var(--pmg-muted)]">
              Video will generate once clips and audio are both ready.
            </p>
          )}
        </div>
      </details>
    </article>
  )
}

function DownloadLink({ href, filename, children }: { href: string; filename: string; children?: ReactNode }) {
  return (
    <a
      href={href}
      download={filename}
      className="pmg-button-secondary inline-flex items-center gap-1.5 px-3 py-1.5 text-xs"
    >
      <svg className="h-3 w-3" viewBox="0 0 12 12" fill="currentColor">
        <path d="M6 1v6.5M3.5 5.5 6 8l2.5-2.5M2 9.5h8" stroke="currentColor" strokeWidth="1.2" fill="none" strokeLinecap="round" />
      </svg>
      {children ?? filename}
    </a>
  )
}

const FEED_KEY_MAP: Record<string, keyof typeof FEED_LOADING_TEXT> = {
  Brand: 'brand',
  'Campaign Context': 'context',
  Trends: 'trends',
  Locations: 'locations',
}

function FeedStatusRow({
  index,
  label,
  ready,
  failed,
}: {
  index: number
  label: string
  ready: boolean
  failed: boolean
}) {
  const feedKey = FEED_KEY_MAP[label] ?? 'brand'
  const texts = FEED_LOADING_TEXT[feedKey]
  const [textIdx, setTextIdx] = useState(0)

  useEffect(() => {
    if (ready || failed) return
    const t = setInterval(() => setTextIdx((i) => (i + 1) % texts.length), 2200)
    return () => clearInterval(t)
  }, [ready, failed, texts.length])

  return (
    <div className="flex items-center gap-4 px-5 py-3.5">
      {/* Status indicator */}
      <div
        className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full"
        style={{
          background: failed
            ? 'rgba(234, 120, 122, 0.15)'
            : ready
              ? 'rgba(120, 192, 166, 0.15)'
              : 'rgba(42, 85, 131, 0.3)',
        }}
      >
        {failed ? (
          <svg viewBox="0 0 12 12" fill="none" className="h-3 w-3" style={{ color: 'var(--pmg-danger)' }}>
            <path d="M2 2l8 8M10 2l-8 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
        ) : ready ? (
          <svg viewBox="0 0 12 12" fill="none" className="h-3.5 w-3.5" style={{ color: 'var(--pmg-success)' }}>
            <path d="M2 6l3 3 5-5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        ) : (
          <span
            className="pmg-live-dot"
            style={{ width: '7px', height: '7px', background: 'var(--pmg-accent)', boxShadow: '0 0 0 0 rgba(42, 85, 131, 0.6)' }}
          />
        )}
      </div>

      {/* Label */}
      <div className="min-w-0 flex-1">
        <p className="text-xs text-[var(--pmg-muted)]">Feed {index}</p>
        <p className="text-sm font-medium text-[var(--pmg-text)]">{label}</p>
      </div>

      {/* Status text */}
      <p
        key={failed ? 'failed' : ready ? 'ready' : textIdx}
        className="flex-shrink-0 text-right text-xs"
        style={{
          color: failed ? 'var(--pmg-danger)' : ready ? 'var(--pmg-success)' : 'var(--pmg-muted)',
          animation: !ready && !failed ? 'pmg-status-fade 2.2s ease-in-out forwards' : undefined,
          minWidth: '130px',
        }}
      >
        {failed ? 'Failed' : ready ? 'Ready' : texts[textIdx]}
      </p>
    </div>
  )
}

function FeedStatusPanel({
  feedProgress,
  isFeedsReady,
  runFailed,
  locationCount,
}: {
  feedProgress: { label: string; ready: boolean }[]
  isFeedsReady: boolean
  runFailed: boolean
  locationCount: number
}) {
  return (
    <div className="pmg-panel overflow-hidden">
      {/* Header */}
      <div
        className="flex items-center justify-between px-5 py-4"
        style={{ borderBottom: '1px solid var(--pmg-border)' }}
      >
        <div className="flex items-center gap-3">
          <div>
            <p className="pmg-kicker">Intelligence pipeline</p>
            <p className="mt-0.5 text-sm font-semibold text-[var(--pmg-text)]">
              {runFailed
                ? 'Pipeline failed'
                : isFeedsReady
                  ? `${locationCount} location${locationCount !== 1 ? 's' : ''} identified`
                  : 'Collecting campaign signals'}
            </p>
          </div>
        </div>
        <span
          className={`pmg-status-chip ${
            runFailed ? 'pmg-status-failed' : isFeedsReady ? 'pmg-status-complete' : 'pmg-status-running'
          }`}
        >
          {runFailed ? 'failed' : isFeedsReady ? 'ready' : 'running'}
        </span>
      </div>

      {/* Footer */}
      {!isFeedsReady && !runFailed && (
        <div
          className="px-5 py-3"
          style={{ borderTop: '1px solid var(--pmg-border)', background: 'rgba(42, 85, 131, 0.06)' }}
        >
          <p className="text-xs text-[var(--pmg-muted)]">
            Full feed data will appear once all signals are collected.
          </p>
        </div>
      )}
    </div>
  )
}

function FeedCard({
  title,
  feed,
  summaryKeys,
  warning = false,
  locationCount,
  locationNames = [],
  revealData = true,
  statusOverride,
  loadingTexts = ['Fetching', 'Analyzing'],
}: {
  title: string
  feed: FeedBlob | LocationFeed | undefined
  summaryKeys: string[]
  warning?: boolean
  locationCount?: number
  locationNames?: string[]
  revealData?: boolean
  statusOverride?: string
  loadingTexts?: readonly string[]
}) {
  const [loadingIdx, setLoadingIdx] = useState(0)
  const [typedText, setTypedText] = useState('')
  useEffect(() => {
    if (revealData) return
    let timer: ReturnType<typeof setTimeout> | undefined
    const scheduleNext = () => {
      const delay = 6000 + Math.random() * 6000
      timer = setTimeout(() => {
        setLoadingIdx((i) => (i + 1) % loadingTexts.length)
        scheduleNext()
      }, delay)
    }
    scheduleNext()
    return () => {
      if (timer) clearTimeout(timer)
    }
  }, [revealData, loadingTexts.length])

  const data = feed?.data as Record<string, unknown> | undefined
  const displayStatus = statusOverride ?? feed?.status ?? 'pending'
  const placeholderText = loadingTexts[loadingIdx % Math.max(loadingTexts.length, 1)] || 'Loading...'
  const chipLabel = revealData ? displayStatus || '' : placeholderText
  useEffect(() => {
    const target = chipLabel || 'Loading...'
    let timer: ReturnType<typeof setTimeout> | undefined
    setTypedText('')
    if (target.length === 0) {
      setTypedText('Loading...')
      return
    }
    let i = 0
    const step = () => {
      i += 1
      setTypedText((prev) => target.slice(0, i))
      if (i < target.length) {
        timer = setTimeout(step, 30)
      }
    }
    timer = setTimeout(step, 0)
    return () => {
      if (timer) clearTimeout(timer)
      setTypedText(target)
    }
  }, [chipLabel])

  const chipDisplay = revealData ? chipLabel || 'Loading...' : typedText || 'Loading...'
  return (
    <article className="pmg-panel p-4">
      <div className="flex items-center justify-between gap-2">
        <h3 className="font-medium">{title}</h3>
        <span className={`pmg-status-chip ${statusChipClass(displayStatus)}`}>{chipDisplay}</span>
      </div>
      {typeof locationCount === 'number' ? (
        <p className="mt-2 text-sm text-[var(--pmg-muted)]">Location count: {locationCount}</p>
      ) : null}
      {warning ? (
        <p className="pmg-alert-warning mt-2 rounded-xl px-3 py-2 text-xs">
          Warning: feed mentions API key or unavailable text.
        </p>
      ) : null}
      {!revealData ? null : (
        <>
          <div className="mt-3 space-y-1 text-sm">
            {summaryKeys.map((key) => (
              <p key={key}>
                <span className="font-medium">{formatFieldLabel(key)}:</span>{' '}
                <span>{renderDisplayValue(data?.[key])}</span>
              </p>
            ))}
          </div>
          {locationNames.length > 0 ? (
            <div className="mt-3">
              <p className="text-sm font-medium">Top 20 locations</p>
              <ol className="mt-1 list-decimal space-y-1 pl-5 text-sm text-[var(--pmg-muted)]">
                {locationNames.map((name, index) => (
                  <li key={`${name}-${index}`}>{name}</li>
                ))}
              </ol>
            </div>
          ) : null}
        </>
      )}
    </article>
  )
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <p className="text-sm text-[var(--pmg-muted)]">
      <span className="font-medium text-[var(--pmg-text)]">{label}: </span>
      <span>{value || '-'}</span>
    </p>
  )
}

function formatFieldLabel(key: string): string {
  if (FIELD_LABEL_OVERRIDES[key]) return FIELD_LABEL_OVERRIDES[key]
  return key
    .split('_')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

function renderDisplayValue(value: unknown, depth = 0): ReactNode {
  if (value === undefined || value === null) return '-'
  if (typeof value === 'string') return value
  if (typeof value === 'number') return value.toLocaleString()
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'

  if (Array.isArray(value)) {
    if (value.length === 0) return 'None'
    const allPrimitive = value.every(
      (item) => item === null || ['string', 'number', 'boolean'].includes(typeof item),
    )
    if (allPrimitive) {
      return (
        <span className="inline-flex flex-wrap gap-1 align-middle">
          {value.map((item, index) => (
            <span key={index} className="pmg-badge">
              {item === null ? 'None' : String(item)}
            </span>
          ))}
        </span>
      )
    }
    return (
      <details className="pmg-panel-muted p-2">
        <summary className="cursor-pointer text-xs text-[var(--pmg-muted)]">View list ({value.length})</summary>
        <pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-xs text-[var(--pmg-muted)]">
          {JSON.stringify(value, null, 2)}
        </pre>
      </details>
    )
  }

  const record = value as Record<string, unknown>
  const entries = Object.entries(record)
  if (entries.length === 0) return 'None'
  if (depth >= 2) {
    return (
      <details className="pmg-panel-muted p-2">
        <summary className="cursor-pointer text-xs text-[var(--pmg-muted)]">View details</summary>
        <pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-xs text-[var(--pmg-muted)]">
          {JSON.stringify(record, null, 2)}
        </pre>
      </details>
    )
  }

  return (
    <div className="pmg-panel-muted mt-1 space-y-1 p-2">
      {entries.map(([key, nestedValue]) => (
        <div key={key} className="grid grid-cols-[120px_1fr] gap-2">
          <span className="text-xs font-medium text-[var(--pmg-text)]">{formatFieldLabel(key)}</span>
          <span className="text-xs text-[var(--pmg-muted)]">{renderDisplayValue(nestedValue, depth + 1)}</span>
        </div>
      ))}
    </div>
  )
}

function statusChipClass(status: string | undefined): string {
  if (!status) return 'pmg-status-pending'
  const normalized = status.toLowerCase()
  if (normalized === 'complete') return 'pmg-status-complete'
  if (normalized === 'running' || normalized === 'idle' || normalized === 'pending') return `pmg-status-${normalized}`
  if (normalized === 'failed' || normalized === 'error' || normalized === 'timeout') return `pmg-status-${normalized}`
  return 'pmg-status-error'
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
