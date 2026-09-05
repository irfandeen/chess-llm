import { useCallback, useEffect, useRef, useState } from 'react'
import Board from './components/Board'
import ChatPanel from './components/ChatPanel'
import KeyPanel from './components/KeyPanel'
import {
  getGame,
  getKeyStatus,
  removeKey,
  resetGame,
  streamSSE,
  undoMove,
} from './api'

let nextId = 1
const mid = () => nextId++

function lastMoveOf(state) {
  const uci = state?.history?.at(-1)
  return uci ? { from: uci.slice(0, 2), to: uci.slice(2, 4) } : null
}

function endMessage(status) {
  if (status === 'checkmate') return 'Checkmate.'
  if (status === 'stalemate') return 'Stalemate — a draw.'
  return null
}

export default function App() {
  const [keyInfo, setKeyInfo] = useState(null)
  const [game, setGame] = useState(null)
  const [humanColor, setHumanColor] = useState('white')
  const [messages, setMessages] = useState([])
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState(null)
  const [pendingColor, setPendingColor] = useState(null) // confirm modal
  const toastTimer = useRef(null)

  const showToast = useCallback((text) => {
    setToast(text)
    clearTimeout(toastTimer.current)
    toastTimer.current = setTimeout(() => setToast(null), 4000)
  }, [])

  useEffect(() => {
    Promise.all([getKeyStatus(), getGame()])
      .then(([k, g]) => {
        setKeyInfo(k)
        setGame(g.state)
        if (g.human_color) setHumanColor(g.human_color)
      })
      .catch(() => showToast('Could not reach the server.'))
  }, [showToast])

  const patchMsg = (id, patch) =>
    setMessages((ms) =>
      ms.map((m) =>
        m.id === id ? { ...m, ...(typeof patch === 'function' ? patch(m) : patch) } : m,
      ),
    )

  /** Stream one LLM turn. `uci` omitted means the LLM opens as White. */
  const runLlmTurn = useCallback(
    async (uci) => {
      const llmId = mid()
      setMessages((ms) => [
        ...ms,
        { id: llmId, role: 'llm', text: '', done: false, ply: null },
      ])
      try {
        await streamSSE(
          '/api/game/move',
          uci ? { uci } : {},
          {
            user_move: ({ state }) => setGame(state),
            move: ({ uci: llmUci, state }) => {
              setGame(state)
              patchMsg(llmId, { moveUci: llmUci, ply: state.history.length })
            },
            read: ({ text }) => patchMsg(llmId, { read: text }),
            strategy: ({ text }) => patchMsg(llmId, { strategy: text }),
            token: ({ text }) => patchMsg(llmId, (m) => ({ text: m.text + text })),
            done: ({ status, game_over }) => {
              patchMsg(llmId, { done: true })
              const end = game_over && endMessage(status)
              if (end) {
                setMessages((ms) => [
                  ...ms,
                  {
                    id: mid(),
                    role: 'info',
                    text: end,
                    done: true,
                    ply: Infinity,
                  },
                ])
              }
            },
            error: ({ message }) => {
              setMessages((ms) => ms.filter((m) => m.id !== llmId))
              showToast(message)
            },
          },
        )
        patchMsg(llmId, { done: true })
      } catch (err) {
        setMessages((ms) => ms.filter((m) => m.id !== llmId))
        showToast(err.message)
      }
    },
    [showToast],
  )

  const handleMove = async (uci) => {
    if (busy) return
    setBusy(true)
    try {
      await runLlmTurn(uci)
    } finally {
      setBusy(false)
    }
  }

  const handleAsk = async (question) => {
    if (busy) return
    setBusy(true)
    const ply = game?.history?.length ?? 0
    const llmId = mid()
    setMessages((ms) => [
      ...ms,
      { id: mid(), role: 'user', text: question, done: true, ply },
      { id: llmId, role: 'llm', text: '', done: false, ply },
    ])
    try {
      await streamSSE(
        '/api/chat',
        { message: question },
        {
          token: ({ text }) => patchMsg(llmId, (m) => ({ text: m.text + text })),
          done: () => patchMsg(llmId, { done: true }),
          error: ({ message }) => {
            setMessages((ms) => ms.filter((m) => m.id !== llmId))
            showToast(message)
          },
        },
      )
      patchMsg(llmId, { done: true })
    } catch (err) {
      setMessages((ms) => ms.filter((m) => m.id !== llmId))
      showToast(err.message)
    } finally {
      setBusy(false)
    }
  }

  /** Reset, optionally switching sides. The LLM opens if the human is Black. */
  const startGame = useCallback(
    async (color) => {
      if (busy) return
      setBusy(true)
      try {
        const data = await resetGame(color)
        setGame(data.state)
        setHumanColor(data.human_color)
        setMessages([])
        if (data.human_color === 'black') {
          await runLlmTurn(null)
        }
      } catch (err) {
        showToast(err.message)
      } finally {
        setBusy(false)
      }
    },
    [busy, runLlmTurn, showToast],
  )

  const handleReset = () => startGame(humanColor)

  const requestColor = (color) => {
    if (busy || color === humanColor) return
    if (game?.history?.length) {
      setPendingColor(color) // confirm before discarding a live game
    } else {
      startGame(color)
    }
  }

  const handleUndo = async () => {
    if (busy || !game?.history?.length) return
    try {
      const data = await undoMove()
      setGame(data.state)
      const keep = data.state.history.length
      setMessages((ms) => ms.filter((m) => m.ply !== null && m.ply <= keep))
    } catch (err) {
      showToast(err.message)
    }
  }

  const handleRemoveKey = async () => {
    try {
      await removeKey()
      setKeyInfo({ has_key: false, provider: null })
    } catch (err) {
      showToast(err.message)
    }
  }

  const canUndo =
    !busy && (game?.history?.length ?? 0) > (humanColor === 'white' ? 0 : 1)

  const statusLabel = (() => {
    if (!game) return 'Loading…'
    if (game.status === 'checkmate') {
      return game.turn === humanColor
        ? 'Checkmate — the LLM wins.'
        : 'Checkmate — you win! 🎉'
    }
    if (game.status === 'stalemate') return 'Stalemate — draw.'
    if (busy) return 'Opponent is thinking…'
    if (game.status === 'check' && game.turn === humanColor) {
      return 'You are in check!'
    }
    return game.turn === humanColor
      ? `Your move (${humanColor === 'white' ? 'White' : 'Black'})`
      : 'Opponent to move'
  })()

  return (
    <div className="app">
      <header className="topbar">
        <h1>
          <span className="logo-glyph">♞</span> chess<span className="accent">·llm</span>
        </h1>
        <p className="tagline">Understand your opponent&rsquo;s strategy.</p>
      </header>

      <main className="layout">
        <section className="board-col">
          <div className="board-toolbar">
            <button className="btn btn-ghost" onClick={handleReset} disabled={busy}>
              ⟳ Refresh Match
            </button>
            <button className="btn btn-ghost" onClick={handleUndo} disabled={!canUndo}>
              ↶ Undo Move
            </button>
            <div className="side-toggle" role="group" aria-label="Choose your side">
              <button
                className={humanColor === 'white' ? 'is-active' : ''}
                onClick={() => requestColor('white')}
                disabled={busy}
                aria-pressed={humanColor === 'white'}
              >
                ♔ White
              </button>
              <button
                className={humanColor === 'black' ? 'is-active' : ''}
                onClick={() => requestColor('black')}
                disabled={busy}
                aria-pressed={humanColor === 'black'}
              >
                ♚ Black
              </button>
            </div>
            <span className={'status-pill' + (busy ? ' pulsing' : '')}>
              {statusLabel}
            </span>
          </div>
          <Board
            game={game}
            disabled={busy || !keyInfo?.has_key}
            onMove={handleMove}
            lastMove={lastMoveOf(game)}
            humanColor={humanColor}
          />
          {!keyInfo?.has_key && keyInfo && (
            <p className="board-hint">Add your API key to unlock the board →</p>
          )}
        </section>

        <aside className="side-col">
          {keyInfo === null ? (
            <div className="chat-panel">
              <div className="skeleton" style={{ padding: 24 }}>
                <div className="skeleton-bar" style={{ width: '60%' }} />
                <div className="skeleton-bar" style={{ width: '85%' }} />
              </div>
            </div>
          ) : keyInfo.has_key ? (
            <ChatPanel
              messages={messages}
              busy={busy}
              onAsk={handleAsk}
              onRemoveKey={handleRemoveKey}
            />
          ) : (
            <KeyPanel onSaved={() => setKeyInfo({ has_key: true, provider: 'gemini' })} />
          )}
        </aside>
      </main>

      {pendingColor && (
        <div className="modal-overlay" onClick={() => setPendingColor(null)}>
          <div
            className="modal"
            role="alertdialog"
            aria-modal="true"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-icon">♟</div>
            <h3>Start over as {pendingColor === 'white' ? 'White' : 'Black'}?</h3>
            <p>
              Your match is already underway. Switching sides starts a brand new
              game — the current board and the whole thought-process log will be
              cleared.
            </p>
            <div className="modal-actions">
              <button className="btn btn-ghost" onClick={() => setPendingColor(null)}>
                Keep playing
              </button>
              <button
                className="btn btn-danger"
                onClick={() => {
                  const color = pendingColor
                  setPendingColor(null)
                  startGame(color)
                }}
              >
                Switch &amp; restart
              </button>
            </div>
          </div>
        </div>
      )}

      {toast && <div className="toast">{toast}</div>}
    </div>
  )
}
