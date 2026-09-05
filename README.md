# Chess-LLM

> Developed as part of a course I taught on how to use React, Flask and the MCP Python SDK to create LLM applications

Chess-LLM is an application that allows players to play against opponent's who think out loud. The chosen (and only supported) model is Gemini, using its generous free tier keys for testing.

- Player's can play against LLM, and ask about its strategy
- LLM's will identify player strategy and counteract
- LLM will maintain a continuous memory of its strategies, such that its gameplay does not change mid-game.
- LLM will develop confidence on the strategy that the player is using. (E.g. "70% confidence that the player is playing a Scotch Game") -> And use that to develop counter-strategy if needed

## Tech Stack
- **Frontend**: Written with React and Vite
- **Backend**: Flask, MCP Python SDK, and Postgres (only for persisting HTTP Sessions Cookies with API keys)
- **Chess Engine**: Python 3.12

## How to Use

### Prerequisites

- Python 3.12+
- Node 18+ (developed on Node 24)
- Postgres running locally. If it is unreachable the backend automatically
  falls back to a local SQLite file, so you can try the app without it.
- A Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey).
  The free tier is adequate, though if you are running locally, running stronger models would yield better results.

### 1. Configure secrets

Create a `.env` file in the project root:

```
SECRET_KEY=<random hex string>
ENCRYPTION_KEY=<Fernet key>
DATABASE_URL=postgresql+psycopg2://postgres:postgres@<db url and db name>
```

`SECRET_KEY` signs the session cookie and `ENCRYPTION_KEY` encrypts stored API
keys, so generate real values rather than inventing them:

```bash
python -c "import secrets; print('SECRET_KEY=' + secrets.token_hex(32))"
python -c "from cryptography.fernet import Fernet; print('ENCRYPTION_KEY=' + Fernet.generate_key().decode())"
```

`DATABASE_URL` is optional (it defaults to the value above, and the database is
created for you if it does not exist yet). Two other optional knobs:
`GEMINI_MODEL` overrides the default `gemini-3.5-flash-lite`, and
`GEMINI_TIMEOUT_MS` caps how long a stalled Gemini call may hang before the
engine plays a safe fallback move.


### 2. Start the backend

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # macOS/Linux: .venv/bin/pip
.venv/Scripts/python app.py                     # macOS/Linux: .venv/bin/python
```

Flask serves on `http://127.0.0.1:5000` and spawns the chess MCP server as a
child process on startup — you do not run that separately.

### 3. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**.
(For production run instead, `npm run build` and open
`http://127.0.0.1:5000`, where Flask serves the built assets itself and no dev
server is needed)

### 4. Play

1. Pick **Google Gemini** in the provider dropdown, paste your API key
2. Move pieces and ask questions :)

To detach your key from the browser, hit **Remove key** above the chat; that
deletes the encrypted row from the database.