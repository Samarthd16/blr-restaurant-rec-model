import { useEffect, useRef, useState } from 'react'
import './App.css'

type Message = {
  role: 'user' | 'assistant'
  content: string
  suggestions?: string[]
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
      setMessages((prev) => [...prev, { role: 'assistant', content: data.answer, suggestions: data.suggestions }])
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
            <div className={`bubble ${m.role}`}>{m.content}</div>
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