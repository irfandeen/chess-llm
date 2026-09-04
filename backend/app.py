from __future__ import annotations

import json
import os
import random
import secrets
import threading
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, request, session, stream_with_context
from sqlalchemy import create_engine, text

import crypto
import llm
from db import ApiKey, db
from mcp_bridge import get_bridge

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


def _resolve_database_url() -> str:
    """Prefer Postgres (creating the database if needed); fall back to SQLite."""
    url = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg2://postgres:postgres@localhost:5432/chessllm",
    )
    if url.startswith("sqlite"):
        return url
    try:
        eng = create_engine(url, connect_args={"connect_timeout": 3})
        with eng.connect():
            pass
        return url
    except Exception:
        pass
    # Maybe the server is up but the database doesn't exist yet.
    try:
        base, dbname = url.rsplit("/", 1)
        admin = create_engine(
            f"{base}/postgres",
            isolation_level="AUTOCOMMIT",
            connect_args={"connect_timeout": 3},
        )
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{dbname}"'))
        return url
    except Exception:
        fallback = "sqlite:///" + str(
            (Path(__file__).resolve().parent / "keys.db").as_posix()
        )
        print(
            "WARNING: Postgres unreachable, falling back to SQLite at "
            f"{fallback}. Set DATABASE_URL in .env to use Postgres."
        )
        return fallback


app = Flask(__name__, static_folder=str(_FRONTEND_DIST), static_url_path="")
app.config.update(
    SECRET_KEY=os.environ["SECRET_KEY"],
    SQLALCHEMY_DATABASE_URI=_resolve_database_url(),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30,
)
db.init_app(app)
with app.app_context():
    db.create_all()

# Per-session volatile state (strategy log + chat transcript). Nothing here
# needs to survive a restart — only the cookie/API-key pair is persisted.
_mem: dict[str, dict] = {}
_mem_lock = threading.Lock()


def _uid() -> str:
    if "uid" not in session:
        session["uid"] = secrets.token_hex(16)
        session.permanent = True
    return session["uid"]


def _store(uid: str) -> dict:
    with _mem_lock:
        return _mem.setdefault(
            uid,
            {
                "strategy_log": [],
                "read_log": [],
                "chat": [],
                "human_color": "white",
            },
        )


def _api_key_for(uid: str) -> str | None:
    row = db.session.get(ApiKey, uid)
    if row is None:
        return None
    return crypto.decrypt_key(row.encrypted_key)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# ---------------------------------------------------------------- API key ---


@app.get("/api/key")
def key_status():
    uid = _uid()
    row = db.session.get(ApiKey, uid)
    return jsonify(
        {"has_key": row is not None, "provider": row.provider if row else None}
    )


@app.post("/api/key")
def set_key():
    uid = _uid()
    body = request.get_json(silent=True) or {}
    provider = (body.get("provider") or "gemini").lower()
    api_key = (body.get("api_key") or "").strip()

    if provider != "gemini":
        return jsonify({"error": "Only Gemini is supported for now."}), 400
    if not (20 <= len(api_key) <= 300):
        return jsonify({"error": "That doesn't look like a valid API key."}), 400

    try:
        llm.validate_key(api_key)
    except Exception:
        return (
            jsonify({"error": "Gemini rejected this key. Double-check it."}),
            400,
        )

    row = db.session.get(ApiKey, uid)
    if row is None:
        row = ApiKey(session_uid=uid, provider=provider)
        db.session.add(row)
    row.provider = provider
    row.encrypted_key = crypto.encrypt_key(api_key)
    db.session.commit()
    return jsonify({"ok": True, "provider": provider})


@app.post("/api/dev/use-env-key")
def dev_use_env_key():
    """Local-dev convenience: register GEMINI_KEY from .env for this session.

    Disabled unless DEV_ALLOW_ENV_KEY=1 is set in the server environment; the
    key itself never leaves the server.
    """
    if os.environ.get("DEV_ALLOW_ENV_KEY") != "1":
        return jsonify({"error": "Not found"}), 404
    env_key = os.environ.get("GEMINI_KEY")
    if not env_key:
        return jsonify({"error": "GEMINI_KEY not set in .env"}), 400
    uid = _uid()
    row = db.session.get(ApiKey, uid)
    if row is None:
        row = ApiKey(session_uid=uid, provider="gemini")
        db.session.add(row)
    row.encrypted_key = crypto.encrypt_key(env_key)
    db.session.commit()
    return jsonify({"ok": True, "provider": "gemini"})


@app.delete("/api/key")
def delete_key():
    uid = _uid()
    row = db.session.get(ApiKey, uid)
    if row is not None:
        db.session.delete(row)
        db.session.commit()
    return jsonify({"ok": True})


# ------------------------------------------------------------------- game ---


def _payload(uid: str, state: dict) -> dict:
    store = _store(uid)
    return {
        "state": state,
        "strategy_log": store["strategy_log"],
        "human_color": store["human_color"],
    }


