"use client";

import React, { useState, useEffect } from "react";
import { Card } from "./ui/card";

interface CrosswordClue {
  number: number;
  clue: string;
  answer: string;
  direction: "across" | "down";
  startRow: number;
  startCol: number;
}

interface CrosswordPuzzle {
  id: string;
  title: string;
  size: number;
  clues: CrosswordClue[];
}

// Sample crossword puzzle (medium difficulty)
const PUZZLE: CrosswordPuzzle = {
  id: "daily-1",
  title: "Daily Challenge",
  size: 7,
  clues: [
    { number: 1, clue: "Opposite of hot", answer: "COLD", direction: "across", startRow: 0, startCol: 0 },
    { number: 2, clue: "Large body of water", answer: "OCEAN", direction: "across", startRow: 2, startCol: 1 },
    { number: 3, clue: "Flying mammal", answer: "BAT", direction: "down", startRow: 0, startCol: 0 },
    { number: 4, clue: "Yellow citrus fruit", answer: "LEMON", direction: "across", startRow: 4, startCol: 0 },
    { number: 5, clue: "Feline pet", answer: "CAT", direction: "down", startRow: 2, startCol: 1 },
    { number: 6, clue: "Frozen water", answer: "ICE", direction: "down", startRow: 0, startCol: 3 },
    { number: 7, clue: "King of the jungle", answer: "LION", direction: "across", startRow: 1, startCol: 3 },
  ],
};

interface CellData {
  letter: string;
  number?: number;
  isBlack: boolean;
}

