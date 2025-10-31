"use client";

import { useEffect, useRef, useState } from "react";

type ChatChunk = {
  textDelta?: string;
  audioBase64Delta?: string;
};

export default function Page() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [message, setMessage] = useState("");
  const [transcript, setTranscript] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const audioRef = useRef<HTMLAudioElement>(null);

  useEffect(() => {
    (async () => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
        }
      } catch (e) {
        // ignore
      }
    })();
  }, []);

  const handleSend = async () => {
    if (!message.trim()) return;
    setIsLoading(true);
    setTranscript("");
    let audioBase64 = "";

    try {
      // Capture a snapshot from the camera
      let imageDataUrl: string | undefined = undefined;
      if (videoRef.current) {
        const video = videoRef.current;
        const canvas = document.createElement("canvas");
        canvas.width = video.videoWidth || 640;
        canvas.height = video.videoHeight || 360;
        const ctx = canvas.getContext("2d");
        if (ctx) {
          ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
          imageDataUrl = canvas.toDataURL("image/jpeg", 0.85);
        }
      }

      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, imageDataUrl })
      });

      if (!res.body) throw new Error("No response body");
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        for (const line of lines) {
          if (!line) continue;
          try {
            const chunk: ChatChunk = JSON.parse(line);
            if (chunk.textDelta) setTranscript((t) => t + chunk.textDelta);
            if (chunk.audioBase64Delta) audioBase64 += chunk.audioBase64Delta;
          } catch {}
        }
      }

      if (audioBase64 && audioRef.current) {
        const bytes = Uint8Array.from(atob(audioBase64), c => c.charCodeAt(0));
        const blob = new Blob([bytes], { type: "audio/wav" });
        const url = URL.createObjectURL(blob);
        audioRef.current.src = url;
        await audioRef.current.play().catch(() => {});
      }
    } catch (e) {
      // ignore
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div style={{ display: "grid", gap: 16, gridTemplateColumns: "1fr", maxWidth: 900, margin: "0 auto" }}>
      <h1 style={{ margin: 0 }}>Qwen3 Omni (Text + Audio) with Camera</h1>
      <div style={{ display: "grid", gap: 12, gridTemplateColumns: "1fr 1fr" }}>
        <div>
          <video ref={videoRef} autoPlay playsInline muted style={{ width: "100%", borderRadius: 8, background: "#111" }} />
        </div>
        <div>
          <div style={{ display: "grid", gap: 8 }}>
            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="Type your message"
              rows={5}
              style={{ width: "100%", resize: "vertical" }}
            />
            <button onClick={handleSend} disabled={isLoading}>
              {isLoading ? "Sending..." : "Send"}
            </button>
          </div>
          <div style={{ marginTop: 12, padding: 12, background: "#f5f5f5", minHeight: 120, borderRadius: 8, whiteSpace: "pre-wrap" }}>
            {transcript || (isLoading ? "Waiting for response..." : "Model response will appear here.")}
          </div>
          <div style={{ marginTop: 12 }}>
            <audio ref={audioRef} controls />
          </div>
        </div>
      </div>
    </div>
  );
}

