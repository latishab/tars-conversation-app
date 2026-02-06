'use client'

import { useState, useEffect } from 'react'
import { Button } from './ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './ui/card'

interface TTSProvider {
  id: string
  name: string
  description: string
  type: string
}

const TTS_PROVIDERS: TTSProvider[] = [
  {
    id: 'qwen3',
    name: 'Qwen3-TTS',
    description: 'Local voice cloning (offline, fast, free)',
    type: 'Local'
  },
  {
    id: 'elevenlabs',
    name: 'ElevenLabs',
    description: 'Cloud TTS (online, high quality, requires API key)',
    type: 'Cloud'
  },
]

interface TTSSelectorProps {
  onProviderChange?: (providerId: string) => void
}

export function TTSSelector({ onProviderChange }: TTSSelectorProps) {
  const [selectedProvider, setSelectedProvider] = useState<string>('qwen3')
  const [currentBackendProvider, setCurrentBackendProvider] = useState<string | null>(null)
  const [isOpen, setIsOpen] = useState(false)

  // Fetch current TTS provider from backend
  useEffect(() => {
    fetch('http://localhost:7860/api/status')
      .then(res => res.json())
      .then(data => {
        if (data.tts_provider) {
          setCurrentBackendProvider(data.tts_provider)
          setSelectedProvider(data.tts_provider)
        }
      })
      .catch(err => console.error('Failed to fetch current TTS provider:', err))
  }, [])

  // Load saved provider preference
  useEffect(() => {
    const saved = localStorage.getItem('selected-tts-provider')
    if (saved && !currentBackendProvider) {
      setSelectedProvider(saved)
    }
  }, [currentBackendProvider])

  const handleProviderChange = async (providerId: string) => {
    setSelectedProvider(providerId)
    localStorage.setItem('selected-tts-provider', providerId)

    // Save to backend config.ini
    try {
      const response = await fetch('http://localhost:7860/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tts_provider: providerId })
      })

      const data = await response.json()

      if (data.success) {
        alert('✓ TTS provider saved to config.ini. Please restart the Pipecat service for changes to take effect.')
      } else {
        alert('Failed to save TTS configuration.')
      }
    } catch (err) {
      console.error('Failed to update config:', err)
      alert('Failed to save TTS configuration. Make sure the Pipecat service is running.')
    }

    if (onProviderChange) {
      onProviderChange(providerId)
    }
  }

  const currentProvider = TTS_PROVIDERS.find(p => p.id === selectedProvider) || TTS_PROVIDERS[0]

  return (
    <div className="relative">
      <Button
        variant="outline"
        onClick={() => setIsOpen(!isOpen)}
        className="gap-2"
      >
        <span className="text-sm">🎤 {currentProvider.name}</span>
        <span className="text-xs text-gray-500">({currentProvider.type})</span>
      </Button>

      {isOpen && (
        <div className="absolute right-0 top-full mt-2 z-50">
          <Card className="w-96 shadow-lg">
            <CardHeader className="pb-3">
              <CardTitle className="text-lg">Select TTS Provider</CardTitle>
              <CardDescription>
                Choose between local or cloud TTS
              </CardDescription>
              {currentBackendProvider && (
                <div className="mt-2 px-2 py-1 bg-green-50 border border-green-200 rounded text-xs">
                  <span className="font-semibold text-green-700">Active: </span>
                  <span className="font-mono text-green-600">
                    {TTS_PROVIDERS.find(p => p.id === currentBackendProvider)?.name || 'Unknown'}
                  </span>
                </div>
              )}
            </CardHeader>
            <CardContent className="space-y-2">
              {TTS_PROVIDERS.map((provider) => {
                const isActive = currentBackendProvider === provider.id
                const isSelected = selectedProvider === provider.id
                return (
                  <button
                    key={provider.id}
                    onClick={() => {
                      handleProviderChange(provider.id)
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
                          <span className="font-medium">{provider.name}</span>
                          {isActive && (
                            <span className="text-xs bg-green-500 text-white px-1.5 py-0.5 rounded">
                              ACTIVE
                            </span>
                          )}
                        </div>
                        <div className="text-xs text-gray-600 mt-1">{provider.description}</div>
                      </div>
                      <div className="text-xs font-mono text-blue-600 whitespace-nowrap ml-2">
                        {provider.type}
                      </div>
                    </div>
                  </button>
                )
              })}

              <div className="pt-3 border-t text-xs text-gray-500 space-y-2">
                <p className="font-semibold">How it works:</p>
                <ol className="list-decimal list-inside space-y-1 text-xs">
                  <li>Select a TTS provider above</li>
                  <li>Configuration is saved to <code className="bg-gray-100 px-1 rounded">config.ini</code></li>
                  <li>Restart the Pipecat service to apply changes</li>
                </ol>
                {selectedProvider === 'elevenlabs' && (
                  <div className="mt-2 p-2 bg-amber-50 border border-amber-200 rounded">
                    <p className="text-xs font-semibold text-amber-800">⚠️ Note:</p>
                    <p className="text-xs text-amber-700 mt-1">
                      ElevenLabs requires <code className="bg-amber-100 px-1 rounded">ELEVENLABS_API_KEY</code> in your <code className="bg-amber-100 px-1 rounded">.env.local</code> file
                    </p>
                  </div>
                )}
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
