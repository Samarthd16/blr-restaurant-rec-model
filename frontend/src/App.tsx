import { useEffect, useRef, useState } from 'react'
import './App.css'

type Message = {
  role: 'user' | 'assistant'
  content: string
}

// VITE_API_BASE_URL is set per-environment (.env.local for dev, a Vercel
// project env var for production pointing at the deployed Railway backend)
// -- never hardcode localhost here, or the deployed build silently tries
// to call itself.
const API_URL = `${import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'}/chat`

function App() {
  const [messages, setMessages] = useState<Message[]>([
    { role: 'assistant', content: 'Ask me about cafes, bars, or dessert spots around Bengaluru.' },
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function sendMessage() {
    const question = input.trim()
    if (!question || loading) return

    setMessages((prev) => [...prev, { role: 'user', content: question }])
    setInput('')
    setLoading(true)

    try {
      const res = await fetch(API_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question }),
      })
      if (!res.ok) throw new Error(`Backend returned ${res.status}`)
      const data = await res.json()
      setMessages((prev) => [...prev, { role: 'assistant', content: data.answer }])
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: `Couldn't reach the backend at ${API_URL}. Is the FastAPI server running?`,
        },
      ])
    } finally {
      setLoading(false)
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') sendMessage()
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1>Cafe Hopper Guide</h1>
        <p className="subtitle">Bengaluru food spot recommendations</p>
      </header>

      <main className="chat">
        {messages.map((m, i) => (
          <div key={i} className={`bubble ${m.role}`}>
            {m.content}
          </div>
        ))}
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
        <button onClick={sendMessage} disabled={loading || !input.trim()}>
          Send
        </button>
      </footer>
    </div>
  )
}

export default App
