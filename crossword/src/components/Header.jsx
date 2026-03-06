import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'

export default function Header({ title, timerDisplay, onCheckAnswers, onDownloadLog, onEndSession, onSelectPuzzle }) {
  return (
    <div className="flex items-center justify-between px-6 py-3 border-b border-neutral-200 bg-white">
      <span className="text-sm text-neutral-500 font-medium">{title}</span>

      <Badge variant="outline" className="tabular-nums text-sm px-3 py-1">
        {timerDisplay}
      </Badge>

      <div className="flex gap-2">
        <Button variant="outline" size="sm" onClick={onSelectPuzzle}>
          Select Puzzle
        </Button>
        <Button variant="outline" size="sm" onClick={onCheckAnswers}>
          Check Answers
        </Button>
        <Button variant="outline" size="sm" onClick={onDownloadLog}>
          Download Log
        </Button>
        <Button variant="destructive" size="sm" onClick={onEndSession}>
          End Session
        </Button>
      </div>
    </div>
  )
}
