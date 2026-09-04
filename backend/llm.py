"""Gemini integration: move selection + streamed thought process.

Token-frugal by design (users run free-tier keys): one streaming call per
move, compact grounded context, minimal thinking, capped output. The reply
protocol front-loads the move so the board can update before the reasoning
finishes streaming:

    MOVE: e7e5
    READ: Sicilian Defence, Najdorf setup — 80% confident
    STRATEGY: <one short line — current plan, updated when it changes>
    <3-5 sentences of reasoning: the evidence behind the read, then the
     counter-plan that follows from it>
"""
from __future__ import annotations

import os
import re
from typing import Iterator

from google import genai
from google.genai import types

# flash-lite has the best free-tier rate limits and lowest latency; the engine
# supplies the legal moves, so a lite model plays well enough for this UX.
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")

_MOVE_RE = re.compile(r"MOVE:\s*([a-h][1-8][a-h][1-8][qrbn]?)", re.IGNORECASE)
_STRATEGY_RE = re.compile(r"STRATEGY:\s*(.+)", re.IGNORECASE)
_READ_RE = re.compile(r"READ:\s*(.+)", re.IGNORECASE)

_TIMEOUT_MS = int(os.environ.get("GEMINI_TIMEOUT_MS", "45000"))


def _system(ai_color: str) -> str:
    human = "White" if ai_color == "black" else "Black"
    return f"""You are a chess AI playing {ai_color.upper()} against a human \
playing {human}, and the human watches your thought process live. You reason \
like an analyst: name what the opponent is doing, say how sure you are, then \
derive your move from that read.

Reply in EXACTLY this format, no markdown, no code fences:
MOVE: <one move copied from the provided legal moves, in UCI like e7e5>
READ: <what the human is playing, with a confidence percentage — e.g. \
"Sicilian Defence, heading for a Najdorf — 80% confident" or "building a \
kingside pawn storm — 55% confident" or "racing a passed pawn to promote — \
75% confident">
STRATEGY: <your counter-plan in under 12 words; keep it stable across moves \
unless the position genuinely demands a change>
<Then 3-5 short sentences of reasoning, in this order: (1) the concrete \
evidence for your READ — the specific moves, pawn structure or piece \
placement that point to it; (2) what that plan threatens if you ignore it; \
(3) how your move counters it and serves your strategy. Address the human as \
"you". Be specific and conversational, never generic.>

Rules for the READ line:
- Ground it in the position facts you are given (opening name, phase, \
material, pawns near promotion) and the actual move history.
- Your confidence must reflect the evidence: high (75-95%) when the move \
order or structure is unmistakable, moderate (50-70%) when the plan is still \
taking shape, low (30-45%) when you are genuinely guessing. Never state 100%.
- If your read changes from last move, say so explicitly and explain what \
changed your mind."""


_CHAT_SYSTEM_TEMPLATE = """You are a chess AI playing {ai_color} against a \
human. Mid-game, the human is asking you a question about your play. Answer \
honestly from your strategy log, your previous reads and the move history — \
if you changed plans or misread their intentions, own it and explain what \
changed. Keep confidence estimates honest. 2-4 sentences, plain text, no \
markdown."""


def make_client(api_key: str) -> genai.Client:
    # A hard timeout keeps free-tier throttling stalls from hanging the UI;
    # the caller falls back to a safe engine move instead.
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=_TIMEOUT_MS),
    )


def validate_key(api_key: str) -> None:
    """Raise if the key can't authenticate (cheap metadata call, no tokens)."""
    client = make_client(api_key)
    next(iter(client.models.list(config={"page_size": 1})), None)


def _stream(
    api_key: str,
    prompt: str,
    system: str,
    max_tokens: int,
    temperature: float,
) -> Iterator[str]:
    """Stream text chunks; keep thinking minimal to spare free-tier tokens.

    Models that reject thinking_level (older Gemini) get one retry without it.
    """
    client = make_client(api_key)

    def run(thinking):
        cfg = types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            max_output_tokens=max_tokens,
            thinking_config=thinking,
        )
        return client.models.generate_content_stream(
            model=MODEL, contents=prompt, config=cfg
        )

    try:
        stream = run(types.ThinkingConfig(thinking_level="minimal"))
        first = next(iter(stream), None)
    except Exception:
        stream = run(None)
        first = next(iter(stream), None)

    if first is not None:
        if first.text:
            yield first.text
        for chunk in stream:
            if chunk.text:
                yield chunk.text


