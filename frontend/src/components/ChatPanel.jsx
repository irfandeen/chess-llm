import { useEffect, useRef, useState } from 'react'

/** Reveal text progressively; when the stream is done, catch up at 2x. */
function Typewriter({ text, done }) {
  const [shown, setShown] = useState(0)
  const textRef = useRef(text)
  textRef.current = text

  useEffect(() => {
    if (shown >= text.length) return
    const interval = setInterval(() => {
      setShown((s) => {
        const target = textRef.current.length
        if (s >= target) return s
        return Math.min(s + (done ? 4 : 2), target)
      })
    }, 16)
    return () => clearInterval(interval)
  }, [shown < text.length, done, text.length])

  return (
    <>
      {text.slice(0, shown)}
      {shown < text.length && <span className="caret" />}
    </>
  )
}

/** Pull the "NN%" out of a read so the confidence can be styled distinctly. */
function ReadText({ text }) {
  const match = text.match(/(\d{1,3})\s*%/)
  if (!match) return <>{text}</>
  const label = text
    .replace(/[—\-–,]?\s*\(?\d{1,3}\s*%\s*(confident|confidence|sure)?\)?/i, '')
    .replace(/[—\-–,:]\s*$/, '')
    .trim()
  return (
    <>
      {label}
      <span className="confidence">{match[1]}%</span>
    </>
  )
}

function Skeleton() {
  return (
    <div className="skeleton">
      <div className="skeleton-bar" style={{ width: '90%' }} />
      <div className="skeleton-bar" style={{ width: '75%' }} />
      <div className="skeleton-bar" style={{ width: '82%' }} />
    </div>
  )
}

export default function ChatPanel({ messages, busy, onAsk, onRemoveKey }) {
  const [draft, setDraft] = useState('')
  const listRef = useRef(null)
  const streaming = messages.some((m) => !m.done)

  useEffect(() => {
    const el = listRef.current
    if (!el) return
    const scroll = () => {
      el.scrollTop = el.scrollHeight
    }
    scroll()
    if (!streaming) return
    const interval = setInterval(scroll, 250)
    return () => clearInterval(interval)
  }, [messages.length, streaming])

  const submit = (e) => {
    e.preventDefault()
    const q = draft.trim()
    if (!q || busy) return
    setDraft('')
    onAsk(q)
  }

  return (
    <div className="chat-panel">
      <div className="chat-header">
        <div>
          <h2>Opponent&rsquo;s mind</h2>
          <p>Live thought process.</p>
        </div>
        <button className="btn btn-ghost btn-small" onClick={onRemoveKey}>
          Remove key
        </button>
      </div>

      <div className="chat-list" ref={listRef}>
        {messages.length === 0 && (
          <div className="chat-empty">
            <span className="chat-empty-glyph">♞</span>
            <p>
              Make a move as White. Your opponent will reply — and explain
              exactly what it&rsquo;s thinking.
            </p>
          </div>
        )}
        {messages.map((m) => {
          if (m.role === 'user') {
            return (
              <div key={m.id} className="msg msg-user">
                {m.text}
              </div>
            )
          }
          if (m.role === 'info') {
            return (
              <div key={m.id} className="msg msg-info">
                {m.text}
              </div>
            )
          }
          return (
            <div key={m.id} className="msg msg-llm">
              {(m.moveUci || m.read || m.strategy) && (
                <div className="msg-chips">
                  {m.moveUci && (
                    <span className="msg-move-chip">
                      {m.moveUci.slice(0, 2)} → {m.moveUci.slice(2, 4)}
                    </span>
                  )}
                  {m.read && (
                    <span
                      className="msg-read-chip"
                      title="What it thinks you are playing"
                    >
                      🔍 <ReadText text={m.read} />
                    </span>
                  )}
                  {m.strategy && (
                    <span className="msg-strategy-chip" title="Current strategy">
                      ♟ {m.strategy}
                    </span>
                  )}
                </div>
              )}
              {m.text === '' && !m.done ? (
                <Skeleton />
              ) : (
                <p className="msg-text">
                  <Typewriter text={m.text} done={m.done} />
                </p>
              )}
            </div>
          )
        })}
      </div>

      <form className="chat-input" onSubmit={submit}>
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={
            busy ? 'Thinking…' : 'Ask about its strategy… e.g. "why the knight?"'
          }
          disabled={busy}
          maxLength={2000}
        />
        <button
          className="btn btn-primary"
          type="submit"
          disabled={busy || !draft.trim()}
        >
          Ask
        </button>
      </form>
    </div>
  )
}
