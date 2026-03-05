import { Button } from '@/components/ui/button'

const PUZZLES = [
  { id: 'puzzle1', label: 'General Knowledge', subtitle: '9×9' },
  { id: 'puzzle2', label: 'Pixar Movies', subtitle: '9×9' },
  { id: 'puzzle3', label: 'General Knowledge II', subtitle: '9×9' },
]

export default function PuzzlePicker({ currentId, onSelect, onClose }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="relative bg-white rounded-xl shadow-xl border border-neutral-200 w-72 p-5">
        <p className="text-sm font-semibold text-neutral-800 mb-4">Select a Puzzle</p>
        <div className="flex flex-col gap-2">
          {PUZZLES.map((p) => (
            <button
              key={p.id}
              onClick={() => { onSelect(p.id); onClose() }}
              className={[
                'flex items-center justify-between px-4 py-3 rounded-lg border text-left transition-colors',
                p.id === currentId
                  ? 'border-neutral-800 bg-neutral-50'
                  : 'border-neutral-200 hover:border-neutral-400 hover:bg-neutral-50',
              ].join(' ')}
            >
              <span>
                <span className="block text-sm font-medium text-neutral-800">{p.label}</span>
                <span className="block text-xs text-neutral-400 mt-0.5">{p.subtitle}</span>
              </span>
              {p.id === currentId && (
                <span className="text-xs font-medium text-neutral-500">current</span>
              )}
            </button>
          ))}
        </div>
        <Button variant="ghost" size="sm" className="mt-4 w-full" onClick={onClose}>
          Cancel
        </Button>
      </div>
    </div>
  )
}
