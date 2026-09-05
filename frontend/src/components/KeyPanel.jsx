import { useState } from 'react'
import { saveKey } from '../api'

export default function KeyPanel({ onSaved }) {
  const [provider, setProvider] = useState('gemini')
  const [apiKey, setApiKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const submit = async (e) => {
    e.preventDefault()
    if (!apiKey.trim() || busy) return
    setBusy(true)
    setError(null)
    try {
      await saveKey(provider, apiKey.trim())
      onSaved()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="key-panel">
      <h2>
        Paste your API key to start playing
        <span className="info-wrap">
          <span className="info-icon" tabIndex={0} aria-label="API key info">
            i
          </span>
          <span className="info-tooltip" role="tooltip">
            Your keys are encrypted safely, but it is advisable anyway to use
            free tier{' '}
            <a
              href="https://aistudio.google.com/apikey"
              target="_blank"
              rel="noreferrer"
            >
              Gemini
            </a>{' '}
            keys!
          </span>
        </span>
      </h2>
      <p className="key-sub">
        Play chess against an LLM that thinks out loud — every move comes with
        its live reasoning, and you can question its strategy mid-game.
      </p>
      <form onSubmit={submit}>
        <label className="field-label" htmlFor="provider">
          Provider
        </label>
        <select
          id="provider"
          value={provider}
          onChange={(e) => setProvider(e.target.value)}
        >
          <option value="gemini">Google Gemini</option>
        </select>

        <label className="field-label" htmlFor="apikey">
          API key
        </label>
        <input
          id="apikey"
          type="password"
          autoComplete="off"
          placeholder="AIza..."
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
        />

        {error && <p className="key-error">{error}</p>}

        <button className="btn btn-primary" type="submit" disabled={busy || !apiKey.trim()}>
          {busy ? 'Checking key…' : 'Start playing'}
        </button>
      </form>
    </div>
  )
}