def _facts_block(analysis: dict) -> str:
    lines = [
        f"Game phase: {analysis.get('phase', 'unknown')}",
        f"Material: {analysis.get('material_balance', 'unknown')}",
    ]
    opening = analysis.get("opening")
    if opening:
        lines.append(f"Opening book match (verified by the engine): {opening}")
    else:
        lines.append("Opening book match: none — this is off the book lines")
    promo = analysis.get("promotion_watch") or []
    if promo:
        lines.append("Pawns near promotion: " + "; ".join(promo))
    return "\n".join(lines)


def _history_block(history: list[str]) -> str:
    """Number the moves so the model can reason about the sequence."""
    if not history:
        return "(no moves yet)"
    rounds = []
    for i in range(0, len(history), 2):
        white = history[i]
        black = history[i + 1] if i + 1 < len(history) else ""
        rounds.append(f"{i // 2 + 1}. {white} {black}".strip())
    return " ".join(rounds)


def _context_block(
    analysis: dict,
    strategy_log: list[dict],
    read_log: list[dict],
    legal_moves: list[str],
    last_user_move: str,
    ai_color: str,
) -> str:
    history = analysis.get("history", [])
    strat = (
        "\n".join(f"- after ply {s['move_no']}: {s['text']}" for s in strategy_log)
        if strategy_log
        else "(none yet — set one)"
    )
    reads = (
        "\n".join(f"- after ply {r['move_no']}: {r['text']}" for r in read_log)
        if read_log
        else "(none yet)"
    )
    return (
        f"Board (uppercase = White, lowercase = Black; you are {ai_color}):\n"
        f"{analysis.get('board', '')}\n\n"
        f"{_facts_block(analysis)}\n\n"
        f"Move history: {_history_block(history)}\n"
        f"Opponent's last move: {last_user_move}\n\n"
        f"Your previous reads of the opponent:\n{reads}\n\n"
        f"Your strategy log so far:\n{strat}\n\n"
        f"Your legal moves (copy ONE exactly): {' '.join(legal_moves)}"
    )


def stream_move(
    api_key: str,
    analysis: dict,
    strategy_log: list[dict],
    read_log: list[dict],
    legal_moves: list[str],
    last_user_move: str,
    ai_color: str = "black",
    feedback: str | None = None,
) -> Iterator[str]:
    """Yield raw text chunks from Gemini for one move decision."""
    prompt = _context_block(
        analysis, strategy_log, read_log, legal_moves, last_user_move, ai_color
    )
    if feedback:
        prompt += f"\n\nIMPORTANT: {feedback}"
    yield from _stream(api_key, prompt, _system(ai_color), 600, 0.7)


def stream_chat(
    api_key: str,
    analysis: dict,
    strategy_log: list[dict],
    read_log: list[dict],
    chat_history: list[dict],
    question: str,
    ai_color: str = "black",
) -> Iterator[str]:
    """Yield answer chunks for a mid-game question from the human."""
    history = analysis.get("history", [])
    strat = (
        "\n".join(f"- after ply {s['move_no']}: {s['text']}" for s in strategy_log)
        if strategy_log
        else "(none yet)"
    )
    reads = (
        "\n".join(f"- after ply {r['move_no']}: {r['text']}" for r in read_log)
        if read_log
        else "(none yet)"
    )
    recent = "\n".join(
        f"{'Human' if m['role'] == 'user' else 'You'}: {m['text']}"
        for m in chat_history[-6:]
    )
    prompt = (
        f"Board (uppercase = White, lowercase = Black; you are {ai_color}):\n"
        f"{analysis.get('board', '')}\n\n"
        f"{_facts_block(analysis)}\n\n"
        f"Move history: {_history_block(history)}\n\n"
        f"Your reads so far:\n{reads}\n\nYour strategy log:\n{strat}\n\n"
        f"Recent conversation:\n{recent or '(none)'}\n\n"
        f"Human asks: {question}"
    )
    yield from _stream(
        api_key,
        prompt,
        _CHAT_SYSTEM_TEMPLATE.format(ai_color=ai_color.upper()),
        350,
        0.6,
    )


def parse_move(text: str) -> str | None:
    m = _MOVE_RE.search(text)
    return m.group(1).lower() if m else None


def parse_strategy(text: str) -> str | None:
    m = _STRATEGY_RE.search(text)
    return m.group(1).strip() if m else None


def parse_read(text: str) -> str | None:
    m = _READ_RE.search(text)
    return m.group(1).strip() if m else None


def strip_protocol_lines(text: str) -> str:
    """Remove MOVE:/READ:/STRATEGY: lines and fences, leaving the reasoning."""
    out = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("```"):
            continue
        if _MOVE_RE.match(s) or _STRATEGY_RE.match(s) or _READ_RE.match(s):
            continue
        out.append(line)
    return "\n".join(out).strip()