@app.get("/api/game")
def game_state():
    uid = _uid()
    state = get_bridge().call("get_state", game_id=uid)
    return jsonify(_payload(uid, state))


@app.post("/api/game/reset")
def game_reset():
    uid = _uid()
    body = request.get_json(silent=True) or {}
    color = (body.get("color") or _store(uid)["human_color"]).lower()
    if color not in ("white", "black"):
        return jsonify({"error": "Colour must be white or black."}), 400

    state = get_bridge().call("new_game", game_id=uid)
    store = _store(uid)
    store["strategy_log"] = []
    store["read_log"] = []
    store["chat"] = []
    store["human_color"] = color
    return jsonify(_payload(uid, state))


def _undo_target(n: int, human_white: bool) -> int:
    """Largest ply < n where it is the human's turn again.

    The human is on move at ply p when p is even (playing White) or odd
    (playing Black); playing Black, ply 0 is skipped since the LLM's opening
    move belongs to the engine, not the human.
    """
    floor = 0 if human_white else 1
    for p in range(n - 1, floor - 1, -1):
        if (p % 2 == 0) == human_white:
            return p
    return floor


@app.post("/api/game/undo")
def game_undo():
    uid = _uid()
    bridge = get_bridge()
    store = _store(uid)
    state = bridge.call("get_state", game_id=uid)
    n = len(state["history"])
    human_white = store["human_color"] == "white"
    if n <= (0 if human_white else 1):
        return jsonify(_payload(uid, state))

    target = _undo_target(n, human_white)
    state = bridge.call("undo_moves", game_id=uid, count=n - target)
    new_len = len(state["history"])
    store["strategy_log"] = [
        s for s in store["strategy_log"] if s["move_no"] <= new_len
    ]
    store["read_log"] = [r for r in store["read_log"] if r["move_no"] <= new_len]
    store["chat"] = [c for c in store["chat"] if c.get("ply", 0) <= new_len]
    return jsonify(_payload(uid, state))


# ------------------------------------------------------- move + LLM reply ---


def _fallback_move(legal_moves: list[str]) -> str:
    captures_center = [m for m in legal_moves if m[2] in "cdef" and m[3] in "3456"]
    return random.choice(captures_center or legal_moves)