export function Crossword({ onProgressUpdate }: { onProgressUpdate?: (progress: any) => void }) {
  const [grid, setGrid] = useState<CellData[][]>([]);
  const [selectedCell, setSelectedCell] = useState<{ row: number; col: number } | null>(null);
  const [selectedDirection, setSelectedDirection] = useState<"across" | "down">("across");
  const [mistakes, setMistakes] = useState(0);
  const [completed, setCompleted] = useState(false);

  // Initialize grid
  useEffect(() => {
    const newGrid: CellData[][] = Array(PUZZLE.size)
      .fill(null)
      .map(() =>
        Array(PUZZLE.size)
          .fill(null)
          .map(() => ({ letter: "", isBlack: true }))
      );

    // Mark cells that should be white based on clues
    PUZZLE.clues.forEach((clue) => {
      const { answer, startRow, startCol, direction } = clue;
      for (let i = 0; i < answer.length; i++) {
        const row = direction === "across" ? startRow : startRow + i;
        const col = direction === "across" ? startCol + i : startCol;
        if (row < PUZZLE.size && col < PUZZLE.size) {
          newGrid[row][col].isBlack = false;
          // Set clue number on first cell
          if (i === 0) {
            newGrid[row][col].number = clue.number;
          }
        }
      }
    });

    setGrid(newGrid);
  }, []);

  // Check completion
  useEffect(() => {
    if (grid.length === 0) return;

    let allCorrect = true;
    PUZZLE.clues.forEach((clue) => {
      const { answer, startRow, startCol, direction } = clue;
      for (let i = 0; i < answer.length; i++) {
        const row = direction === "across" ? startRow : startRow + i;
        const col = direction === "across" ? startCol + i : startCol;
        if (grid[row][col].letter !== answer[i]) {
          allCorrect = false;
        }
      }
    });

    if (allCorrect && !completed) {
      setCompleted(true);
    }

    // Update progress to TARS
    if (onProgressUpdate) {
      const totalCells = PUZZLE.clues.reduce((sum, c) => sum + c.answer.length, 0);
      const filledCells = grid.flat().filter((c) => !c.isBlack && c.letter).length;
      onProgressUpdate({
        totalCells,
        filledCells,
        progress: (filledCells / totalCells) * 100,
        mistakes,
        completed: allCorrect,
      });
    }
  }, [grid, mistakes, completed, onProgressUpdate]);

  const handleCellClick = (row: number, col: number) => {
    if (grid[row][col].isBlack) return;

    if (selectedCell?.row === row && selectedCell?.col === col) {
      // Toggle direction on same cell click
      setSelectedDirection((prev) => (prev === "across" ? "down" : "across"));
    } else {
      setSelectedCell({ row, col });
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!selectedCell) return;

    const { row, col } = selectedCell;

    if (e.key === "Backspace") {
      const newGrid = [...grid];
      newGrid[row][col] = { ...newGrid[row][col], letter: "" };
      setGrid(newGrid);
      // Move to previous cell
      moveToPrevCell();
    } else if (e.key === "ArrowLeft") {
      moveCell(0, -1);
    } else if (e.key === "ArrowRight") {
      moveCell(0, 1);
    } else if (e.key === "ArrowUp") {
      moveCell(-1, 0);
    } else if (e.key === "ArrowDown") {
      moveCell(1, 0);
    } else if (/^[a-zA-Z]$/.test(e.key)) {
      const newGrid = [...grid];
      const letter = e.key.toUpperCase();
      newGrid[row][col] = { ...newGrid[row][col], letter };
      setGrid(newGrid);

      // Check if it's correct
      const isCorrect = checkCell(row, col, letter);
      if (!isCorrect) {
        setMistakes((prev) => prev + 1);
      }

      // Move to next cell
      moveToNextCell();
    }
  };

  const checkCell = (row: number, col: number, letter: string): boolean => {
    for (const clue of PUZZLE.clues) {
      const { answer, startRow, startCol, direction } = clue;
      for (let i = 0; i < answer.length; i++) {
        const r = direction === "across" ? startRow : startRow + i;
        const c = direction === "across" ? startCol + i : startCol;
        if (r === row && c === col) {
          return answer[i] === letter;
        }
      }
    }
    return false;
  };

  const moveCell = (rowDelta: number, colDelta: number) => {
    if (!selectedCell) return;
    const newRow = selectedCell.row + rowDelta;
    const newCol = selectedCell.col + colDelta;
    if (
      newRow >= 0 &&
      newRow < PUZZLE.size &&
      newCol >= 0 &&
      newCol < PUZZLE.size &&
      !grid[newRow][newCol].isBlack
    ) {
      setSelectedCell({ row: newRow, col: newCol });
    }
  };

  const moveToNextCell = () => {
    if (selectedDirection === "across") {
      moveCell(0, 1);
    } else {
      moveCell(1, 0);
    }
  };

  const moveToPrevCell = () => {
    if (selectedDirection === "across") {
      moveCell(0, -1);
    } else {
      moveCell(-1, 0);
    }
  };

  const acrossClues = PUZZLE.clues.filter((c) => c.direction === "across");
  const downClues = PUZZLE.clues.filter((c) => c.direction === "down");

  return (
    <div className="w-full max-w-4xl mx-auto">
      <Card className="p-4 mb-4">
        <h2 className="text-xl font-bold mb-2">{PUZZLE.title}</h2>
        <div className="flex gap-4 text-sm text-muted-foreground">
          <div>Progress: {Math.round((grid.flat().filter((c) => !c.isBlack && c.letter).length / PUZZLE.clues.reduce((sum, c) => sum + c.answer.length, 0)) * 100)}%</div>
          <div>Mistakes: {mistakes}</div>
          {completed && <div className="text-green-600 font-bold">✓ Completed!</div>}
        </div>
      </Card>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Grid */}
        <Card className="p-4">
          <div
            className="inline-block"
            tabIndex={0}
            onKeyDown={handleKeyDown}
            style={{ outline: "none" }}
          >
            {grid.map((row, rowIndex) => (
              <div key={rowIndex} className="flex">
                {row.map((cell, colIndex) => (
                  <div
                    key={colIndex}
                    onClick={() => handleCellClick(rowIndex, colIndex)}
                    className={`
                      w-10 h-10 border border-gray-400 flex items-center justify-center text-lg font-bold cursor-pointer relative
                      ${cell.isBlack ? "bg-black" : "bg-white"}
                      ${
                        selectedCell?.row === rowIndex && selectedCell?.col === colIndex
                          ? "ring-2 ring-blue-500"
                          : ""
                      }
                    `}
                  >
                    {!cell.isBlack && (
                      <>
                        {cell.number && (
                          <span className="absolute top-0 left-0.5 text-[8px] text-gray-500">
                            {cell.number}
                          </span>
                        )}
                        <span className="text-black">{cell.letter}</span>
                      </>
                    )}
                  </div>
                ))}
              </div>
            ))}
          </div>
        </Card>

        {/* Clues */}
        <Card className="p-4 overflow-y-auto max-h-[400px]">
          <div className="mb-4">
            <h3 className="font-bold text-sm mb-2">ACROSS</h3>
            {acrossClues.map((clue) => (
              <div key={clue.number} className="text-sm mb-1">
                <span className="font-semibold">{clue.number}.</span> {clue.clue}
              </div>
            ))}
          </div>
          <div>
            <h3 className="font-bold text-sm mb-2">DOWN</h3>
            {downClues.map((clue) => (
              <div key={clue.number} className="text-sm mb-1">
                <span className="font-semibold">{clue.number}.</span> {clue.clue}
              </div>
            ))}
          </div>
        </Card>
      </div>

      <Card className="p-4 mt-4 bg-muted/50">
        <p className="text-sm text-muted-foreground">
          💡 Tip: TARS knows all the answers. If you get stuck or confused, he might notice and offer help!
        </p>
      </Card>
    </div>
  );
}
