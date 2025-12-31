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
  const audioContextRef = useRef<AudioContext | null>(null)
  const analyserRef = useRef<AnalyserNode | null>(null)
  const rafRef = useRef<number | null>(null)
  const lastSpeakingTimeRef = useRef<number>(0)

  const PIPECAT_URL = process.env.NEXT_PUBLIC_PIPECAT_URL || 'http://localhost:7860'
  const spectrumBars = Array.from({ length: 8 }, (_, idx) => idx)

  interface ExtendedRTCPeerConnection extends RTCPeerConnection {
    pc_id?: string
    pendingIceCandidates: RTCIceCandidate[]
    canSendIceCandidates: boolean
  }

  const getSpeakerLabelClass = (speakerId: string | null | undefined): string => {
    if (!speakerId) return styles.speakerLabel
    const normalizedId = speakerId.toString().toUpperCase()
    if (normalizedId.includes('1') || normalizedId === 'S1') return `${styles.speakerLabel} ${styles.speakerLabelS1}`
    if (normalizedId.includes('2') || normalizedId === 'S2') return `${styles.speakerLabel} ${styles.speakerLabelS2}`
    return `${styles.speakerLabel} ${styles.speakerLabelS1}`
  }

  useEffect(() => {
    return () => { stopConnection() }
  }, [])

  // --- AUDIO ANALYSIS ---
  const initAudioContext = () => {
    if (!audioContextRef.current) {
      audioContextRef.current = new (window.AudioContext || (window as any).webkitAudioContext)()
    }
    if (audioContextRef.current.state === 'suspended') {
      audioContextRef.current.resume().catch(console.error)
    }
  }

  const startAudioAnalysis = (stream: MediaStream) => {
    try {
      if (!audioContextRef.current) initAudioContext();
      const ctx = audioContextRef.current!
      const source = ctx.createMediaStreamSource(stream)
      const analyser = ctx.createAnalyser()
      analyser.fftSize = 256
      analyser.smoothingTimeConstant = 0.5
      source.connect(analyser)
      analyserRef.current = analyser
      const dataArray = new Uint8Array(analyser.frequencyBinCount)
      
      const checkAudioLevel = () => {
        if (!analyserRef.current) return
        analyserRef.current.getByteFrequencyData(dataArray)
        let sum = 0
        for (let i = 0; i < dataArray.length; i++) sum += dataArray[i]
        const average = sum / dataArray.length
        
        if (average > 20) { 
          setIsTarsSpeaking(true)
          lastSpeakingTimeRef.current = Date.now()
        } else if (Date.now() - lastSpeakingTimeRef.current > 400) {
          setIsTarsSpeaking(false)
        }
        rafRef.current = requestAnimationFrame(checkAudioLevel)
      }
      checkAudioLevel()
    } catch (err) { console.warn(err) }
  }

  const stopAudioAnalysis = () => {
    if (rafRef.current) { cancelAnimationFrame(rafRef.current); rafRef.current = null; }
    analyserRef.current = null; setIsTarsSpeaking(false);
  }

  const stripCodecs = (sdp: string, codecsToRemove: string[]) => {
    const lines = sdp.split('\r\n');
    const mLineIndex = lines.findIndex(l => l.startsWith('m=video'));
    if (mLineIndex === -1) return sdp;

    const badPts = new Set<string>();
    lines.forEach(l => {
      const match = l.match(/^a=rtpmap:(\d+) ([a-zA-Z0-9-]+)\/\d+/);
      if (match) {
        const pt = match[1];
        const codec = match[2].toUpperCase();
        if (codecsToRemove.includes(codec)) badPts.add(pt);
      }
    });

    lines.forEach(l => {
      const match = l.match(/^a=fmtp:(\d+) apt=(\d+)/);
      if (match && badPts.has(match[2])) badPts.add(match[1]);
    });

    if (badPts.size === 0) return sdp;

    const mLineParts = lines[mLineIndex].split(' ');
    const newMLine = [
      ...mLineParts.slice(0, 3), 
      ...mLineParts.slice(3).filter(pt => !badPts.has(pt))
    ].join(' ');
    lines[mLineIndex] = newMLine;

    const newLines = lines.filter(l => {
      const rtpmapMatch = l.match(/^a=rtpmap:(\d+)/);
      if (rtpmapMatch && badPts.has(rtpmapMatch[1])) return false;
      const fmtpMatch = l.match(/^a=fmtp:(\d+)/);
      if (fmtpMatch && badPts.has(fmtpMatch[1])) return false;
      const rtcpMatch = l.match(/^a=rtcp-fb:(\d+)/);
      if (rtcpMatch && badPts.has(rtcpMatch[1])) return false;
      return true;
    });

    console.log(`Removed codecs: ${codecsToRemove.join(', ')}. Remaining SDP lines: ${newLines.length}`);
    return newLines.join('\r\n');
  }

  const sendIceCandidate = async (pc: ExtendedRTCPeerConnection, candidate: RTCIceCandidate) => {
    if (!pc.pc_id) return
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
    const config = { iceServers: [{ urls: 'stun:stun.l.google.com:19302' }] }
    const pc = new RTCPeerConnection(config) as ExtendedRTCPeerConnection
    pc.pendingIceCandidates = []
    pc.canSendIceCandidates = false

    pc.ontrack = (event) => {
      if (event.track.kind === 'audio') {
        if (audioRef.current) {
          audioRef.current.srcObject = event.streams[0]
          audioRef.current.play().catch(console.error)
          startAudioAnalysis(event.streams[0])
        }
      } else if (event.track.kind === 'video') {
        if (remoteVideoRef.current) {
          remoteVideoRef.current.srcObject = event.streams[0]
          remoteVideoRef.current.play().catch(console.error)
        }
      }
    }

    pc.addTransceiver(audioTrack, { direction: 'sendrecv' })
    if (videoTrack) {
        const videoTransceiver = pc.addTransceiver(videoTrack, { 
            direction: 'sendrecv',
            streams: [streamRef.current!] 
        });

        // 1. Set Parameters: Lower bitrate and framerate for stability
        const parameters = videoTransceiver.sender.getParameters();
        if (!parameters.encodings) parameters.encodings = [{}];
        
        parameters.encodings[0].maxBitrate = 1_000_000; // 1 Mbps
        parameters.encodings[0].maxFramerate = 24;      // 24 FPS
        parameters.encodings[0].keyFrameInterval = 2000; 
        
        videoTransceiver.sender.setParameters(parameters)
            .catch(e => console.warn("setParameters failed:", e));

        // 2. Set Codec Preferences
        if ('setCodecPreferences' in videoTransceiver.sender) {
            try {
                const codecs = RTCRtpSender.getCapabilities('video')?.codecs || [];
                const h264Codecs = codecs.filter(c => c.mimeType.toLowerCase().includes('h264'));
                
                // Sort to put 42e01f (Constrained Baseline) first
                h264Codecs.sort((a, b) => {
                    const aIsSafe = (a.sdpFmtpLine || "").includes("42e01f") ? 2 : 0;
                    const bIsSafe = (b.sdpFmtpLine || "").includes("42e01f") ? 2 : 0;
                    // Secondary sort: standard baseline (42001f)
                    const aIsBase = (a.sdpFmtpLine || "").includes("42001f") ? 1 : 0;
                    const bIsBase = (b.sdpFmtpLine || "").includes("42001f") ? 1 : 0;
                    return (bIsSafe + bIsBase) - (aIsSafe + aIsBase);
                });

                const sender = videoTransceiver.sender as RTCRtpSender & { setCodecPreferences?: (codecs: any[]) => void };
                if (sender.setCodecPreferences && h264Codecs.length > 0) {
                    console.log("Setting H.264 preferences:", h264Codecs[0].sdpFmtpLine);
                    sender.setCodecPreferences(h264Codecs);
                }
            } catch (e) { console.warn("setCodecPreferences failed:", e); }
        }
    } else {
        pc.addTransceiver('video', { direction: 'sendrecv' });
    }

    const dataChannel = pc.createDataChannel('messages', { ordered: true })
    const handleMessage = (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data)
        if (data.type === 'transcription') {
          const entry = { text: data.text, speakerId: data.speaker_id || null }
          setTranscription(entry); setPartialTranscription(null);
          if (data.text) setTranscriptionHistory(prev => [...prev, entry])
        } else if (data.type === 'partial') {
          setPartialTranscription({ text: data.text, speakerId: data.speaker_id || null })
        } else if (data.type === 'error') {
          setError(data.message); setIsConnected(false); setIsListening(false);
        }
      } catch (e) { console.error(e) }
    }
    dataChannel.onmessage = handleMessage
    pc.ondatachannel = (event) => { event.channel.onmessage = handleMessage }

    pc.onicecandidate = async (event) => {
      if (event.candidate) {
        if (pc.canSendIceCandidates && pc.pc_id) await sendIceCandidate(pc, event.candidate)
        else pc.pendingIceCandidates.push(event.candidate)
      }
    }

    pc.onconnectionstatechange = () => {
      if (pc.connectionState === 'connected') {
        setIsConnected(true); setIsListening(true); setError(null);
      } else if (pc.connectionState === 'disconnected' || pc.connectionState === 'failed') {
        setIsConnected(false); setIsListening(false); stopAudioAnalysis();
      }
    }

    // 1. Create Offer
    const offer = await pc.createOffer()

    // 2. Strip VP8, VP9, and AV1 completely. Force H.264.
    const cleanSdp = stripCodecs(offer.sdp || "", ['VP8', 'VP9', 'AV1'])
    
    // 3. Set Local Description with CLEAN SDP
    await pc.setLocalDescription({ type: offer.type, sdp: cleanSdp })

    // 4. Send to Server
    const response = await fetch(`${PIPECAT_URL}/api/offer`, {
      body: JSON.stringify({ sdp: cleanSdp, type: offer.type }),
      headers: { 'Content-Type': 'application/json' },
      method: 'POST',
    })

    if (!response.ok) throw new Error(`Server error: ${response.status}`)
    const answer = await response.json()
    pc.pc_id = answer.pc_id
    await pc.setRemoteDescription(answer)
    pc.canSendIceCandidates = true
    for (const candidate of pc.pendingIceCandidates) await sendIceCandidate(pc, candidate)
    pc.pendingIceCandidates = []

    return pc
  }

  const startConnection = async () => {
    try {
      initAudioContext()
      setError(null); setIsConnected(false); setIsListening(false);

      const mediaStream = await navigator.mediaDevices.getUserMedia({ 
        audio: true,
        video: { width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 30 } }
      })
      streamRef.current = mediaStream

      if (localVideoRef.current) {
        localVideoRef.current.srcObject = mediaStream
        localVideoRef.current.play().catch(console.error)
      }

      const audioTrack = mediaStream.getAudioTracks()[0]
      const videoTrack = mediaStream.getVideoTracks()[0] || null
      if (videoTrack) videoTrack.applyConstraints({ width: 1280, height: 720, frameRate: 30 }).catch(console.warn)

      const pc = await createSmallWebRTCConnection(audioTrack, videoTrack)
      pcRef.current = pc
    } catch (err) {
      console.error(err)
      setError(err instanceof Error ? err.message : 'Failed to start connection')
      stopConnection()
    }
  }

  const stopConnection = () => {
    stopAudioAnalysis()
    if (pcRef.current) { pcRef.current.close(); pcRef.current = null; }
    if (streamRef.current) { streamRef.current.getTracks().forEach(track => track.stop()); streamRef.current = null; }
    if (audioRef.current) audioRef.current.srcObject = null;
    if (localVideoRef.current) localVideoRef.current.srcObject = null;
    if (remoteVideoRef.current) remoteVideoRef.current.srcObject = null;
    setIsConnected(false); setIsListening(false); setTranscription(null); setPartialTranscription(null); setIsTarsSpeaking(false);
  }

  return (
    <main className={styles.main}>
      <div className={styles.container}>
        <div className={styles.header}>
          <h1 className={styles.title}>TARS Omni</h1>
          <p className={styles.subtitle}>Real-time Voice AI powered by Qwen, Speechmatics & ElevenLabs</p>
          <div className={styles.headerControls}>
            <div className={styles.controls}>
              {!isConnected ? (
                <button onClick={startConnection} className={styles.button}><span>🎙️ Start Voice Session</span></button>
              ) : (
                <button onClick={stopConnection} className={`${styles.button} ${styles.stopButton}`}><span>⏹️ Stop Session</span></button>
              )}
            </div>
            {isListening && (
              <div className={styles.status}><div className={styles.pulse}></div><span>✨ Listening and Processing...</span></div>
            )}
          </div>
          {error && <div className={styles.error}>Error: {error}</div>}
        </div>
        <div className={styles.contentGrid}>
          <div className={styles.videoColumn}>
            <div className={styles.videoWrapper}>
              <video ref={localVideoRef} className={styles.localVideo} autoPlay playsInline muted />
              <div className={styles.videoLabel}>Camera Feed</div>
            </div>
            <div className={styles.voiceIndicator}>
              <div className={`${styles.voiceSpectrum} ${isTarsSpeaking ? styles.voiceSpectrumActive : ''}`}>
                {spectrumBars.map((bar) => (<span key={bar} style={{ animationDelay: `${bar * 0.08}s` }}></span>))}
              </div>
              <span className={styles.voiceStatusText}>{isTarsSpeaking ? 'TARS is speaking...' : 'TARS is idle'}</span>
            </div>
          </div>
          <div className={styles.chatColumn}>
            <div className={styles.transcription}>
              <h2>Conversation</h2>
              <div className={styles.chatMessages}>
                {transcriptionHistory.length === 0 && !transcription && !partialTranscription && (
                  <p className={styles.placeholder}>Transcription will appear here as you speak...</p>
                )}
                {transcriptionHistory.map((entry, idx) => (
                  <div key={idx} className={styles.finalTranscript}>
                    {entry.speakerId && <span className={getSpeakerLabelClass(entry.speakerId)}>Speaker {entry.speakerId}: </span>}
                    {entry.text}
                  </div>
                ))}
                {transcription && !transcriptionHistory.some(e => e.text === transcription.text && e.speakerId === transcription.speakerId) && (
                  <div className={styles.finalTranscript}>
                    {transcription.speakerId && <span className={getSpeakerLabelClass(transcription.speakerId)}>Speaker {transcription.speakerId}: </span>}
                    {transcription.text}
                  </div>
                )}
                {partialTranscription && (
                  <div className={styles.partialTranscript}>
                    {partialTranscription.speakerId && <span className={getSpeakerLabelClass(partialTranscription.speakerId)}>Speaker {partialTranscription.speakerId}: </span>}
                    {partialTranscription.text}
                  </div>
                )}
              </div>
            </div>
            <audio ref={audioRef} className={styles.audio} controls autoPlay />
            <p className={styles.info}>Audio and video from your camera are sent to the server via WebRTC. TTS audio responses will play automatically.</p>
          </div>
        </div>
      </div>
    </main>
  )
}