@app.post("/api/game/move")
def game_move():
    uid = _uid()
    body = request.get_json(silent=True) or {}
    uci = (body.get("uci") or "").strip().lower()
    api_key = _api_key_for(uid)

    if api_key is None:
        return jsonify({"error": "Add your API key first."}), 401

    bridge = get_bridge()
    store = _store(uid)
    ai_color = "black" if store["human_color"] == "white" else "white"

    # An empty uci means "just make your move" — used when the LLM plays White
    # and opens the game.
    if not uci:
        opening_state = bridge.call("get_state", game_id=uid)
        if opening_state["turn"] != ai_color:
            return jsonify({"error": "It is your move."}), 400

    def generate():
        if uci:
            try:
                state = bridge.call("make_move", game_id=uid, uci=uci)
            except ValueError as exc:
                yield _sse("error", {"message": str(exc)})
                return
            yield _sse("user_move", {"uci": uci, "state": state})
            if state["game_over"]:
                yield _sse("done", {"status": state["status"], "game_over": True})
                return
        else:
            state = bridge.call("get_state", game_id=uid)

        analysis = bridge.call("get_context", game_id=uid)
        legal = state["legal_moves"]
        last_move_desc = uci if uci else "(none — you open the game)"

        applied_uci = None
        new_state = None
        strategy = None
        read = None
        llm_failed = False
        explanation_parts: list[str] = []
        head_buf = ""
        phase = "head"

        def try_apply(candidate: str):
            nonlocal applied_uci, new_state
            new_state = bridge.call("make_move", game_id=uid, uci=candidate)
            applied_uci = candidate

        try:
            stream = llm.stream_move(
                api_key,
                analysis,
                store["strategy_log"],
                store["read_log"],
                legal,
                last_move_desc,
                ai_color,
            )
            for chunk in stream:
                if phase == "explain":
                    explanation_parts.append(chunk)
                    yield _sse("token", {"text": chunk})
                    continue

                head_buf += chunk
                while phase == "head" and "\n" in head_buf:
                    line, head_buf = head_buf.split("\n", 1)
                    stripped = line.strip().strip("`").strip()
                    if not stripped:
                        continue
                    if applied_uci is None:
                        candidate = llm.parse_move(stripped)
                        if candidate is None:
                            continue  # ignore junk before the MOVE line
                        try_apply(candidate)  # raises ValueError if illegal
                        yield _sse(
                            "move", {"uci": applied_uci, "state": new_state}
                        )
                        continue

                    parsed_read = llm.parse_read(stripped)
                    if parsed_read is not None and read is None:
                        read = parsed_read
                        yield _sse("read", {"text": read})
                        continue

                    parsed_strategy = llm.parse_strategy(stripped)
                    if parsed_strategy is not None and strategy is None:
                        strategy = parsed_strategy
                        yield _sse("strategy", {"text": strategy})
                        continue

                    # Neither header line: the reasoning has begun.
                    phase = "explain"
                    rest = line + ("\n" + head_buf if head_buf else "")
                    explanation_parts.append(rest)
                    yield _sse("token", {"text": rest})
                    head_buf = ""

            # Stream ended: flush anything still buffered.
            if phase == "head" and head_buf.strip():
                stripped = head_buf.strip().strip("`").strip()
                if applied_uci is None:
                    candidate = llm.parse_move(stripped)
                    if candidate is not None:
                        try_apply(candidate)
                        yield _sse(
                            "move", {"uci": applied_uci, "state": new_state}
                        )
                else:
                    explanation_parts.append(head_buf)
                    yield _sse("token", {"text": head_buf})
        except Exception:
            llm_failed = True  # fall through to the fallback path below

        if applied_uci is None:
            # One retry with explicit feedback (unless the API itself failed,
            # where a second call would only stall the user further).
            full_text = ""
            try:
                if llm_failed:
                    raise RuntimeError("skip retry")
                full_text = "".join(
                    llm.stream_move(
                        api_key,
                        analysis,
                        store["strategy_log"],
                        store["read_log"],
                        legal,
                        last_move_desc,
                        ai_color,
                        feedback=(
                            "Your previous answer did not contain a legal "
                            "move. You MUST pick one move exactly from the "
                            "legal moves list."
                        ),
                    )
                )
            except Exception:
                pass
            candidate = llm.parse_move(full_text or "")
            if candidate is None or candidate not in {
                m[:4] for m in legal
            } | set(legal):
                candidate = _fallback_move(legal)
                full_text = (
                    "I had trouble settling on a line just now, so I'm "
                    "playing a solid, safe move and will regroup next turn."
                )
            try:
                try_apply(candidate)
            except ValueError:
                try_apply(_fallback_move(legal))
            yield _sse("move", {"uci": applied_uci, "state": new_state})
            read = read or llm.parse_read(full_text)
            if read:
                yield _sse("read", {"text": read})
            strategy = strategy or llm.parse_strategy(full_text)
            if strategy:
                yield _sse("strategy", {"text": strategy})
            explanation = llm.strip_protocol_lines(full_text)
            if explanation:
                explanation_parts.append(explanation)
                yield _sse("token", {"text": explanation})

        ply = len(new_state["history"])
        if strategy:
            log = store["strategy_log"]
            if not log or log[-1]["text"] != strategy:
                log.append({"move_no": ply, "text": strategy})
        if read:
            reads = store["read_log"]
            if not reads or reads[-1]["text"] != read:
                reads.append({"move_no": ply, "text": read})
        explanation_text = llm.strip_protocol_lines("".join(explanation_parts))
        if explanation_text:
            store["chat"].append(
                {"role": "model", "text": explanation_text, "ply": ply}
            )
        yield _sse(
            "done",
            {"status": new_state["status"], "game_over": new_state["game_over"]},
        )

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ------------------------------------------------------------------- chat ---


@app.post("/api/chat")
def chat():
    uid = _uid()
    body = request.get_json(silent=True) or {}
    question = (body.get("message") or "").strip()
    api_key = _api_key_for(uid)

    if api_key is None:
        return jsonify({"error": "Add your API key first."}), 401
    if not question or len(question) > 2000:
        return jsonify({"error": "Message must be 1-2000 characters."}), 400

    bridge = get_bridge()
    store = _store(uid)
    state = bridge.call("get_state", game_id=uid)
    analysis = bridge.call("get_context", game_id=uid)
    ai_color = "black" if store["human_color"] == "white" else "white"
    ply = len(state["history"])
    store["chat"].append({"role": "user", "text": question, "ply": ply})

    def generate():
        parts: list[str] = []
        try:
            for chunk in llm.stream_chat(
                api_key,
                analysis,
                store["strategy_log"],
                store["read_log"],
                store["chat"][:-1],
                question,
                ai_color,
            ):
                parts.append(chunk)
                yield _sse("token", {"text": chunk})
        except Exception:
            yield _sse(
                "error", {"message": "The model didn't answer. Try again."}
            )
            return
        store["chat"].append(
            {"role": "model", "text": "".join(parts), "ply": ply}
        )
        yield _sse("done", {})

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# -------------------------------------------------------- frontend (prod) ---


@app.get("/")
def index():
    if (_FRONTEND_DIST / "index.html").exists():
        return app.send_static_file("index.html")
    return (
        "Frontend not built. Run `npm run build` in frontend/ or use the "
        "Vite dev server.",
        200,
    )


if __name__ == "__main__":
    get_bridge()  # start the MCP server before accepting requests
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
