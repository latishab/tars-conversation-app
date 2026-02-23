import { useEffect, useRef, useCallback } from 'react'
import { cn } from '@/lib/utils'

// Build a map of (row,col) -> { acrossClue, downClue, cellNumber }
function buildCellMeta(puzzle) {
  const meta = {}
  const init = (r, c) => {
    const key = `${r},${c}`
    if (!meta[key]) meta[key] = { acrossClue: null, downClue: null, cellNumber: null }
    return meta[key]
  }

  puzzle.clues.across.forEach((clue) => {
    for (let i = 0; i < clue.length; i++) {
      const m = init(clue.row, clue.col + i)
      m.acrossClue = clue
      if (i === 0) m.cellNumber = clue.number
    }
  })
  puzzle.clues.down.forEach((clue) => {
    for (let i = 0; i < clue.length; i++) {
      const m = init(clue.row + i, clue.col)
      m.downClue = clue
      if (i === 0 && !m.cellNumber) m.cellNumber = clue.number
    }
  })
  return meta
}

export default function CrosswordGrid({
  puzzle,
  userGrid,
  selectedCell,
  selectedDirection,
  selectedClue,
  incorrectCells,
  onCellClick,
  onKeyDown,
}) {
  const cellMeta = buildCellMeta(puzzle)
  const gridRef = useRef(null)
  const inputRef = useRef(null)

  // Keep a hidden input focused so keyboard events work everywhere
  useEffect(() => {
    if (selectedCell && inputRef.current) {
      inputRef.current.focus()
    }
  }, [selectedCell])

  function isInActiveClue(r, c) {
    if (!selectedClue) return false
    if (selectedDirection === 'across') {
      return r === selectedClue.row &&
        c >= selectedClue.col &&
        c < selectedClue.col + selectedClue.length
    }
    return c === selectedClue.col &&
      r >= selectedClue.row &&
      r < selectedClue.row + selectedClue.length
  }

  function isSelected(r, c) {
    return selectedCell?.row === r && selectedCell?.col === c
  }

  function isIncorrect(r, c) {
    return incorrectCells.some((cell) => cell.row === r && cell.col === c)
  }

  return (
    <div className="flex flex-col items-center justify-center">
      {/* Hidden input captures keyboard on mobile / ensures focus */}
      <input
        ref={inputRef}
        className="sr-only"
        onKeyDown={onKeyDown}
        readOnly
        aria-hidden="true"
      />

      <div
        ref={gridRef}
        className="inline-grid border border-neutral-400"
        style={{
          gridTemplateColumns: `repeat(${puzzle.size.cols}, 52px)`,
          gridTemplateRows: `repeat(${puzzle.size.rows}, 52px)`,
        }}
        onClick={() => inputRef.current?.focus()}
      >
        {puzzle.solution.map((row, r) =>
          row.map((letter, c) => {
            const isBlack = letter === '#'
            const key = `${r},${c}`
            const meta = cellMeta[key] || {}
            const letter_entered = userGrid[r]?.[c] ?? ''

            if (isBlack) {
              return (
                <div
                  key={key}
                  className="bg-neutral-900 border border-neutral-700"
                />
              )
            }

            return (
              <div
                key={key}
                onClick={() => onCellClick(r, c)}
                className={cn(
                  'relative border border-neutral-300 cursor-pointer select-none',
                  'flex items-center justify-center',
                  isInActiveClue(r, c) && !isSelected(r, c) && 'bg-blue-50',
                  isSelected(r, c) && 'ring-2 ring-inset ring-blue-500 bg-white z-10',
                  !isInActiveClue(r, c) && !isSelected(r, c) && 'bg-white',
                  isIncorrect(r, c) && 'bg-red-100'
                )}
              >
                {meta.cellNumber && (
                  <span className="absolute top-0.5 left-0.5 text-[10px] leading-none text-neutral-400 font-normal">
                    {meta.cellNumber}
                  </span>
                )}
                <span className="text-[18px] font-medium text-neutral-900 leading-none">
                  {letter_entered}
                </span>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
