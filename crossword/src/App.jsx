import { useState, useEffect, useRef, useCallback } from 'react'
import puzzle from '@/data/puzzle1.json'
import CrosswordGrid from '@/components/CrosswordGrid'
import ClueList from '@/components/ClueList'
import Header from '@/components/Header'
import { startSession, logEvent, downloadLog } from '@/utils/eventLogger'

// ─── helpers ────────────────────────────────────────────────────────────────

function buildInitialGrid(solution) {
  return solution.map((row) => row.map((cell) => (cell === '#' ? null : '')))
}

function cluesAt(puzzle, r, c) {
  const across = puzzle.clues.across.find(
    (cl) => cl.row === r && c >= cl.col && c < cl.col + cl.length
  )
  const down = puzzle.clues.down.find(
    (cl) => cl.col === c && r >= cl.row && r < cl.row + cl.length
  )
  return { across, down }
}

function nextCell(clue, direction, row, col) {
  if (direction === 'across') {
    const nc = col + 1
    if (nc < clue.col + clue.length) return { row, col: nc }
  } else {
    const nr = row + 1
    if (nr < clue.row + clue.length) return { row: nr, col }
  }
  return null
}

function prevCell(clue, direction, row, col) {
  if (direction === 'across') {
    const nc = col - 1
    if (nc >= clue.col) return { row, col: nc }
  } else {
    const nr = row - 1
    if (nr >= clue.row) return { row: nr, col }
  }
  return null
}

function firstEmptyCell(clue, direction, grid) {
  for (let i = 0; i < clue.length; i++) {
    const r = direction === 'across' ? clue.row : clue.row + i
    const c = direction === 'across' ? clue.col + i : clue.col
    if (!grid[r][c]) return { row: r, col: c }
  }
  return { row: clue.row, col: clue.col }
}

function allCluesFlat(puzzle) {
  return [
    ...puzzle.clues.across.map((cl) => ({ ...cl, direction: 'across' })),
    ...puzzle.clues.down.map((cl) => ({ ...cl, direction: 'down' })),
  ]
}

function nextClueAfter(puzzle, clue, direction) {
  const list = allCluesFlat(puzzle)
  const idx = list.findIndex((cl) => cl.number === clue.number && cl.direction === direction)
  return list[(idx + 1) % list.length]
}

function formatTime(seconds) {
  const m = String(Math.floor(seconds / 60)).padStart(2, '0')
  const s = String(seconds % 60).padStart(2, '0')
  return `${m}:${s}`
}

// ─── App ────────────────────────────────────────────────────────────────────

