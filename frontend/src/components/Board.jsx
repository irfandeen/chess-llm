import { useMemo, useState } from 'react'

const GLYPHS = { K: '♚', Q: '♛', R: '♜', B: '♝', N: '♞', P: '♟' }
const FILES = 'abcdefgh'

/** grid[0] is rank 8 and grid[r][0] is file a, regardless of orientation. */
function squareName(row, col) {
  return FILES[col] + (8 - row)
}

export default function Board({
  game,
  disabled,
  onMove,
  lastMove,
  humanColor = 'white',
}) {
  const [selected, setSelected] = useState(null) // e.g. "e2"
  const [promo, setPromo] = useState(null) // { uciBase } while choosing

  const flipped = humanColor === 'black'
  const promoRank = humanColor === 'white' ? '8' : '1'

  const legalTargets = useMemo(() => {
    if (!selected || !game) return new Set()
    return new Set(
      game.legal_moves
        .filter((m) => m.startsWith(selected))
        .map((m) => m.slice(2, 4)),
    )
  }, [selected, game])

  const kingInDanger = useMemo(() => {
    if (!game || (game.status !== 'check' && game.status !== 'checkmate')) {
      return null
    }
    for (let r = 0; r < 8; r++) {
      for (let c = 0; c < 8; c++) {
        const p = game.grid[r][c]
        if (p && p.kind === 'K' && p.color === game.turn) {
          return squareName(r, c)
        }
      }
    }
    return null
  }, [game])

  if (!game) {
    return <div className="board board-loading" aria-label="Loading board" />
  }

  const canPlay = !disabled && game.turn === humanColor && !game.game_over

  const handleClick = (row, col) => {
    if (!canPlay) return
    const sq = squareName(row, col)
    const piece = game.grid[row][col]

    if (selected && legalTargets.has(sq)) {
      const fromPiece = pieceAt(game, selected)
      if (fromPiece?.kind === 'P' && sq[1] === promoRank) {
        setPromo({ uciBase: selected + sq })
      } else {
        onMove(selected + sq)
      }
      setSelected(null)
      return
    }
    if (piece && piece.color === humanColor) {
      setSelected(sq === selected ? null : sq)
    } else {
      setSelected(null)
    }
  }

  const choosePromotion = (letter) => {
    onMove(promo.uciBase + letter)
    setPromo(null)
  }

  // Display order: White at the bottom normally, Black at the bottom flipped.
  const rowOrder = flipped ? [7, 6, 5, 4, 3, 2, 1, 0] : [0, 1, 2, 3, 4, 5, 6, 7]
  const colOrder = flipped ? [7, 6, 5, 4, 3, 2, 1, 0] : [0, 1, 2, 3, 4, 5, 6, 7]

  return (
    <div className="board-wrap">
      <div className={'board' + (canPlay ? '' : ' board-locked')}>
        {rowOrder.map((row, displayRow) =>
          colOrder.map((col, displayCol) => {
            const sq = squareName(row, col)
            const piece = game.grid[row][col]
            const dark = (row + col) % 2 === 1
            const classes = [
              'square',
              dark ? 'sq-dark' : 'sq-light',
              selected === sq ? 'sq-selected' : '',
              legalTargets.has(sq) ? (piece ? 'sq-capture' : 'sq-target') : '',
              lastMove && (lastMove.from === sq || lastMove.to === sq)
                ? 'sq-last'
                : '',
              kingInDanger === sq ? 'sq-check' : '',
            ]
              .filter(Boolean)
              .join(' ')
            return (
              <button
                key={sq}
                className={classes}
                onClick={() => handleClick(row, col)}
                aria-label={sq + (piece ? ` ${piece.color} ${piece.kind}` : '')}
              >
                {displayCol === 0 && (
                  <span className="coord coord-rank">{8 - row}</span>
                )}
                {displayRow === 7 && (
                  <span className="coord coord-file">{FILES[col]}</span>
                )}
                {piece && (
                  <span className={`piece piece-${piece.color}`}>
                    {GLYPHS[piece.kind]}
                  </span>
                )}
              </button>
            )
          }),
        )}
      </div>

      {promo && (
        <div className="promo-overlay" onClick={() => setPromo(null)}>
          <div className="promo-box" onClick={(e) => e.stopPropagation()}>
            <p>Promote to</p>
            <div className="promo-choices">
              {['q', 'r', 'b', 'n'].map((l) => (
                <button key={l} onClick={() => choosePromotion(l)}>
                  {GLYPHS[l.toUpperCase()]}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function pieceAt(game, sq) {
  const col = FILES.indexOf(sq[0])
  const row = 8 - Number(sq[1])
  return game.grid[row][col]
}
