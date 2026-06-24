import { type ReactNode, useEffect, useMemo, useState } from 'react'
import { CampaignAnalytics } from './CampaignAnalytics'

type Step = 1 | 2 | 3 | 4
type Page = 'wizard' | 'analytics'

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
  const [page, setPage] = useState<Page>('wizard')
  const [step, setStep] = useState<Step>(1)
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

  // Poll audio and video state in Step 4
  useEffect(() => {
    if (step !== 4 || runId === null) return

    const loadAudio = async () => {
      try {
        const state = await apiFetch<AudioStateResponse>(`/runs/${runId}/audio`)
        setAudioState(state)
        setAudioError(state.error ?? null)
      } catch (error) {
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
  const feedProgress = [
    { label: 'Brand', ready: isFeedsReady && Boolean(runData?.feeds.brand?.data) },
    { label: 'Campaign Context', ready: isFeedsReady && Boolean(runData?.feeds.context?.data) },
    { label: 'Trends', ready: isFeedsReady && Boolean(runData?.feeds.trends?.data) },
    { label: 'Locations', ready: isFeedsReady && (runData?.feeds.locations?.count ?? 0) > 0 },
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
        <p className="pmg-kicker">Engineered for impact</p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight text-[var(--pmg-text)] md:text-4xl">
          Dynamic Voice Local Wizard
        </h1>
        <p className="mt-3 max-w-2xl text-sm text-[var(--pmg-muted)] md:text-base">
          Build localized voice creative through a guided flow: collect feed intelligence, review brief data, and
          generate location-specific audio results.
        </p>
      </section>

      <div className="mt-4 flex gap-2">
        <button
          type="button"
          onClick={() => setPage('wizard')}
          className={page === 'wizard' ? 'pmg-button-primary px-4 py-2 text-sm font-medium' : 'pmg-button-secondary px-4 py-2 text-sm'}
        >
          Wizard
        </button>
        <button
          type="button"
          onClick={() => setPage('analytics')}
          className={page === 'analytics' ? 'pmg-button-primary px-4 py-2 text-sm font-medium' : 'pmg-button-secondary px-4 py-2 text-sm'}
        >
          Campaign Analytics
        </button>
      </div>

      {page === 'wizard' && (
        <>
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
                <span className="text-sm font-medium text-[var(--pmg-muted)]">Campaign</span>
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
            <p className="text-sm text-[var(--pmg-muted)]">
              Be specific - avoid generic phrases like &quot;Enroll now!&quot;
            </p>
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
        <section className="mt-8 space-y-4">
          <h2 className="text-lg font-medium text-[var(--pmg-text)]">Step 2 - Feed results</h2>
          <p className="text-sm text-[var(--pmg-muted)]">Polling run #{runId} every 2 seconds.</p>
          <div className="pmg-panel-muted p-4 text-sm">
            <p className="font-medium text-[var(--pmg-text)]">
              {runFailed
                ? 'Feed run failed.'
                : isFeedsReady
                  ? 'All feeds ready.'
                  : `Feeds running: ${readyFeedCount}/${feedProgress.length} ready`}
            </p>
            <p className="mt-1 text-[var(--pmg-muted)]">
              {isFeedsReady
                ? `Locations found: ${runData?.feeds.locations?.count ?? 0}`
                : 'Locations found: waiting for feed completion'}
            </p>
            <div className="mt-2 flex flex-wrap gap-2 text-xs">
              {feedProgress.map((feed, index) => (
                <span
                  key={feed.label}
                  className={`pmg-status-chip ${
                    runFailed ? 'pmg-status-failed' : feed.ready ? 'pmg-status-complete' : 'pmg-status-running'
                  }`}
                >
                  {index + 1}. {feed.label}: {runFailed ? 'failed' : feed.ready ? 'ready' : 'running'}
                </span>
              ))}
            </div>
            {!isFeedsReady && !runFailed ? (
              <p className="mt-2 text-[var(--pmg-muted)]">
                Waiting for all feeds to finish before showing full feed details.
              </p>
            ) : null}
          </div>
          {runError ? <p className="pmg-alert-error rounded-xl px-3 py-2 text-sm">{runError}</p> : null}
          <div className="grid gap-4 md:grid-cols-2">
            <FeedCard
              title={`1. ${FEED_ORDER[0]}`}
              feed={runData?.feeds.brand}
              summaryKeys={['brand_name', 'mission', 'tone_of_voice', 'cta']}
              revealData={isFeedsReady}
              statusOverride={runFailed ? 'failed' : isFeedsReady ? 'complete' : 'running'}
            />
            <FeedCard
              title={`2. ${FEED_ORDER[1]}`}
              feed={runData?.feeds.context}
              summaryKeys={['live_moment', 'campaign_angle']}
              warning={isFeedsReady && isContextWarning}
              revealData={isFeedsReady}
              statusOverride={runFailed ? 'failed' : isFeedsReady ? 'complete' : 'running'}
            />
            <FeedCard
              title={`3. ${FEED_ORDER[2]}`}
              feed={runData?.feeds.trends}
              summaryKeys={['traffic_signal', 'website_traffic', 'search_trends']}
              revealData={isFeedsReady}
              statusOverride={runFailed ? 'failed' : isFeedsReady ? 'complete' : 'running'}
            />
            <FeedCard
              title={`4. ${FEED_ORDER[3]}`}
              feed={runData?.feeds.locations}
              summaryKeys={[]}
              locationCount={runData?.feeds.locations?.count ?? 0}
              locationNames={locationOptions.slice(0, 20).map((location) => location.name)}
              revealData={isFeedsReady}
              statusOverride={runFailed ? 'failed' : isFeedsReady ? 'complete' : 'running'}
            />
          </div>
          {imageState && imageState.status !== 'idle' && (
            <div className="pmg-panel-muted p-4 text-sm">
              <p className="font-medium text-[var(--pmg-text)]">Visual generation (auto-started)</p>
              <div className="mt-2 flex flex-wrap gap-2 text-xs">
                <span className={`pmg-status-chip ${statusChipClass(
                  ['generating_clips', 'complete', 'clips_failed'].includes(imageState.status) ? 'complete' : imageState.status
                )}`}>
                  Image: {imageState.imageUrl ? 'ready' : imageState.status === 'failed' ? 'failed' : 'running'}
                </span>
                <span className={`pmg-status-chip ${statusChipClass(
                  imageState.status === 'complete' ? 'complete'
                    : imageState.status === 'clips_failed' ? 'failed'
                    : imageState.status === 'generating_clips' ? 'running'
                    : 'idle'
                )}`}>
                  Clips: {imageState.status === 'complete' ? `${imageState.clipUrls?.length ?? 0} ready`
                    : imageState.status === 'clips_failed' ? 'failed'
                    : imageState.status === 'generating_clips' ? 'running'
                    : 'pending'}
                </span>
              </div>
              {imageState.imageUrl && (
                <img
                  src={imageState.imageUrl}
                  alt="Generated campaign image"
                  className="mt-3 max-h-48 rounded-lg object-cover"
                />
              )}
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
          <div className="pmg-panel p-4">
            <h3 className="text-base font-medium text-[var(--pmg-text)]">Brief preview (read-only)</h3>
            {briefError ? <p className="pmg-alert-error mt-2 rounded-xl px-3 py-2 text-sm">{briefError}</p> : null}
            {!briefPreview ? (
              <p className="mt-2 text-sm text-[var(--pmg-muted)]">Select locations to load preview.</p>
            ) : (
              <div className="mt-3 space-y-4">
                <div className="grid gap-2 text-sm md:grid-cols-2">
                  <Field label="productName" value={briefPreview.shared.productName} />
                  <Field label="targetAudience" value={briefPreview.shared.targetAudience} />
                  <Field label="toneOfScript" value={briefPreview.shared.toneOfScript} />
                </div>
                <Field label="productDescription" value={briefPreview.shared.productDescription} />
                {briefPreview.locations.map((loc) => (
                  <details key={loc.location} className="pmg-panel-muted p-3">
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
        <section className="mt-8 space-y-6">
          <h2 className="text-lg font-medium text-[var(--pmg-text)]">Step 4 - Generation results</h2>

          {/* Campaign visual card */}
          {imageState?.imageUrl && (
            <div className="pmg-panel overflow-hidden">
              <div className="flex items-start gap-5 p-5">
                <div
                  className="relative flex-shrink-0 overflow-hidden rounded-xl"
                  style={{ width: '7rem', aspectRatio: '9 / 16' }}
                >
                  <img
                    src={imageState.imageUrl}
                    alt="Campaign visual"
                    className="absolute inset-0 h-full w-full object-cover"
                  />
                </div>
                <div className="flex min-w-0 flex-1 flex-col gap-3 py-1">
                  <div>
                    <p className="pmg-kicker">Campaign visual</p>
                    <h3 className="mt-1.5 text-xl font-semibold tracking-tight text-[var(--pmg-text)]">
                      {productName}
                    </h3>
                    {runData?.campaign && (
                      <p className="mt-1.5 line-clamp-3 text-sm text-[var(--pmg-muted)]">{runData.campaign}</p>
                    )}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <DownloadLink
                      href={`${API_BASE}/proxy-download?url=${encodeURIComponent(imageState.imageUrl)}&filename=campaign-visual.jpg`}
                      filename="campaign-visual.jpg"
                    >
                      Download image
                    </DownloadLink>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Video generation status banner */}
          {videoState && videoState.status !== 'idle' && (
            <div className="pmg-panel-muted flex items-center gap-3 px-4 py-3 text-sm">
              <span className={`pmg-status-chip ${statusChipClass(videoState.status)}`}>
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
        </section>
      )}
        </>
      )}

      {page === 'analytics' && (
        <div className="mt-6"><CampaignAnalytics /></div>
      )}
    </main>
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
        ) : null}
        {audioUrl ? (
          <div className="mt-3 flex flex-col gap-2">
            <audio controls src={audioUrl} className="w-full" />
            <DownloadLink href={audioUrl} filename={`${audioResult.location.replace(/\s+/g, '-')}.wav`}>
              Download audio
            </DownloadLink>
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
          ) : (
            <p className="py-2 text-sm text-[var(--pmg-muted)]">
              {videoGenerating ? 'Assembling video — this may take a few minutes.' : 'Video will generate once clips and audio are both ready.'}
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

function FeedCard({
  title,
  feed,
  summaryKeys,
  warning = false,
  locationCount,
  locationNames = [],
  revealData = true,
  statusOverride,
}: {
  title: string
  feed: FeedBlob | LocationFeed | undefined
  summaryKeys: string[]
  warning?: boolean
  locationCount?: number
  locationNames?: string[]
  revealData?: boolean
  statusOverride?: string
}) {
  const data = feed?.data as Record<string, unknown> | undefined
  const displayStatus = statusOverride ?? feed?.status ?? 'pending'
  return (
    <article className="pmg-panel p-4">
      <div className="flex items-center justify-between gap-2">
        <h3 className="font-medium">{title}</h3>
        <span className={`pmg-status-chip ${statusChipClass(displayStatus)}`}>{displayStatus}</span>
      </div>
      {typeof locationCount === 'number' ? (
        <p className="mt-2 text-sm text-[var(--pmg-muted)]">Location count: {locationCount}</p>
      ) : null}
      {warning ? (
        <p className="pmg-alert-warning mt-2 rounded-xl px-3 py-2 text-xs">
          Warning: feed mentions API key or unavailable text.
        </p>
      ) : null}
      {!revealData ? (
        <p className="mt-3 text-sm text-[var(--pmg-muted)]">
          Feed is running. Live output will appear once all feeds are ready.
        </p>
      ) : (
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