export default function App() {
  const [userGrid, setUserGrid] = useState(() => buildInitialGrid(puzzle.solution))
  const [selectedCell, setSelectedCell] = useState(null)
  const [selectedDirection, setSelectedDirection] = useState('across')
  const [selectedClue, setSelectedClue] = useState(null)
  const [incorrectCells, setIncorrectCells] = useState([])
  const [correctCells, setCorrectCells] = useState([])
  const [timerSeconds, setTimerSeconds] = useState(0)
  const [sessionActive, setSessionActive] = useState(false)
  const [sessionEnded, setSessionEnded] = useState(false)

  const timerRef = useRef(null)
  const incorrectTimerRef = useRef(null)

  useEffect(() => () => {
    clearInterval(timerRef.current)
    clearTimeout(incorrectTimerRef.current)
  }, [])

  function ensureSessionStarted() {
    if (!sessionActive && !sessionEnded) {
      setSessionActive(true)
      startSession(puzzle.id)
      timerRef.current = setInterval(() => setTimerSeconds((s) => s + 1), 1000)
    }
  }

  // ── Select a cell ────────────────────────────────────────────────────────
  function selectCell(r, c, forcedDirection) {
    ensureSessionStarted()
    const { across, down } = cluesAt(puzzle, r, c)

    let dir = forcedDirection
    if (!dir) {
      if (selectedCell?.row === r && selectedCell?.col === c) {
        // Toggle on same-cell click
        if (across && down) {
          dir = selectedDirection === 'across' ? 'down' : 'across'
        } else {
          dir = selectedDirection
        }
      } else {
        if (selectedDirection === 'across' && across) dir = 'across'
        else if (selectedDirection === 'down' && down) dir = 'down'
        else if (across) dir = 'across'
        else if (down) dir = 'down'
        else return
      }
    }

    const clue = dir === 'across' ? across : down
    if (!clue) return

    setSelectedCell({ row: r, col: c })
    setSelectedDirection(dir)
    setSelectedClue(clue)
    logEvent('clue_selected', { clueNumber: clue.number, direction: dir })
  }

  // ── Select a clue from the list ──────────────────────────────────────────
  function selectClue(clue, direction) {
    ensureSessionStarted()
    const target = firstEmptyCell(clue, direction, userGrid)
    setSelectedCell(target)
    setSelectedDirection(direction)
    setSelectedClue(clue)
    logEvent('clue_selected', { clueNumber: clue.number, direction })
  }

  // ── Check if clue is now complete and log it ─────────────────────────────
  function checkClueComplete(grid, clue, direction) {
    let answer = ''
    for (let i = 0; i < clue.length; i++) {
      const r = direction === 'across' ? clue.row : clue.row + i
      const c = direction === 'across' ? clue.col + i : clue.col
      if (!grid[r][c]) return
      answer += grid[r][c]
    }
    logEvent('answer_completed', {
      clueNumber: clue.number,
      direction,
      answer,
      correct: answer === clue.answer,
    })
  }

  // ── Keyboard handler ─────────────────────────────────────────────────────
  const handleKeyDown = useCallback(
    (e) => {
      if (!selectedCell || sessionEnded) return
      const { row, col } = selectedCell

      if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.key)) {
        e.preventDefault()
        let nr = row, nc = col, dir = selectedDirection
        if (e.key === 'ArrowRight') { nc = col + 1; dir = 'across' }
        if (e.key === 'ArrowLeft')  { nc = col - 1; dir = 'across' }
        if (e.key === 'ArrowDown')  { nr = row + 1; dir = 'down' }
        if (e.key === 'ArrowUp')    { nr = row - 1; dir = 'down' }
        if (nr < 0 || nr >= puzzle.size.rows || nc < 0 || nc >= puzzle.size.cols) return
        if (puzzle.solution[nr][nc] === '#') return
        selectCell(nr, nc, dir)
        return
      }

      if (e.key === 'Tab') {
        e.preventDefault()
        if (!selectedClue) return
        const next = nextClueAfter(puzzle, selectedClue, selectedDirection)
        selectClue(next, next.direction)
        return
      }

      if (e.key === 'Backspace') {
        e.preventDefault()
        const newGrid = userGrid.map((r) => [...r])
        if (newGrid[row][col]) {
          newGrid[row][col] = ''
          setUserGrid(newGrid)
          logEvent('cell_cleared', {
            clueNumber: selectedClue?.number,
            direction: selectedDirection,
            row,
            col,
          })
        } else {
          const prev = prevCell(selectedClue, selectedDirection, row, col)
          if (prev) {
            newGrid[prev.row][prev.col] = ''
            setUserGrid(newGrid)
            setSelectedCell(prev)
            logEvent('cell_cleared', {
              clueNumber: selectedClue?.number,
              direction: selectedDirection,
              row: prev.row,
              col: prev.col,
            })
          }
        }
        return
      }

      if (/^[a-zA-Z]$/.test(e.key)) {
        e.preventDefault()
        const letter = e.key.toUpperCase()
        const newGrid = userGrid.map((r) => [...r])
        newGrid[row][col] = letter
        setUserGrid(newGrid)

        logEvent('cell_typed', {
          clueNumber: selectedClue?.number,
          direction: selectedDirection,
          row,
          col,
          letter,
        })

        if (selectedClue) checkClueComplete(newGrid, selectedClue, selectedDirection)

        const next = nextCell(selectedClue, selectedDirection, row, col)
        if (next) setSelectedCell(next)
      }
    },
    [selectedCell, selectedClue, selectedDirection, userGrid, sessionEnded]
  )

  // ── Check Answers ────────────────────────────────────────────────────────
  function handleCheckAnswers() {
    ensureSessionStarted()
    const wrong = []
    const right = []
    const results = []
    allCluesFlat(puzzle).forEach(({ direction, ...clue }) => {
      let correct = true
      for (let i = 0; i < clue.length; i++) {
        const r = direction === 'across' ? clue.row : clue.row + i
        const c = direction === 'across' ? clue.col + i : clue.col
        const entered = userGrid[r][c]
        if (entered && entered !== puzzle.solution[r][c]) {
          wrong.push({ row: r, col: c })
          correct = false
        } else if (entered && entered === puzzle.solution[r][c]) {
          right.push({ row: r, col: c })
        }
      }
      results.push({ clueNumber: clue.number, direction, correct })
    })

    logEvent('check_triggered', { results })
    setIncorrectCells(wrong)
    setCorrectCells(right)
    clearTimeout(incorrectTimerRef.current)
    incorrectTimerRef.current = setTimeout(() => {
      setIncorrectCells([])
      setCorrectCells([])
    }, 3000)
  }

  // ── End Session ──────────────────────────────────────────────────────────
  function handleEndSession() {
    if (sessionEnded) return
    clearInterval(timerRef.current)
    setSessionEnded(true)
    setSessionActive(false)
    const totalCells = puzzle.solution.flat().filter((c) => c !== '#').length
    const cellsFilled = userGrid.flat().filter((c) => c !== null && c !== '').length
    logEvent('session_end', {
      totalTimeMs: timerSeconds * 1000,
      cellsFilled,
      totalCells,
    })
    downloadLog()
  }

  return (
    <div className="h-screen flex flex-col bg-white overflow-hidden">
      <Header
        title={puzzle.title}
        timerDisplay={formatTime(timerSeconds)}
        onCheckAnswers={handleCheckAnswers}
        onDownloadLog={downloadLog}
        onEndSession={handleEndSession}
      />

      <div className="flex flex-1 overflow-hidden">
        {/* Grid panel */}
        <div className="flex items-center justify-center p-8" style={{ flex: '0 0 55%' }}>
          <CrosswordGrid
            puzzle={puzzle}
            userGrid={userGrid}
            selectedCell={selectedCell}
            selectedDirection={selectedDirection}
            selectedClue={selectedClue}
            incorrectCells={incorrectCells}
            correctCells={correctCells}
            onCellClick={selectCell}
            onKeyDown={handleKeyDown}
          />
        </div>

        <div className="w-px bg-neutral-200" />

        {/* Clue list panel */}
        <div className="flex-1 overflow-hidden">
          <ClueList
            clues={puzzle.clues}
            selectedClue={selectedClue}
            selectedDirection={selectedDirection}
            userGrid={userGrid}
            onClueClick={selectClue}
          />
        </div>
      </div>

      {sessionEnded && (
        <div className="fixed inset-0 bg-white/80 flex items-center justify-center z-50">
          <div className="text-center space-y-2">
            <p className="text-lg font-medium text-neutral-800">Session complete</p>
            <p className="text-sm text-neutral-500">Log downloaded. Thank you.</p>
          </div>
        </div>
      )}
    </div>
  )
}
