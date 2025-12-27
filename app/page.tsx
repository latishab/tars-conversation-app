'use client'

import { useState, useRef, useEffect } from 'react'
import styles from './page.module.css'

interface TranscriptionEntry {
  text: string
  speakerId?: string | null
}

export default function Home() {
  const [isConnected, setIsConnected] = useState(false)
  const [transcription, setTranscription] = useState<TranscriptionEntry | null>(null)
  const [partialTranscription, setPartialTranscription] = useState<TranscriptionEntry | null>(null)
  const [transcriptionHistory, setTranscriptionHistory] = useState<TranscriptionEntry[]>([])
  const [isListening, setIsListening] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isTarsSpeaking, setIsTarsSpeaking] = useState(false)
  const audioRef = useRef<HTMLAudioElement>(null)
  const localVideoRef = useRef<HTMLVideoElement>(null)
  const remoteVideoRef = useRef<HTMLVideoElement>(null)
  const pcRef = useRef<RTCPeerConnection | null>(null)
  const streamRef = useRef<MediaStream | null>(null)

  const PIPECAT_URL = process.env.NEXT_PUBLIC_PIPECAT_URL || 'http://localhost:7860'
  const spectrumBars = Array.from({ length: 8 }, (_, idx) => idx)

  interface ExtendedRTCPeerConnection extends RTCPeerConnection {
    pc_id?: string
    pendingIceCandidates: RTCIceCandidate[]
    canSendIceCandidates: boolean
  }

  // Helper function to get speaker label class based on speaker ID
  const getSpeakerLabelClass = (speakerId: string | null | undefined): string => {
    if (!speakerId) return styles.speakerLabel
    const normalizedId = speakerId.toString().toUpperCase()
    // Check if speaker ID contains '1' (for S1) or '2' (for S2)
    if (normalizedId.includes('1') || normalizedId === 'S1') {
      return `${styles.speakerLabel} ${styles.speakerLabelS1}`
    } else if (normalizedId.includes('2') || normalizedId === 'S2') {
      return `${styles.speakerLabel} ${styles.speakerLabelS2}`
    }
    // Default to S1 style if unknown
    return `${styles.speakerLabel} ${styles.speakerLabelS1}`
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

  const createSmallWebRTCConnection = async (audioTrack: MediaStreamTrack, videoTrack: MediaStreamTrack | null) => {
    const config = {
      iceServers: [
        { urls: 'stun:stun.l.google.com:19302' },
      ],
    }

    const pc = new RTCPeerConnection(config) as ExtendedRTCPeerConnection

    // Queue to store ICE candidates until we have received the answer and have a session in progress
    pc.pendingIceCandidates = []
    pc.canSendIceCandidates = false

    // Handle incoming audio and video tracks from server
    pc.ontrack = (event) => {
      console.log('Received remote track:', event.track.kind)
      if (event.track.kind === 'audio') {
        const audioElement = audioRef.current
        if (audioElement) {
          audioElement.srcObject = event.streams[0]
          audioElement.play().catch(console.error)
        }
      } else if (event.track.kind === 'video') {
        const videoElement = remoteVideoRef.current
        if (videoElement) {
          videoElement.srcObject = event.streams[0]
          videoElement.play().catch(console.error)
        }
      }
    }

    // SmallWebRTCTransport expects to receive both transceivers
    pc.addTransceiver(audioTrack, { direction: 'sendrecv' })
    if (videoTrack) {
      const videoTransceiver = pc.addTransceiver(videoTrack, { direction: 'sendrecv' })
      
      // Force H.264/VP9 to avoid VP8 decode errors on the server
      if ('setCodecPreferences' in videoTransceiver.sender) {
        try {
          const codecs = RTCRtpSender.getCapabilities('video')?.codecs || []
          const preferredCodecs = [
            ...codecs.filter(c => c.mimeType.toLowerCase().includes('h264')),
            ...codecs.filter(c => c.mimeType.toLowerCase().includes('vp9')),
          ]
          const sender = videoTransceiver.sender as RTCRtpSender & { setCodecPreferences?: (codecs: any[]) => void }
          if (sender.setCodecPreferences && preferredCodecs.length > 0) {
            sender.setCodecPreferences(preferredCodecs)
            console.log('Video codec preferences set:', preferredCodecs.map(c => c.mimeType))
          }
        } catch (err) {
          console.warn('Could not set codec preferences:', err)
        }
      }
    } else {
      // Add video transceiver even if no video track yet (server expects it)
      pc.addTransceiver('video', { direction: 'sendrecv' })
    }

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
          const entry: TranscriptionEntry = {
            text: data.text,
            speakerId: data.speaker_id || null
          }
          setTranscription(entry)
          setPartialTranscription(null)
          if (data.text) {
            setTranscriptionHistory(prev => [...prev, entry])
          }
        } else if (data.type === 'partial') {
          const entry: TranscriptionEntry = {
            text: data.text,
            speakerId: data.speaker_id || null
          }
          setPartialTranscription(entry)
        } else if (data.type === 'error') {
          setError(data.message || 'An error occurred')
          setIsConnected(false)
          setIsListening(false)
        } else if (data.type === 'tts_state') {
          setIsTarsSpeaking(data.state === 'started')
        } else if (data.type === 'system') {
          console.log('System message:', data.message)
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
            const entry: TranscriptionEntry = {
              text: data.text,
              speakerId: data.speaker_id || null
            }
            setTranscription(entry)
            setPartialTranscription(null)
            if (data.text) {
              setTranscriptionHistory(prev => [...prev, entry])
            }
          } else if (data.type === 'partial') {
            const entry: TranscriptionEntry = {
              text: data.text,
              speakerId: data.speaker_id || null
            }
            setPartialTranscription(entry)
          } else if (data.type === 'error') {
            setError(data.message || 'An error occurred')
            setIsConnected(false)
            setIsListening(false)
          } else if (data.type === 'tts_state') {
            setIsTarsSpeaking(data.state === 'started')
          } else if (data.type === 'system') {
            console.log('System message:', data.message)
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
        setError(null) // Clear any previous errors
      } else if (pc.connectionState === 'disconnected' || pc.connectionState === 'failed') {
        setIsConnected(false)
        setIsListening(false)
        if (pc.connectionState === 'failed' && !error) {
          setError('Connection failed. Please check your network and try again.')
        }
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

      // Get user media (audio and video) with fixed resolution to prevent mid-stream changes
      const mediaStream = await navigator.mediaDevices.getUserMedia({ 
        audio: true,
        video: {
          width: { ideal: 1280, min: 1280 },
          height: { ideal: 720, min: 720 },
          frameRate: { ideal: 30, max: 30 },
          facingMode: 'user'
        }
      })
      
      streamRef.current = mediaStream

      // Display local video stream directly
      const localVideoElement = localVideoRef.current
      if (localVideoElement) {
        localVideoElement.srcObject = mediaStream
        localVideoElement.play().catch(console.error)
      }

      // Get audio and video tracks
      const audioTrack = mediaStream.getAudioTracks()[0]
      const videoTrack = mediaStream.getVideoTracks()[0] || null
      
      // Lock the video track settings to prevent resolution changes mid-stream
      if (videoTrack) {
        videoTrack.applyConstraints({
          width: 1280,
          height: 720,
          frameRate: 30
        }).catch(err => {
          console.warn('Could not apply video constraints:', err)
        })
      }

      // Create SmallWebRTC connection
      const pc = await createSmallWebRTCConnection(audioTrack, videoTrack)
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
    if (localVideoRef.current) {
      localVideoRef.current.srcObject = null
    }
    if (remoteVideoRef.current) {
      remoteVideoRef.current.srcObject = null
    }
    setIsConnected(false)
    setIsListening(false)
    setTranscription(null)
    setPartialTranscription(null)
    setIsTarsSpeaking(false)
  }

  // Note: Transcription and TTS are handled by the pipeline on the server side
  // The WebRTC connection streams audio bidirectionally, so speech goes directly to STT
  // and TTS audio comes back through the audio track

  return (
    <main className={styles.main}>
      <div className={styles.container}>
        <div className={styles.header}>
          <h1 className={styles.title}>TARS Omni</h1>
          <p className={styles.subtitle}>Real-time Voice AI powered by Qwen, Speechmatics & ElevenLabs</p>
          
          <div className={styles.headerControls}>
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
          </div>

          {error && (
            <div className={styles.error}>
              Error: {error}
            </div>
          )}
        </div>

        <div className={styles.contentGrid}>
          {/* Left Column - Video */}
          <div className={styles.videoColumn}>
            <div className={styles.videoWrapper}>
              <video 
                ref={localVideoRef} 
                className={styles.localVideo} 
                autoPlay 
                playsInline 
                muted
              />
              <div className={styles.videoLabel}>Camera Feed</div>
            </div>
            <div className={styles.voiceIndicator}>
              <div className={`${styles.voiceSpectrum} ${isTarsSpeaking ? styles.voiceSpectrumActive : ''}`}>
                {spectrumBars.map((bar) => (
                  <span key={bar} style={{ animationDelay: `${bar * 0.08}s` }}></span>
                ))}
              </div>
              <span className={styles.voiceStatusText}>
                {isTarsSpeaking ? 'TARS is speaking...' : 'TARS is idle'}
              </span>
            </div>
          </div>

          {/* Right Column - Chatbox */}
          <div className={styles.chatColumn}>
            <div className={styles.transcription}>
              <h2>Conversation</h2>
              <div className={styles.chatMessages}>
                {transcriptionHistory.length === 0 && !transcription && !partialTranscription && (
                  <p className={styles.placeholder}>
                    Transcription will appear here as you speak...
                  </p>
                )}
                
                {transcriptionHistory.map((entry, idx) => (
                  <div key={idx} className={styles.finalTranscript}>
                    {entry.speakerId && (
                      <span className={getSpeakerLabelClass(entry.speakerId)}>
                        Speaker {entry.speakerId}: 
                      </span>
                    )}
                    {entry.text}
                  </div>
                ))}
                
                {transcription && !transcriptionHistory.some(e => e.text === transcription.text && e.speakerId === transcription.speakerId) && (
                  <div className={styles.finalTranscript}>
                    {transcription.speakerId && (
                      <span className={getSpeakerLabelClass(transcription.speakerId)}>
                        Speaker {transcription.speakerId}: 
                      </span>
                    )}
                    {transcription.text}
                  </div>
                )}
                
                {partialTranscription && (
                  <div className={styles.partialTranscript}>
                    {partialTranscription.speakerId && (
                      <span className={getSpeakerLabelClass(partialTranscription.speakerId)}>
                        Speaker {partialTranscription.speakerId}: 
                      </span>
                    )}
                    {partialTranscription.text}
                  </div>
                )}
              </div>
            </div>
            
            <audio ref={audioRef} className={styles.audio} controls autoPlay />
            <p className={styles.info}>
              Audio and video from your camera are sent to the server via WebRTC.
              TTS audio responses will play automatically.
            </p>
          </div>
        </div>
      </div>
    </main>
  )
}
