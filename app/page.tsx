'use client'

import { useState, useRef, useEffect } from 'react'
import styles from './page.module.css'

export default function Home() {
  const [isConnected, setIsConnected] = useState(false)
  const [transcription, setTranscription] = useState('')
  const [partialTranscription, setPartialTranscription] = useState('')
  const [transcriptionHistory, setTranscriptionHistory] = useState<string[]>([])
  const [isListening, setIsListening] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const audioRef = useRef<HTMLAudioElement>(null)
  const pcRef = useRef<RTCPeerConnection | null>(null)
  const streamRef = useRef<MediaStream | null>(null)

  const PIPECAT_URL = process.env.NEXT_PUBLIC_PIPECAT_URL || 'http://localhost:7860'

  interface ExtendedRTCPeerConnection extends RTCPeerConnection {
    pc_id?: string
    pendingIceCandidates: RTCIceCandidate[]
    canSendIceCandidates: boolean
  }

  useEffect(() => {
    return () => {
      stopConnection()
    }
  }, [])

  const sendIceCandidate = async (pc: ExtendedRTCPeerConnection, candidate: RTCIceCandidate) => {
    if (!pc.pc_id) {
      console.error('Cannot send ICE candidate: pc_id not set')
      return
    }

    await fetch(`${PIPECAT_URL}/api/offer`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        pc_id: pc.pc_id,
        candidates: [{
          candidate: candidate.candidate,
          sdp_mid: candidate.sdpMid,
          sdp_mline_index: candidate.sdpMLineIndex,
        }],
      }),
    })
  }

  const createSmallWebRTCConnection = async (audioTrack: MediaStreamTrack) => {
    const config = {
      iceServers: [
        { urls: 'stun:stun.l.google.com:19302' },
      ],
    }

    const pc = new RTCPeerConnection(config) as ExtendedRTCPeerConnection

    // Queue to store ICE candidates until we have received the answer and have a session in progress
    pc.pendingIceCandidates = []
    pc.canSendIceCandidates = false

    // Handle incoming audio tracks (TTS audio from server)
    pc.ontrack = (event) => {
      console.log('Received remote track:', event.track.kind)
      if (event.track.kind === 'audio') {
        const audioElement = audioRef.current
        if (audioElement) {
          audioElement.srcObject = event.streams[0]
          audioElement.play().catch(console.error)
        }
      }
    }

    // SmallWebRTCTransport expects to receive both transceivers
    pc.addTransceiver(audioTrack, { direction: 'sendrecv' })
    pc.addTransceiver('video', { direction: 'sendrecv' })

    // Create data channel for receiving transcription messages from server
    // This must be created BEFORE creating the offer
    const dataChannel = pc.createDataChannel('messages', { ordered: true })
    
    dataChannel.onopen = () => {
      console.log('Data channel opened')
    }
    
    dataChannel.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        console.log('Received data channel message:', data)
        if (data.type === 'transcription') {
          setTranscription(data.text)
          setPartialTranscription('')
          if (data.text) {
            setTranscriptionHistory(prev => [...prev, data.text])
          }
        } else if (data.type === 'partial') {
          setPartialTranscription(data.text)
        }
      } catch (e) {
        console.error('Error parsing data channel message:', e)
      }
    }
    
    dataChannel.onerror = (error) => {
      console.error('Data channel error:', error)
    }
    
    // Also listen for data channels created by server (backup)
    pc.ondatachannel = (event) => {
      const serverChannel = event.channel
      console.log('Server data channel received:', serverChannel.label)
      
      serverChannel.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          console.log('Received from server channel:', data)
          if (data.type === 'transcription') {
            setTranscription(data.text)
            setPartialTranscription('')
            if (data.text) {
              setTranscriptionHistory(prev => [...prev, data.text])
            }
          } else if (data.type === 'partial') {
            setPartialTranscription(data.text)
          }
        } catch (e) {
          console.error('Error parsing server channel message:', e)
        }
      }
      
      serverChannel.onopen = () => {
        console.log('Server data channel opened')
      }
    }

    // Handle ICE candidates
    pc.onicecandidate = async (event) => {
      if (event.candidate) {
        console.log('New ICE candidate:', event.candidate)
        // Check if we can send ICE candidates (we have received the answer with pc_id)
        if (pc.canSendIceCandidates && pc.pc_id) {
          // Send immediately
          await sendIceCandidate(pc, event.candidate)
        } else {
          // Queue the candidate until we have pc_id
          pc.pendingIceCandidates.push(event.candidate)
        }
      } else {
        console.log('All ICE candidates have been sent.')
      }
    }

    pc.oniceconnectionstatechange = () => {
      console.log('ICE connection state:', pc.iceConnectionState)
    }

    pc.onconnectionstatechange = () => {
      console.log('Connection state:', pc.connectionState)
      if (pc.connectionState === 'connected') {
        setIsConnected(true)
        setIsListening(true)
      } else if (pc.connectionState === 'disconnected' || pc.connectionState === 'failed') {
        setIsConnected(false)
        setIsListening(false)
      }
    }

    // Create offer
    await pc.setLocalDescription(await pc.createOffer())
    const offer = pc.localDescription

    // Send offer to server
    const response = await fetch(`${PIPECAT_URL}/api/offer`, {
      body: JSON.stringify({ sdp: offer!.sdp, type: offer!.type }),
      headers: { 'Content-Type': 'application/json' },
      method: 'POST',
    })

    if (!response.ok) {
      throw new Error(`Server error: ${response.status}`)
    }

    const answer = await response.json()
    pc.pc_id = answer.pc_id

    // Set remote description from server answer
    await pc.setRemoteDescription(answer)

    // Now we can send ICE candidates
    pc.canSendIceCandidates = true

    // Send any queued ICE candidates
    for (const candidate of pc.pendingIceCandidates) {
      await sendIceCandidate(pc, candidate)
    }
    pc.pendingIceCandidates = []

    return pc
  }

  const startConnection = async () => {
    try {
      setError(null)
      setIsConnected(false)
      setIsListening(false)

      // Get user media (audio only)
      const audioStream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = audioStream

      // Create SmallWebRTC connection
      const pc = await createSmallWebRTCConnection(audioStream.getAudioTracks()[0])
      pcRef.current = pc

      console.log('WebRTC connection established')

    } catch (err) {
      console.error('Error starting connection:', err)
      setError(err instanceof Error ? err.message : 'Failed to start connection')
      stopConnection()
    }
  }

  const stopConnection = () => {
    if (pcRef.current) {
      pcRef.current.close()
      pcRef.current = null
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(track => track.stop())
      streamRef.current = null
    }
    if (audioRef.current) {
      audioRef.current.srcObject = null
    }
    setIsConnected(false)
    setIsListening(false)
    setTranscription('')
    setPartialTranscription('')
  }

  // Note: Transcription and TTS are handled by the pipeline on the server side
  // The WebRTC connection streams audio bidirectionally, so speech goes directly to STT
  // and TTS audio comes back through the audio track

  return (
    <main className={styles.main}>
      <div className={styles.container}>
        <h1 className={styles.title}>TARS Omni</h1>
        <p className={styles.subtitle}>Real-time Voice AI powered by Qwen, Speechmatics & ElevenLabs</p>
        
        {error && (
          <div className={styles.error}>
            Error: {error}
          </div>
        )}
        
        <div className={styles.controls}>
          {!isConnected ? (
            <button 
              onClick={startConnection} 
              className={styles.button}
            >
              <span>🎙️ Start Voice Session</span>
            </button>
          ) : (
            <button 
              onClick={stopConnection} 
              className={`${styles.button} ${styles.stopButton}`}
            >
              <span>⏹️ Stop Session</span>
            </button>
          )}
        </div>
        
        {isListening && (
          <div className={styles.status}>
            <div className={styles.pulse}></div>
            <span>✨ Listening and Processing...</span>
          </div>
        )}
        
        <div className={styles.transcription}>
          <h2>Live Transcription</h2>
          {!transcription && !partialTranscription && (
            <p className={styles.placeholder}>
              Transcription will appear here as you speak...
            </p>
          )}
          {transcription && (
            <div className={styles.finalTranscript}>
              {transcription}
            </div>
          )}
          {partialTranscription && (
            <div className={styles.partialTranscript}>
              {partialTranscription}
            </div>
          )}
          {transcriptionHistory.length > 0 && (
            <div className={styles.history}>
              <h3>History:</h3>
              {transcriptionHistory.slice(-5).reverse().map((text, idx) => (
                <div key={idx} className={styles.historyItem}>{text}</div>
              ))}
            </div>
          )}
        </div>
        
        <audio ref={audioRef} className={styles.audio} controls autoPlay />
        <p className={styles.info}>
          Audio from your microphone is sent to the server via WebRTC.
          TTS audio responses will play automatically above.
        </p>
      </div>
    </main>
  )
}
