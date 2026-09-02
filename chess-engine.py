from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple


Square = Tuple[str, int]


class Color(Enum):
    WHITE = "white"
    BLACK = "black"


class PieceType(Enum):
    KING = "K"
    QUEEN = "Q"
    ROOK = "R"
    BISHOP = "B"
    KNIGHT = "N"
    PAWN = "P"


@dataclass
class Piece:
    color: Color
    kind: PieceType


class ChessBoard:
    FILES = "abcdefgh"
    RANKS = range(1, 9)

    def __init__(self):
        self.board = self._create_board()
        self.turn = Color.WHITE

        self.castling_rights = {
            Color.WHITE: {"king_side": True, "queen_side": True},
            Color.BLACK: {"king_side": True, "queen_side": True},
        }

        self.en_passant_target: Optional[Square] = None

    def get_board(self):
        return self.board.copy()

    def make_move(
        self,
        start: Square,
        end: Square,
        promotion: Optional[PieceType] = None,
    ) -> None:
        self._validate_square(start)
        self._validate_square(end)

        piece = self.board[start]

        if piece is None:
            raise ValueError(f"No piece at {start}")

        if piece.color != self.turn:
            raise ValueError("It is not this piece's turn.")

        if not self._is_legal_move(start, end):
            raise ValueError(f"Illegal move: {start} -> {end}")

        self._apply_move(start, end, promotion)
        self.turn = self._opposite_color(self.turn)

    def special_move(
        self,
        start: Square,
        end: Square,
        promotion: Optional[PieceType] = None,
    ) -> None:
        piece = self.board[start]

        if piece is None:
            raise ValueError(f"No piece at {start}")

        if piece.color != self.turn:
            raise ValueError("It is not this piece's turn.")

        if piece.kind == PieceType.KING and self._is_castling(start, end):
            self._castle(start, end)
        elif piece.kind == PieceType.PAWN and self._is_en_passant(start, end):
            self._en_passant(start, end)
        elif piece.kind == PieceType.PAWN and self._is_promotion_move(start, end):
            self.make_move(start, end, promotion)
            return
        else:
            raise ValueError("Not a valid special move.")

        self.turn = self._opposite_color(self.turn)

    def is_check(self, color: Optional[Color] = None) -> int:
        """
        -1 -> Stalemate
         0 -> No check
         1 -> Check
         2 -> Checkmate
        """
        color = color or self.turn

        in_check = self._is_in_check(color)
        legal_moves = self._get_legal_moves(color)

        if not legal_moves:
            return 2 if in_check else -1

        return 1 if in_check else 0

    def get_legal_moves(self, color: Optional[Color] = None):
        color = color or self.turn
        return self._get_legal_moves(color)

    def is_game_over(self) -> bool:
        return self.is_check() in (-1, 2)

    def _create_board(self):
        board = {
            (file, rank): None
            for file in self.FILES
            for rank in self.RANKS
        }

        for file in self.FILES:
            board[(file, 2)] = Piece(Color.WHITE, PieceType.PAWN)
            board[(file, 7)] = Piece(Color.BLACK, PieceType.PAWN)

        back_rank = [
            PieceType.ROOK,
            PieceType.KNIGHT,
            PieceType.BISHOP,
            PieceType.QUEEN,
            PieceType.KING,
            PieceType.BISHOP,
            PieceType.KNIGHT,
            PieceType.ROOK,
        ]

        for file, piece_type in zip(self.FILES, back_rank):
            board[(file, 1)] = Piece(Color.WHITE, piece_type)
            board[(file, 8)] = Piece(Color.BLACK, piece_type)

        return board

    def _is_legal_move(self, start: Square, end: Square) -> bool:
        piece = self.board[start]

        if piece is None:
            return False

        target = self.board[end]

        if target is not None and target.color == piece.color:
            return False

        if not self._is_piece_move_valid(start, end):
            return False

        state = self._save_state()

        try:
            self._apply_move(start, end)
            return not self._is_in_check(piece.color)
        finally:
            self._restore_state(state)

    def _is_piece_move_valid(self, start: Square, end: Square) -> bool:
        piece = self.board[start]

        if piece is None:
            return False

        validators = {
            PieceType.PAWN: self._valid_pawn_move,
            PieceType.KNIGHT: self._valid_knight_move,
            PieceType.BISHOP: self._valid_bishop_move,
            PieceType.ROOK: self._valid_rook_move,
            PieceType.QUEEN: self._valid_queen_move,
            PieceType.KING: self._valid_king_move,
        }

        return validators[piece.kind](start, end)

    def _valid_pawn_move(self, start: Square, end: Square) -> bool:
        piece = self.board[start]
        assert piece is not None

        direction = 1 if piece.color == Color.WHITE else -1
        start_rank = 2 if piece.color == Color.WHITE else 7

        dx = self._file_index(end[0]) - self._file_index(start[0])
        dy = end[1] - start[1]

        if dx == 0 and dy == direction:
            return self.board[end] is None

        if dx == 0 and dy == 2 * direction:
            middle = (start[0], start[1] + direction)

            return (
                start[1] == start_rank
                and self.board[middle] is None
                and self.board[end] is None
            )

        if abs(dx) == 1 and dy == direction:
            if self.board[end] is not None:
                return True

            return self._is_en_passant(start, end)

        return False

    def _valid_knight_move(self, start: Square, end: Square) -> bool:
        dx = abs(self._file_index(end[0]) - self._file_index(start[0]))
        dy = abs(end[1] - start[1])

        return (dx, dy) in {(1, 2), (2, 1)}

    def _valid_bishop_move(self, start: Square, end: Square) -> bool:
        dx = abs(self._file_index(end[0]) - self._file_index(start[0]))
        dy = abs(end[1] - start[1])

        return dx == dy and self._path_is_clear(start, end)

    def _valid_rook_move(self, start: Square, end: Square) -> bool:
        dx = abs(self._file_index(end[0]) - self._file_index(start[0]))
        dy = abs(end[1] - start[1])

        return (dx == 0 or dy == 0) and self._path_is_clear(start, end)

    def _valid_queen_move(self, start: Square, end: Square) -> bool:
        return (
            self._valid_bishop_move(start, end)
            or self._valid_rook_move(start, end)
        )

    def _valid_king_move(self, start: Square, end: Square) -> bool:
        dx = abs(self._file_index(end[0]) - self._file_index(start[0]))
        dy = abs(end[1] - start[1])

        return max(dx, dy) == 1 or self._is_castling(start, end)

    def _is_in_check(self, color: Color) -> bool:
        king = self._find_king(color)

        if king is None:
            raise ValueError(f"{color.value} has no king.")

        return self._is_square_attacked(
            king,
            self._opposite_color(color),
        )

    def _is_square_attacked(self, square: Square, by_color: Color) -> bool:
        return any(
            piece is not None
            and piece.color == by_color
            and self._piece_attacks_square(start, square)
            for start, piece in self.board.items()
        )

    def _piece_attacks_square(
        self,
        start: Square,
        target: Square,
    ) -> bool:
        piece = self.board[start]

        if piece is None:
            return False

        dx = self._file_index(target[0]) - self._file_index(start[0])
        dy = target[1] - start[1]

        if piece.kind == PieceType.PAWN:
            direction = 1 if piece.color == Color.WHITE else -1
            return abs(dx) == 1 and dy == direction

        if piece.kind == PieceType.KNIGHT:
            return (abs(dx), abs(dy)) in {(1, 2), (2, 1)}

        if piece.kind == PieceType.KING:
            return max(abs(dx), abs(dy)) == 1

        if piece.kind == PieceType.BISHOP:
            return abs(dx) == abs(dy) and self._path_is_clear(start, target)

        if piece.kind == PieceType.ROOK:
            return (
                (dx == 0 or dy == 0)
                and self._path_is_clear(start, target)
            )

        if piece.kind == PieceType.QUEEN:
            return (
                (abs(dx) == abs(dy) or dx == 0 or dy == 0)
                and self._path_is_clear(start, target)
            )

        return False

    def _get_legal_moves(self, color: Color):
        moves = []

        for start, piece in self.board.items():
            if piece is None or piece.color != color:
                continue

            for end in self.board:
                if self._is_legal_move(start, end):
                    moves.append((start, end))

        return moves

    def _apply_move(
        self,
        start: Square,
        end: Square,
        promotion: Optional[PieceType] = None,
    ) -> None:
        piece = self.board[start]

        if piece is None:
            raise ValueError("No piece at start square.")

        captured = self.board[end]

        self.board[end] = piece
        self.board[start] = None

        if piece.kind == PieceType.KING:
            self._remove_castling_rights(piece.color)

        if piece.kind == PieceType.ROOK:
            self._remove_rook_castling_rights(piece.color, start)

        if captured and captured.kind == PieceType.ROOK:
            self._remove_rook_castling_rights(captured.color, end)

        if piece.kind == PieceType.PAWN and self._is_promotion_move(start, end):
            if promotion is None:
                raise ValueError("Promotion piece required.")

            if promotion not in {
                PieceType.QUEEN,
                PieceType.ROOK,
                PieceType.BISHOP,
                PieceType.KNIGHT,
            }:
                raise ValueError("Invalid promotion piece.")

            self.board[end] = Piece(piece.color, promotion)

        self.en_passant_target = None

        if piece.kind == PieceType.PAWN and abs(end[1] - start[1]) == 2:
            direction = 1 if piece.color == Color.WHITE else -1
            self.en_passant_target = (
                start[0],
                start[1] + direction,
            )

    def _is_castling(self, start: Square, end: Square) -> bool:
        piece = self.board[start]

        if piece is None or piece.kind != PieceType.KING:
            return False

        if start[1] != end[1]:
            return False

        if abs(self._file_index(end[0]) - self._file_index(start[0])) != 2:
            return False

        color = piece.color
        rank = 1 if color == Color.WHITE else 8

        if start != ("e", rank):
            return False

        king_side = end[0] == "g"
        queen_side = end[0] == "c"

        if king_side and not self.castling_rights[color]["king_side"]:
            return False

        if queen_side and not self.castling_rights[color]["queen_side"]:
            return False

        rook_file = "h" if king_side else "a"
        rook = self.board[(rook_file, rank)]

        if rook is None or rook.kind != PieceType.ROOK:
            return False

        between = ["f", "g"] if king_side else ["b", "c", "d"]

        if any(self.board[(file, rank)] is not None for file in between):
            return False

        enemy = self._opposite_color(color)

        path = ["e", "f", "g"] if king_side else ["e", "d", "c"]

        return not any(
            self._is_square_attacked((file, rank), enemy)
            for file in path
        )

    def _castle(self, start: Square, end: Square) -> None:
        king = self.board[start]

        if king is None:
            raise ValueError("Invalid castling move.")

        rank = 1 if king.color == Color.WHITE else 8
        king_side = end[0] == "g"

        rook_start = ("h", rank) if king_side else ("a", rank)
        rook_end = ("f", rank) if king_side else ("d", rank)

        self.board[end] = self.board[start]
        self.board[start] = None

        self.board[rook_end] = self.board[rook_start]
        self.board[rook_start] = None

        self._remove_castling_rights(king.color)
        self.en_passant_target = None

    def _is_en_passant(self, start: Square, end: Square) -> bool:
        piece = self.board[start]

        if piece is None or piece.kind != PieceType.PAWN:
            return False

        if self.en_passant_target != end:
            return False

        direction = 1 if piece.color == Color.WHITE else -1

        if end[1] - start[1] != direction:
            return False

        if abs(self._file_index(end[0]) - self._file_index(start[0])) != 1:
            return False

        captured_square = (end[0], end[1] - direction)
        captured = self.board[captured_square]

        return (
            captured is not None
            and captured.kind == PieceType.PAWN
            and captured.color != piece.color
        )

    def _en_passant(self, start: Square, end: Square) -> None:
        piece = self.board[start]

        if piece is None:
            raise ValueError("Invalid en passant move.")

        direction = 1 if piece.color == Color.WHITE else -1
        captured_square = (end[0], end[1] - direction)

        self.board[end] = piece
        self.board[start] = None
        self.board[captured_square] = None

        self.en_passant_target = None

    def _path_is_clear(self, start: Square, end: Square) -> bool:
        x1 = self._file_index(start[0])
        y1 = start[1]

        x2 = self._file_index(end[0])
        y2 = end[1]

        dx = (x2 > x1) - (x2 < x1)
        dy = (y2 > y1) - (y2 < y1)

        x = x1 + dx
        y = y1 + dy

        while (x, y) != (x2, y2):
            if self.board[(self.FILES[x], y)] is not None:
                return False

            x += dx
            y += dy

        return True

    def _find_king(self, color: Color) -> Optional[Square]:
        for square, piece in self.board.items():
            if (
                piece is not None
                and piece.color == color
                and piece.kind == PieceType.KING
            ):
                return square

        return None

    def _is_promotion_move(self, start: Square, end: Square) -> bool:
        piece = self.board[start]

        return (
            piece is not None
            and piece.kind == PieceType.PAWN
            and end[1] in (1, 8)
        )

    def _validate_square(self, square: Square) -> None:
        file, rank = square

        if file not in self.FILES or rank not in self.RANKS:
            raise ValueError(f"Invalid square: {square}")

    def _file_index(self, file: str) -> int:
        return self.FILES.index(file)

    @staticmethod
    def _opposite_color(color: Color) -> Color:
        return Color.BLACK if color == Color.WHITE else Color.WHITE

    def _remove_castling_rights(self, color: Color) -> None:
        self.castling_rights[color]["king_side"] = False
        self.castling_rights[color]["queen_side"] = False

    def _remove_rook_castling_rights(
        self,
        color: Color,
        square: Square,
    ) -> None:
        rank = 1 if color == Color.WHITE else 8

        if square == ("h", rank):
            self.castling_rights[color]["king_side"] = False
        elif square == ("a", rank):
            self.castling_rights[color]["queen_side"] = False

    def _save_state(self):
        return (
            self.board.copy(),
            {
                color: rights.copy()
                for color, rights in self.castling_rights.items()
            },
            self.en_passant_target,
        )

    def _restore_state(self, state) -> None:
        (
            self.board,
            self.castling_rights,
            self.en_passant_target,
        ) = state
