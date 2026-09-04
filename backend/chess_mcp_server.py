"""MCP server exposing chess-engine.py as tools over stdio.

The Flask backend connects to this process as an MCP client and performs
every chess operation (state, legal moves, applying moves, undo) through
these tools. The same tool results are what get fed to the LLM, so the
engine is the single source of truth for the game.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Optional

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

# chess-engine.py has a hyphen in its name, so import it from its file path.
_ENGINE_PATH = Path(__file__).resolve().parent.parent / "chess-engine.py"
_spec = importlib.util.spec_from_file_location("chess_engine", _ENGINE_PATH)
_engine_mod = importlib.util.module_from_spec(_spec)
sys.modules["chess_engine"] = _engine_mod
_spec.loader.exec_module(_engine_mod)

ChessBoard = _engine_mod.ChessBoard
Color = _engine_mod.Color
PieceType = _engine_mod.PieceType

_PROMO = {
    "q": PieceType.QUEEN,
    "r": PieceType.ROOK,
    "b": PieceType.BISHOP,
    "n": PieceType.KNIGHT,
}


class Engine(ChessBoard):
    """ChessBoard with a safe default promotion during legal-move probing.

    ChessBoard._is_legal_move simulates moves via _apply_move without a
    promotion piece, which raises on promotion candidates; defaulting to
    a queen keeps enumeration total and never loses a legal option.
    """

    def _apply_move(self, start, end, promotion=None):
        if promotion is None and self._is_promotion_move(start, end):
            promotion = PieceType.QUEEN
        super()._apply_move(start, end, promotion)


class Game:
    def __init__(self) -> None:
        self.board = Engine()
        self.history: list[str] = []  # UCI strings, e.g. "e2e4", "e7e8q"

    def replay(self, moves: list[str]) -> None:
        self.board = Engine()
        self.history = []
        for uci in moves:
            self.apply(uci)

    def apply(self, uci: str) -> None:
        start, end, promo = _parse_uci(uci)
        piece = self.board.board[start]
        if piece is None:
            raise ValueError(f"No piece on {uci[:2]}")

        is_castle = (
            piece.kind == PieceType.KING
            and abs(ord(end[0]) - ord(start[0])) == 2
        )
        is_ep = (
            piece.kind == PieceType.PAWN
            and start[0] != end[0]
            and self.board.board[end] is None
        )
        if is_castle or is_ep:
            self.board.special_move(start, end)
        else:
            self.board.make_move(start, end, promo)
        self.history.append(uci)


_games: dict[str, Game] = {}


def _parse_uci(uci: str):
    uci = uci.strip().lower()
    if len(uci) not in (4, 5):
        raise ValueError(f"Bad move format: {uci!r}")
    start = (uci[0], int(uci[1]))
    end = (uci[2], int(uci[3]))
    promo = _PROMO.get(uci[4]) if len(uci) == 5 else None
    return start, end, promo


def _square_str(sq) -> str:
    return f"{sq[0]}{sq[1]}"


def _game(game_id: str) -> Game:
    if game_id not in _games:
        _games[game_id] = Game()
    return _games[game_id]


def _status_word(board: Engine) -> str:
    return {
        -1: "stalemate",
        0: "ongoing",
        1: "check",
        2: "checkmate",
    }[board.is_check()]


def _state_dict(game: Game) -> dict:
    board = game.board
    grid = []
    for rank in range(8, 0, -1):
        row = []
        for file in ChessBoard.FILES:
            piece = board.board[(file, rank)]
            if piece is None:
                row.append(None)
            else:
                row.append({"color": piece.color.value, "kind": piece.kind.value})
        grid.append(row)

    legal = sorted(
        _square_str(a) + _square_str(b)
        for a, b in board.get_legal_moves(board.turn)
    )
    status = _status_word(board)
    return {
        "grid": grid,
        "turn": board.turn.value,
        "status": status,
        "history": list(game.history),
        "legal_moves": legal,
        "game_over": status in ("checkmate", "stalemate"),
    }


# Opening book keyed by UCI move-sequence prefix; longest match wins. This
# grounds the LLM's opening recognition in fact rather than recall, so its
# stated confidence means something.
_OPENINGS = {
    "e2e4": "King's Pawn Opening",
    "e2e4 c7c5": "Sicilian Defence",
    "e2e4 c7c5 g1f3": "Sicilian Defence, Open",
    "e2e4 c7c5 g1f3 d7d6": "Sicilian Defence, Najdorf/Dragon complex",
    "e2e4 c7c5 g1f3 b8c6": "Sicilian Defence, Old Sicilian",
    "e2e4 c7c5 g1f3 e7e6": "Sicilian Defence, Taimanov/Kan complex",
    "e2e4 c7c5 b1c3": "Sicilian Defence, Closed",
    "e2e4 c7c5 c2c3": "Sicilian Defence, Alapin",
    "e2e4 c7c5 d2d4": "Sicilian Defence, Smith-Morra Gambit",
    "e2e4 e7e5": "Open Game",
    "e2e4 e7e5 g1f3": "King's Knight Opening",
    "e2e4 e7e5 g1f3 b8c6 f1b5": "Ruy Lopez (Spanish)",
    "e2e4 e7e5 g1f3 b8c6 f1c4": "Italian Game",
    "e2e4 e7e5 g1f3 b8c6 d2d4": "Scotch Game",
    "e2e4 e7e5 g1f3 g8f6": "Petrov (Russian) Defence",
    "e2e4 e7e5 f2f4": "King's Gambit",
    "e2e4 e7e5 b1c3": "Vienna Game",
    "e2e4 e7e6": "French Defence",
    "e2e4 c7c6": "Caro-Kann Defence",
    "e2e4 d7d5": "Scandinavian Defence",
    "e2e4 g8f6": "Alekhine's Defence",
    "e2e4 d7d6": "Pirc Defence",
    "e2e4 g7g6": "Modern Defence",
    "d2d4": "Queen's Pawn Opening",
    "d2d4 d7d5": "Closed Game",
    "d2d4 d7d5 c2c4": "Queen's Gambit",
    "d2d4 d7d5 c2c4 d5c4": "Queen's Gambit Accepted",
    "d2d4 d7d5 c2c4 e7e6": "Queen's Gambit Declined",
    "d2d4 d7d5 c2c4 c7c6": "Slav Defence",
    "d2d4 g8f6": "Indian Defence",
    "d2d4 g8f6 c2c4 e7e6": "Nimzo/Queen's Indian complex",
    "d2d4 g8f6 c2c4 g7g6": "King's Indian Defence",
    "d2d4 g8f6 c2c4 c7c5": "Benoni Defence",
    "d2d4 f7f5": "Dutch Defence",
    "c2c4": "English Opening",
    "g1f3": "Réti Opening",
    "f2f4": "Bird's Opening",
    "b2b3": "Nimzo-Larsen Attack",
    "g2g3": "King's Fianchetto Opening",
}

_VALUES = {
    PieceType.QUEEN: 9,
    PieceType.ROOK: 5,
    PieceType.BISHOP: 3,
    PieceType.KNIGHT: 3,
    PieceType.PAWN: 1,
    PieceType.KING: 0,
}


def _detect_opening(history: list[str]) -> str | None:
    key = " ".join(history[:12])
    best: tuple[str, str] | None = None
    for prefix, name in _OPENINGS.items():
        if key == prefix or key.startswith(prefix + " "):
            if best is None or len(prefix) > len(best[0]):
                best = (prefix, name)
    return best[1] if best else None


def _analyse(game: Game) -> dict:
    """Facts about the position the LLM would otherwise have to guess at."""
    board = game.board
    material = {Color.WHITE: 0, Color.BLACK: 0}
    officers = {Color.WHITE: 0, Color.BLACK: 0}  # non-pawn, non-king value
    queens = {Color.WHITE: 0, Color.BLACK: 0}
    advanced: list[str] = []

    for square, piece in board.board.items():
        if piece is None:
            continue
        value = _VALUES[piece.kind]
        material[piece.color] += value
        if piece.kind not in (PieceType.PAWN, PieceType.KING):
            officers[piece.color] += value
        if piece.kind == PieceType.QUEEN:
            queens[piece.color] += 1
        if piece.kind == PieceType.PAWN:
            rank = square[1]
            steps_to_promote = (8 - rank) if piece.color == Color.WHITE else (rank - 1)
            if steps_to_promote <= 2:
                advanced.append(
                    f"{piece.color.value} pawn on {_square_str(square)} "
                    f"({steps_to_promote} square(s) from promoting)"
                )

    total_officers = officers[Color.WHITE] + officers[Color.BLACK]
    ply = len(game.history)
    if total_officers <= 13 or (not any(queens.values()) and total_officers <= 20):
        phase = "endgame"
    elif ply <= 16 and total_officers >= 28:
        phase = "opening"
    else:
        phase = "middlegame"

    diff = material[Color.WHITE] - material[Color.BLACK]
    if diff == 0:
        balance = "material is level"
    else:
        leader = "White" if diff > 0 else "Black"
        balance = f"{leader} is up {abs(diff)} point(s) of material"

    return {
        "phase": phase,
        "opening": _detect_opening(game.history),
        "material_balance": balance,
        "promotion_watch": advanced,
        "ply": ply,
    }


def _ascii_board(board: Engine) -> str:
    """Compact text board for the LLM: uppercase = white, lowercase = black."""
    lines = []
    for rank in range(8, 0, -1):
        cells = []
        for file in ChessBoard.FILES:
            piece = board.board[(file, rank)]
            if piece is None:
                cells.append(".")
            else:
                ch = piece.kind.value
                cells.append(ch if piece.color == Color.WHITE else ch.lower())
        lines.append(f"{rank} " + " ".join(cells))
    lines.append("  a b c d e f g h")
    return "\n".join(lines)


mcp = MCPServer("chess-engine")


@mcp.tool()
def new_game(game_id: str) -> dict:
    """Start a fresh game for this game_id and return its state."""
    _games[game_id] = Game()
    return _state_dict(_games[game_id])


@mcp.tool()
def get_state(game_id: str) -> dict:
    """Get the full state: board grid, turn, status, history, legal moves."""
    return _state_dict(_game(game_id))


@mcp.tool()
def get_board_text(game_id: str) -> dict:
    """Get a compact ASCII diagram of the board (for LLM context)."""
    game = _game(game_id)
    return {"board": _ascii_board(game.board), "turn": game.board.turn.value}


@mcp.tool()
def get_context(game_id: str) -> dict:
    """Board diagram plus positional facts: phase, opening match, material,
    and pawns close to promoting. Intended as grounding context for an LLM."""
    game = _game(game_id)
    analysis = _analyse(game)
    analysis["board"] = _ascii_board(game.board)
    analysis["turn"] = game.board.turn.value
    analysis["history"] = list(game.history)
    return analysis


@mcp.tool()
def get_legal_moves(game_id: str) -> dict:
    """List every legal move for the side to move, in UCI notation."""
    return {"legal_moves": _state_dict(_game(game_id))["legal_moves"]}


@mcp.tool()
def make_move(game_id: str, uci: str) -> dict:
    """Apply a move in UCI notation (e.g. e2e4, e7e8q). Errors if illegal."""
    game = _game(game_id)
    state = _state_dict(game)
    uci_n = uci.strip().lower()
    if uci_n[:4] not in {c[:4] for c in state["legal_moves"]}:
        raise ToolError(f"Illegal move: {uci}")
    try:
        game.apply(uci_n)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    return _state_dict(game)


@mcp.tool()
def undo_moves(game_id: str, count: int = 2) -> dict:
    """Undo the last `count` half-moves by replaying history."""
    game = _game(game_id)
    keep = game.history[: max(0, len(game.history) - count)]
    game.replay(keep)
    return _state_dict(game)


if __name__ == "__main__":
    mcp.run(transport="stdio")
