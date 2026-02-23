import { ScrollArea } from '@/components/ui/scroll-area'
import { cn } from '@/lib/utils'

function ClueItem({ clue, isActive, isComplete, onClick }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'w-full text-left px-3 py-1.5 rounded text-sm transition-colors',
        isActive && 'bg-blue-50',
        isComplete && !isActive && 'text-neutral-400',
        !isActive && !isComplete && 'hover:bg-neutral-50 text-neutral-800'
      )}
    >
      <span className="font-semibold">{clue.number}.</span>{' '}
      {clue.clue}{' '}
      <span className={cn('text-neutral-400', isActive && 'text-blue-400')}>
        ({clue.length})
      </span>
    </button>
  )
}

export default function ClueList({ clues, selectedClue, selectedDirection, userGrid, onClueClick }) {
  function isClueComplete(clue, direction) {
    for (let i = 0; i < clue.length; i++) {
      const r = direction === 'across' ? clue.row : clue.row + i
      const c = direction === 'across' ? clue.col + i : clue.col
      if (!userGrid[r]?.[c]) return false
    }
    return true
  }

  return (
    <ScrollArea className="h-full">
      <div className="px-2 py-4 space-y-4">
        <section>
          <h3 className="px-3 pb-1 text-xs font-semibold uppercase tracking-widest text-neutral-400">
            Across
          </h3>
          {clues.across.map((clue) => (
            <ClueItem
              key={`across-${clue.number}`}
              clue={clue}
              isActive={selectedDirection === 'across' && selectedClue?.number === clue.number}
              isComplete={isClueComplete(clue, 'across')}
              onClick={() => onClueClick(clue, 'across')}
            />
          ))}
        </section>

        <section>
          <h3 className="px-3 pb-1 text-xs font-semibold uppercase tracking-widest text-neutral-400">
            Down
          </h3>
          {clues.down.map((clue) => (
            <ClueItem
              key={`down-${clue.number}`}
              clue={clue}
              isActive={selectedDirection === 'down' && selectedClue?.number === clue.number}
              isComplete={isClueComplete(clue, 'down')}
              onClick={() => onClueClick(clue, 'down')}
            />
          ))}
        </section>
      </div>
    </ScrollArea>
  )
}
