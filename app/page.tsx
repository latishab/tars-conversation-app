'use client'

import { useState, useRef, useEffect } from 'react'
import { Button } from './components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from './components/ui/card'
import { Badge } from './components/ui/badge'
import { Alert, AlertDescription } from './components/ui/alert'
import { Separator } from './components/ui/separator'
import { Progress } from './components/ui/progress'

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

  const getSpeakerLabelVariant = (speakerId: string | null | undefined): "default" | "secondary" | "destructive" | "outline" => {
    if (!speakerId) return "outline"
    const normalizedId = speakerId.toString().toUpperCase()
    if (normalizedId.includes('1') || normalizedId === 'S1') return "default"
    if (normalizedId.includes('2') || normalizedId === 'S2') return "secondary"
    return "default"
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
        // Note: keyFrameInterval is not a standard WebRTC property 
        
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
    <main className="flex flex-col items-center justify-center min-h-screen p-8 relative overflow-x-hidden">
      <div className="bg-white/95 backdrop-blur-2xl rounded-3xl p-8 max-w-7xl w-full border border-white/50 relative z-10 flex flex-col gap-6">
        <div className="flex flex-col gap-4">
          <div className="text-center">
            <h1 className="text-4xl font-bold text-gray-900 mb-2">TARS Omni</h1>
            <p className="text-lg text-gray-600">Real-time Voice AI powered by Qwen, Speechmatics & ElevenLabs</p>
          </div>

          <div className="flex flex-col items-center gap-4">
            <div className="flex gap-4">
              {!isConnected ? (
                <Button onClick={startConnection} size="lg" className="px-6 py-3 text-lg">
                  🎙️ Start Voice Session
                </Button>
              ) : (
                <Button onClick={stopConnection} variant="destructive" size="lg" className="px-6 py-3 text-lg">
                  ⏹️ Stop Session
                </Button>
              )}
            </div>
            {isListening && (
              <div className="flex items-center gap-2 text-green-600 font-medium">
                <div className="w-3 h-3 bg-green-500 rounded-full animate-pulse"></div>
                <span>✨ Listening and Processing...</span>
              </div>
            )}
          </div>

          {error && (
            <Alert variant="destructive">
              <AlertDescription>Error: {error}</AlertDescription>
            </Alert>
          )}
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 w-full">
          <div className="space-y-6">
            <Card>
              <CardContent className="p-4">
                <div className="relative">
                  <video
                    ref={localVideoRef}
                    className="w-full h-64 bg-gray-100 rounded-lg object-cover"
                    autoPlay
                    playsInline
                    muted
                  />
                  <div className="absolute bottom-2 left-2 bg-black/70 text-white px-3 py-1 rounded-md text-sm">
                    Camera Feed
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-center">Voice Status</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex items-center justify-center gap-4 mb-4">
                  <div className={`flex gap-1 ${isTarsSpeaking ? 'animate-pulse' : ''}`}>
                    {spectrumBars.map((bar, idx) => (
                      <div
                        key={idx}
                        className={`w-2 bg-gradient-to-t from-blue-400 to-blue-600 rounded-full transition-all duration-300 ${
                          isTarsSpeaking ? 'h-8' : 'h-2'
                        }`}
                        style={{ animationDelay: `${idx * 0.1}s` }}
                      />
                    ))}
                  </div>
                </div>
                <p className="text-center text-sm text-gray-600">
                  {isTarsSpeaking ? 'TARS is speaking...' : 'TARS is idle'}
                </p>
              </CardContent>
            </Card>
          </div>

          <div className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle>Conversation</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-3 max-h-96 overflow-y-auto">
                  {transcriptionHistory.length === 0 && !transcription && !partialTranscription && (
                    <p className="text-gray-500 text-center py-8">Transcription will appear here as you speak...</p>
                  )}
                  {transcriptionHistory.map((entry, idx) => (
                    <div key={idx} className="flex gap-2 p-3 bg-gray-50 rounded-lg">
                      {entry.speakerId && (
                        <Badge variant={getSpeakerLabelVariant(entry.speakerId)}>
                          Speaker {entry.speakerId}
                        </Badge>
                      )}
                      <span className="flex-1">{entry.text}</span>
                    </div>
                  ))}
                  {transcription && !transcriptionHistory.some(e => e.text === transcription.text && e.speakerId === transcription.speakerId) && (
                    <div className="flex gap-2 p-3 bg-gray-50 rounded-lg">
                      {transcription.speakerId && (
                        <Badge variant={getSpeakerLabelVariant(transcription.speakerId)}>
                          Speaker {transcription.speakerId}
                        </Badge>
                      )}
                      <span className="flex-1">{transcription.text}</span>
                    </div>
                  )}
                  {partialTranscription && (
                    <div className="flex gap-2 p-3 bg-gray-100 rounded-lg opacity-70">
                      {partialTranscription.speakerId && (
                        <Badge variant={getSpeakerLabelVariant(partialTranscription.speakerId)}>
                          Speaker {partialTranscription.speakerId}
                        </Badge>
                      )}
                      <span className="flex-1 italic">{partialTranscription.text}</span>
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-4">
                <audio ref={audioRef} controls className="w-full" autoPlay />
                <Separator className="my-4" />
                <p className="text-sm text-gray-600 text-center">
                  Audio and video from your camera are sent to the server via WebRTC. TTS audio responses will play automatically.
                </p>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </main>
  )
}