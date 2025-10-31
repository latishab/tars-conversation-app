import { WebSocketServer, WebSocket } from 'ws'
import {
  Pipeline,
  PipelineEvents,
  PipelineEventFromServer,
} from '@pipecat-ai/framework'
import { SpeechmaticsRealtimeTranscriptionService } from './services/speechmatics'
import { ElevenLabsTTSService } from './services/elevenlabs'

interface ClientConnection {
  ws: WebSocket
  pipeline: Pipeline | null
  transcriptionService: SpeechmaticsRealtimeTranscriptionService | null
  ttsService: ElevenLabsTTSService | null
}

const clients = new Map<string, ClientConnection>()

export function createVoiceServer(server: any) {
  const wss = new WebSocketServer({ server, path: '/api/voice' })

  wss.on('connection', (ws: WebSocket) => {
    const clientId = Math.random().toString(36).substring(7)
    console.log(`Client connected: ${clientId}`)

    const connection: ClientConnection = {
      ws,
      pipeline: null,
      transcriptionService: null,
      ttsService: null,
    }

    clients.set(clientId, connection)

    // Initialize services
    try {
      connection.transcriptionService = new SpeechmaticsRealtimeTranscriptionService(
        process.env.SPEECHMATICS_API_KEY || ''
      )
      
      connection.ttsService = new ElevenLabsTTSService(
        process.env.ELEVENLABS_API_KEY || '',
        process.env.ELEVENLABS_VOICE_ID || '21m00Tcm4TlvDq8ikWAM' // Default voice
      )

      // Setup transcription callbacks
      connection.transcriptionService.onTranscription = (text: string) => {
        ws.send(JSON.stringify({ type: 'transcription', text }))
      }

      // Setup pipeline
      connection.pipeline = new Pipeline({
        services: [
          connection.transcriptionService,
          connection.ttsService,
        ],
      })

      // Handle pipeline events
      connection.pipeline.on(PipelineEvents.PipelineReady, () => {
        console.log(`Pipeline ready for client ${clientId}`)
      })

      // Handle audio from client
      ws.on('message', async (data: Buffer) => {
        if (connection.transcriptionService) {
          await connection.transcriptionService.processAudio(data)
        }
      })

      // Handle text input for TTS
      ws.on('message', async (message: string) => {
        try {
          const data = JSON.parse(message.toString())
          if (data.type === 'tts' && data.text && connection.ttsService) {
            const audioData = await connection.ttsService.synthesize(data.text)
            ws.send(audioData, { binary: true })
          }
        } catch (e) {
          // Not JSON, treat as audio
        }
      })

      ws.on('close', () => {
        console.log(`Client disconnected: ${clientId}`)
        if (connection.pipeline) {
          connection.pipeline.stop()
        }
        if (connection.transcriptionService) {
          connection.transcriptionService.close()
        }
        clients.delete(clientId)
      })

      ws.on('error', (error) => {
        console.error(`WebSocket error for client ${clientId}:`, error)
      })

    } catch (error) {
      console.error('Error initializing services:', error)
      ws.send(JSON.stringify({ 
        type: 'error', 
        message: 'Failed to initialize services' 
      }))
      ws.close()
    }
  })

  return wss
}

