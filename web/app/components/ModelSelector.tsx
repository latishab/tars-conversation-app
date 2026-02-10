'use client'

import { useState, useEffect } from 'react'
import { Button } from './ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './ui/card'

interface Model {
  id: string
  name: string
  ttft: string
  description: string
}

const MODELS: Model[] = [
  {
    id: 'openai/gpt-oss-20b',
    name: 'GPT-OSS-20B',
    ttft: '800ms-1s',
    description: 'Fast, good quality (20B params) - Default'
  },
  {
    id: 'meta-llama/Llama-3.3-70B-Instruct-Turbo',
    name: 'Llama-3.3-70B Turbo',
    ttft: '1-2s',
    description: 'Balanced performance (70B params)'
  },
  {
    id: 'nvidia/Nemotron-3-Nano-30B-A3B',
    name: 'Nemotron-3-30B',
    ttft: '1-1.5s',
    description: 'Efficient NVIDIA model (30B params)'
  },
  {
    id: 'meta-llama/Llama-4-Scout-17B-16E-Instruct',
    name: 'Llama-4-Scout-17B',
    ttft: '600-900ms',
    description: 'Very fast, smaller model (17B params)'
  },
  {
    id: 'meta-llama/Llama-3.2-3B-Instruct',
    name: 'Llama-3.2-3B',
    ttft: '300-500ms',
    description: 'Fastest, smallest (3B params)'
  },
]

interface ModelSelectorProps {
  onModelChange?: (modelId: string) => void
}

export function ModelSelector({ onModelChange }: ModelSelectorProps) {
  const [selectedModel, setSelectedModel] = useState<string>(MODELS[0].id)
  const [currentBackendModel, setCurrentBackendModel] = useState<string | null>(null)
  const [isOpen, setIsOpen] = useState(false)

  // Fetch current model from backend
  useEffect(() => {
    fetch('http://localhost:7860/api/status')
      .then(res => res.json())
      .then(data => {
        if (data.llm_model) {
          setCurrentBackendModel(data.llm_model)
          setSelectedModel(data.llm_model)
        }
      })
      .catch(err => console.error('Failed to fetch current model:', err))
  }, [])

  // Load saved model preference
  useEffect(() => {
    const saved = localStorage.getItem('selected-llm-model')
    if (saved && !currentBackendModel) {
      setSelectedModel(saved)
    }
  }, [currentBackendModel])

  const handleModelChange = async (modelId: string) => {
    setSelectedModel(modelId)
    localStorage.setItem('selected-llm-model', modelId)

    // Save to backend config.ini
    try {
      const response = await fetch('http://localhost:7860/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ llm_model: modelId })
      })

      const data = await response.json()

      if (data.success) {
        alert('✓ Model saved to config.ini. Please restart the Pipecat service for changes to take effect.')
      } else {
        alert('Failed to save model configuration.')
      }
    } catch (err) {
      console.error('Failed to update config:', err)
      alert('Failed to save model configuration. Make sure the Pipecat service is running.')
    }

    if (onModelChange) {
      onModelChange(modelId)
    }
  }

  const currentModel = MODELS.find(m => m.id === selectedModel) || MODELS[0]

  return (
    <div className="relative">
      <Button
        variant="outline"
        onClick={() => setIsOpen(!isOpen)}
        className="gap-2"
      >
        <span className="text-sm">🤖 {currentModel.name}</span>
        <span className="text-xs text-gray-500">({currentModel.ttft})</span>
      </Button>

      {isOpen && (
        <div className="absolute right-0 top-full mt-2 z-50">
          <Card className="w-96 shadow-lg">
            <CardHeader className="pb-3">
              <CardTitle className="text-lg">Select LLM Model</CardTitle>
              <CardDescription>
                Choose model based on speed vs capability
              </CardDescription>
              {currentBackendModel && (
                <div className="mt-2 px-2 py-1 bg-green-50 border border-green-200 rounded text-xs">
                  <span className="font-semibold text-green-700">Active: </span>
                  <span className="font-mono text-green-600">
                    {MODELS.find(m => m.id === currentBackendModel)?.name || 'Custom'}
                  </span>
                </div>
              )}
            </CardHeader>
            <CardContent className="space-y-2">
              {MODELS.map((model) => {
                const isActive = currentBackendModel === model.id
                const isSelected = selectedModel === model.id
                return (
                <button
                  key={model.id}
                  onClick={() => {
                    handleModelChange(model.id)
                    setIsOpen(false)
                  }}
                  className={`w-full text-left p-3 rounded-lg border transition-colors ${
                    isActive
                      ? 'border-green-500 bg-green-50'
                      : isSelected
                      ? 'border-blue-500 bg-blue-50'
                      : 'border-gray-200 hover:bg-gray-50'
                  }`}
                >
                  <div className="flex items-start justify-between">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-medium">{model.name}</span>
                        {isActive && (
                          <span className="text-xs bg-green-500 text-white px-1.5 py-0.5 rounded">
                            ACTIVE
                          </span>
                        )}
                      </div>
                      <div className="text-xs text-gray-600 mt-1">{model.description}</div>
                    </div>
                    <div className="text-xs font-mono text-blue-600 whitespace-nowrap ml-2">
                      {model.ttft}
                    </div>
                  </div>
                </button>
                )
              })}

              <div className="pt-3 border-t text-xs text-gray-500 space-y-2">
                <p className="font-semibold">How it works:</p>
                <ol className="list-decimal list-inside space-y-1 text-xs">
                  <li>Select a model above</li>
                  <li>Configuration is saved to <code className="bg-gray-100 px-1 rounded">config.ini</code></li>
                  <li>Restart the Pipecat service to apply changes</li>
                </ol>
                <div className="mt-2 p-2 bg-blue-50 border border-blue-200 rounded">
                  <p className="text-xs">
                    <span className="font-semibold">Selected:</span>
                    <span className="font-mono ml-1 text-blue-600 break-all block mt-1">
                      {selectedModel}
                    </span>
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Backdrop */}
      {isOpen && (
        <div
          className="fixed inset-0 z-40"
          onClick={() => setIsOpen(false)}
        />
      )}
    </div>
  )
}
