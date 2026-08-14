import { useEffect, useRef, useState } from 'react'
import './App.css'

type PlaceResult = {
  name: string
  distance_km?: number | null
  rating?: number | null
  user_rating_count?: number | null
  things_to_try?: string[]
}

type PlacePairResult = {
  place_a: string
  place_b: string
  distance_km: number
}

type GraphNode = {
  id: string
  label: string
  type: 'reference' | 'place' | 'area' | 'category' | 'specialty'
}

type GraphEdge = {
  source: string
  target: string
  type: string
  label?: string | null
}

type GraphSnippetData = {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

type Message = {
  role: 'user' | 'assistant'
  content: string
  suggestions?: string[]
  places?: PlaceResult[]
  placePairs?: PlacePairResult[]
  graph?: GraphSnippetData
}

// Reference/hub node (if any) sits at the center; everything else is spread
// evenly around it on a circle. Deliberately not a real force-directed
// layout -- a snippet of 5-10 nodes doesn't need physics, just something
// legible at a glance.
function layoutGraph(nodes: GraphNode[], size: number): Record<string, { x: number; y: number }> {
  const center = size / 2
  const radius = size * 0.36
  const positions: Record<string, { x: number; y: number }> = {}
  const hub = nodes.find((n) => n.type === 'reference') ?? nodes[0]
  const rest = nodes.filter((n) => n.id !== hub?.id)

  if (hub) positions[hub.id] = { x: center, y: center }
  rest.forEach((n, i) => {
    const angle = (2 * Math.PI * i) / Math.max(rest.length, 1) - Math.PI / 2
    positions[n.id] = { x: center + radius * Math.cos(angle), y: center + radius * Math.sin(angle) }
  })

  return positions
}

function truncateLabel(label: string, max = 18) {
  return label.length > max ? `${label.slice(0, max - 1)}…` : label
}

function GraphSnippetSvg({ graph, size }: { graph: GraphSnippetData; size: number }) {
  const positions = layoutGraph(graph.nodes, size)
  const r = size * 0.055
  const hubR = r * 1.4
  const labelSize = Math.max(size * 0.032, 8)
  const edgeLabelSize = Math.max(size * 0.026, 7)

  return (
    <svg viewBox={`0 0 ${size} ${size}`} width={size} height={size} className="graph-svg">
      {graph.edges.map((e, i) => {
        const s = positions[e.source]
        const t = positions[e.target]
        if (!s || !t) return null
        const edgeText = e.label ? `${e.type} · ${e.label}` : e.type
        return (
          <g key={i}>
            <line x1={s.x} y1={s.y} x2={t.x} y2={t.y} className="graph-edge" />
            {edgeText && (
              <text
                x={(s.x + t.x) / 2}
                y={(s.y + t.y) / 2 - 4}
                textAnchor="middle"
                className="graph-edge-label"
                style={{ fontSize: edgeLabelSize }}
              >
                {edgeText}
              </text>
            )}
          </g>
        )
      })}
      {graph.nodes.map((n) => {
        const p = positions[n.id]
        if (!p) return null
        const radius = n.type === 'reference' ? hubR : r
        return (
          <g key={n.id}>
            <circle cx={p.x} cy={p.y} r={radius} className={`graph-node graph-node-${n.type}`} />
            <text
              x={p.x}
              y={p.y + radius + labelSize + 2}
              textAnchor="middle"
              className="graph-node-label"
              style={{ fontSize: labelSize }}
            >
              {truncateLabel(n.label)}
            </text>
          </g>
        )
      })}
    </svg>
  )
}

function GraphSnippetView({ graph }: { graph: GraphSnippetData }) {
  const [zoomed, setZoomed] = useState(false)
  if (!graph.nodes.length) return null

  return (
    <>
      <button className="graph-view-button" onClick={() => setZoomed(true)}>
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="5" r="2.5" />
          <circle cx="5" cy="19" r="2.5" />
          <circle cx="19" cy="19" r="2.5" />
          <path d="M12 7.5 L6.5 17 M12 7.5 L17.5 17 M7.5 19 L16.5 19" />
        </svg>
        View knowledge graph
      </button>
      {zoomed && (
        <div className="graph-modal-overlay" onClick={() => setZoomed(false)}>
          <div className="graph-modal" onClick={(e) => e.stopPropagation()}>
            <button className="graph-modal-close" onClick={() => setZoomed(false)} aria-label="Close">
              ✕
            </button>
            <GraphSnippetSvg graph={graph} size={640} />
          </div>
        </div>
      )}
    </>
  )
}

// Solid glyph (not outline) -- takes `color` directly via CSS, no SVG needed
// and renders consistently across platforms.
function StarIcon() {
  return <span className="star">★</span>
}

function PlaceCard({ place }: { place: PlaceResult }) {
  // Backend sends JSON `null` for fields a given query shape doesn't fetch
  // (e.g. near_reference_place results have no rating in some paths) --
  // `!= null` (loose) deliberately catches both null and undefined, unlike
  // `!== undefined`, which let a null rating through and rendered a bare
  // "★" with nothing after it.
  return (
    <div className="place-card">
      <div className="place-card-header">
        <span className="place-name">{place.name}</span>
        {place.distance_km != null && (
          <span className="place-distance">{Math.round(place.distance_km * 1000)}m away</span>
        )}
        {place.rating != null && (
          <span className="place-rating">
            <StarIcon /> {place.rating}
            {place.user_rating_count != null && (
              <span className="place-rating-count"> ({place.user_rating_count})</span>
            )}
          </span>
        )}
      </div>
      {place.things_to_try && place.things_to_try.length > 0 && (
        <div className="place-try">
          <span className="place-try-label">Try</span>
          {place.things_to_try.slice(0, 3).map((item) => (
            <span className="try-pill" key={item}>
              {item}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

function PlacePairCard({ pair }: { pair: PlacePairResult }) {
  return (
    <div className="place-card place-pair-card">
      <span className="place-name">{pair.place_a}</span>
      <span className="place-pair-sep">↔</span>
      <span className="place-name">{pair.place_b}</span>
      <span className="place-distance">{Math.round(pair.distance_km * 1000)}m apart</span>
    </div>
  )
}

// VITE_API_BASE_URL is set per-environment (.env.local for dev, a Vercel
// project env var for production pointing at the deployed Railway backend)
// -- never hardcode localhost here, or the deployed build silently tries
// to call itself.
const API_URL = `${import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'}/chat`

// Deliberately varied across query shapes (specialty+area, near-a-place,
// near-each-other, category+area) and areas, not just Indiranagar-centric --
// each one confirmed to return real results against the current dataset.
const SAMPLE_PROMPTS = [
  'Where can I get good filter coffee in Basavanagudi?',
  "What's a good dessert spot near Toit?",
  "What's the best biryani in Marathahalli?",
  'What bars in Indiranagar are near each other?',
  'Show me craft breweries in Whitefield',
]

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // Clipboard API can be unavailable (e.g. non-HTTPS context) -- fail
      // silently rather than showing an error for a non-critical action.
    }
  }

  return (
    <button
      className="copy-button"
      onClick={handleCopy}
      aria-label="Copy message"
      title={copied ? 'Copied!' : 'Copy to clipboard'}
    >
      {copied ? (
        <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="20 6 9 17 4 12" />
        </svg>
      ) : (
        <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="9" y="9" width="13" height="13" rx="2" />
          <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
        </svg>
      )}
    </button>
  )
}

function App() {
  const [messages, setMessages] = useState<Message[]>([
    { role: 'assistant', content: 'Ask me about cafes, bars, or dessert spots around Bengaluru.' },
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  // Conversation memory sent back to the backend each turn so follow-up
  // suggestions steer away from places/questions already covered instead of
  // bouncing between the same tightly-connected cluster forever. Refs, not
  // state -- mutated in place, never need to trigger a re-render themselves.
  const seenPlacesRef = useRef<Set<string>>(new Set())
  const askedQuestionsRef = useRef<Set<string>>(new Set())

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function sendMessage(overrideText?: string) {
    const question = (overrideText ?? input).trim()
    if (!question || loading) return

    askedQuestionsRef.current.add(question)
    setMessages((prev) => [...prev, { role: 'user', content: question }])
    setInput('')
    setLoading(true)

    try {
      const res = await fetch(API_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question,
          seen_places: Array.from(seenPlacesRef.current),
          asked_questions: Array.from(askedQuestionsRef.current),
        }),
      })
      if (!res.ok) throw new Error(`Backend returned ${res.status}`)
      const data = await res.json()
      for (const name of data.place_names ?? []) seenPlacesRef.current.add(name)
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: data.answer,
          suggestions: data.suggestions,
          places: data.places,
          placePairs: data.place_pairs,
          graph: data.graph,
        },
      ])
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: "Something went wrong reaching the server. Please try again in a moment.",
        },
      ])
    } finally {
      setLoading(false)
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') sendMessage()
  }

  // Only shown before any real exchange has happened -- once the user's
  // sent something, the suggestions would just clutter an active
  // conversation.
  const showSuggestions = messages.length === 1

  // Follow-ups from the most recent answer only -- once the conversation
  // moves on, older suggestions no longer make sense to keep showing.
  const lastMessage = messages[messages.length - 1]
  const followUps =
    !loading && lastMessage?.role === 'assistant' ? lastMessage.suggestions ?? [] : []

  return (
    <div className="app">
      <header className="app-header">
        <h1>Cafe Hopper Guide</h1>
        <p className="subtitle">Bengaluru food spot recommendations</p>
      </header>

      <main className="chat">
        {messages.map((m, i) => (
          <div key={i} className={`message-row ${m.role}`}>
            <div className="message-column">
              <div className={`bubble ${m.role}`}>
                {m.places && m.places.length > 0 ? (
                  <div className="place-list">
                    {m.places.map((p) => (
                      <PlaceCard place={p} key={p.name} />
                    ))}
                  </div>
                ) : m.placePairs && m.placePairs.length > 0 ? (
                  <div className="place-list">
                    {m.placePairs.map((pair) => (
                      <PlacePairCard pair={pair} key={`${pair.place_a}-${pair.place_b}`} />
                    ))}
                  </div>
                ) : (
                  m.content
                )}
              </div>
              {m.graph && m.graph.nodes.length > 0 && <GraphSnippetView graph={m.graph} />}
            </div>
            {m.role === 'assistant' && <CopyButton text={m.content} />}
          </div>
        ))}

        {showSuggestions && (
          <div className="suggestions">
            {SAMPLE_PROMPTS.map((prompt) => (
              <button
                key={prompt}
                className="suggestion-chip"
                onClick={() => sendMessage(prompt)}
                disabled={loading}
              >
                {prompt}
              </button>
            ))}
          </div>
        )}

        {followUps.length > 0 && (
          <div className="suggestions">
            {followUps.map((prompt) => (
              <button
                key={prompt}
                className="suggestion-chip"
                onClick={() => sendMessage(prompt)}
                disabled={loading}
              >
                {prompt}
              </button>
            ))}
          </div>
        )}

        {loading && <div className="bubble assistant loading">Thinking…</div>}
        <div ref={bottomRef} />
      </main>

      <footer className="composer">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask about cafes, bars, dessert spots…"
          disabled={loading}
        />
        <button onClick={() => sendMessage()} disabled={loading || !input.trim()}>
          Send
        </button>
      </footer>
    </div>
  )
}

export default App