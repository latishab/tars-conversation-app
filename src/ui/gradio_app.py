"""Integrated Gradio UI for TARS Conversation App."""

import html as _html
import gradio as gr
import plotly.graph_objects as go
from typing import List
import statistics
import threading

from shared_state import metrics_store


# ---------------------------------------------------------------------------
# Embedded WebRTC client (browser audio mode)
# ---------------------------------------------------------------------------
# Rendered inside a srcdoc iframe so <script> tags actually execute
# (Gradio's Svelte @html directive does not run injected scripts).
# The iframe delegates mic permission from the parent via allow="microphone".
# ---------------------------------------------------------------------------

_WEBRTC_INNER = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * { box-sizing: border-box; }
  body {
    margin: 0;
    padding: 10px 14px;
    font-family: system-ui, sans-serif;
    background: transparent;
    display: flex;
    align-items: center;
    gap: 12px;
    height: 52px;
    overflow: hidden;
  }
  button {
    padding: 7px 16px;
    border-radius: 6px;
    border: 1px solid #475569;
    cursor: pointer;
    font-size: 13px;
    font-weight: 500;
    transition: background 0.15s, border-color 0.15s;
  }
  #cb { background: #0891b2; color: #fff; border-color: #0891b2; }
  #cb:hover { background: #0e7490; }
  #cb.live { background: #dc2626; border-color: #dc2626; }
  #cb.live:hover { background: #b91c1c; }
  #mb { background: #1e293b; color: #94a3b8; }
  #mb:hover:not(:disabled) { border-color: #64748b; }
  #mb.muted { color: #f59e0b; border-color: #f59e0b; }
  #mb:disabled { opacity: 0.35; cursor: default; }
  #st { font-size: 13px; color: #64748b; }
</style>
</head>
<body>
  <button id="cb" onclick="tc()">&#127908; Connect</button>
  <button id="mb" onclick="tm()" disabled>Mute</button>
  <span id="st">&#9679; Disconnected</span>
  <audio id="a" autoplay playsinline></audio>

<script>
"use strict";
var pc = null, mic = null, muted = false;
var API = window.parent.location.origin + "/api/offer";

function el(id) { return document.getElementById(id); }

function setStatus(text, color) {
  var s = el("st");
  s.textContent = "\\u25cf " + text;
  s.style.color = color;
}

function resetUI() {
  el("cb").textContent = "\\ud83c\\udf99\\ufe0f Connect";
  el("cb").className = "";
  el("mb").disabled = true;
  el("mb").textContent = "Mute";
  el("mb").className = "";
  el("a").srcObject = null;
  setStatus("Disconnected", "#64748b");
}

function disconnect() {
  if (mic) { mic.getTracks().forEach(function(t) { t.stop(); }); mic = null; }
  if (pc)  { pc.close(); pc = null; }
  muted = false;
  resetUI();
}

async function connect() {
  setStatus("Requesting mic\\u2026", "#f59e0b");
  try {
    mic = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
  } catch (e) {
    setStatus("Mic denied", "#ef4444");
    return;
  }

  pc = new RTCPeerConnection({ iceServers: [{ urls: "stun:stun.l.google.com:19302" }] });
  mic.getTracks().forEach(function(t) { pc.addTrack(t, mic); });

  pc.ontrack = function(ev) { el("a").srcObject = ev.streams[0]; };

  pc.onconnectionstatechange = function() {
    var s = pc ? pc.connectionState : "closed";
    if (s === "connected") {
      setStatus("Connected", "#10b981");
      el("cb").textContent = "\\u23f9\\ufe0f Disconnect";
      el("cb").className = "live";
      el("mb").disabled = false;
    } else if (s === "failed" || s === "closed") {
      disconnect();
    }
  };

  setStatus("Negotiating\\u2026", "#f59e0b");
  var offer = await pc.createOffer();
  await pc.setLocalDescription(offer);

  // Wait for ICE gathering so all candidates are bundled in the SDP
  await new Promise(function(resolve) {
    if (pc.iceGatheringState === "complete") { resolve(); return; }
    pc.addEventListener("icegatheringstatechange", function() {
      if (pc.iceGatheringState === "complete") resolve();
    });
    setTimeout(resolve, 4000); // 4s safety timeout
  });

  try {
    var resp = await fetch(API, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sdp: pc.localDescription.sdp, type: pc.localDescription.type })
    });
    if (!resp.ok) { throw new Error("HTTP " + resp.status); }
    var ans = await resp.json();
    await pc.setRemoteDescription(new RTCSessionDescription(ans));
  } catch (e) {
    setStatus("Error: " + e.message, "#ef4444");
    disconnect();
  }
}

async function tc() {
  if (pc) { disconnect(); } else { await connect(); }
}

function tm() {
  if (!mic) return;
  muted = !muted;
  mic.getTracks().forEach(function(t) { t.enabled = !muted; });
  el("mb").textContent = muted ? "Unmute" : "Mute";
  el("mb").className = muted ? "muted" : "";
}
</script>
</body>
</html>
"""

_WEBRTC_CLIENT_HTML = (
    '<iframe'
    ' allow="microphone; autoplay"'
    ' style="width:100%;border:none;height:60px;background:transparent;"'
    ' srcdoc="' + _html.escape(_WEBRTC_INNER) + '"'
    '></iframe>'
)


class TarsGradioUI:
    """Integrated Gradio UI for TARS conversation app."""

    def __init__(self):
        self._lock = threading.Lock()

    # === Display Methods (for Gradio) ===

    def get_conversation_history(self) -> List[tuple]:
        """Get conversation history in Gradio chatbot format."""
        transcriptions = metrics_store.get_transcriptions()
        history = []
        for t in transcriptions:
            if t["role"] == "user":
                history.append((t["text"], None))
            else:
                if history and history[-1][1] is None:
                    history[-1] = (history[-1][0], t["text"])
                else:
                    history.append((None, t["text"]))
        return history

    def get_status_display(self) -> str:
        """Get status for display."""
        status = metrics_store.get_pipeline_status()
        emoji_map = {
            "listening": "🎤",
            "thinking": "🤔",
            "speaking": "🗣️",
            "idle": "⚪",
            "disconnected": "❌",
            "error": "⚠️"
        }
        emoji = emoji_map.get(status, "⚪")
        return f"{emoji} **Status:** {status.title()}"

    def get_service_badges(self) -> str:
        """Return service info as markdown badges."""
        info = metrics_store.get_service_info()
        if not info:
            return "⏳ Waiting for connection..."
        return f"**STT:** {info.get('stt', 'N/A')} | **LLM:** {info.get('llm', 'N/A')} | **TTS:** {info.get('tts', 'N/A')}"

    def get_connection_info(self) -> str:
        """Get connection information."""
        return f"""### Connection Info
**Daemon:** {metrics_store.daemon_address}
**Audio Mode:** {metrics_store.audio_mode}
**Status:** {metrics_store.get_pipeline_status()}"""

    def get_turn_count(self) -> str:
        """Return turn count."""
        metrics = metrics_store.get_metrics()
        return f"**Turns:** {len(metrics)}"

    def calculate_stats(self, values: List[float]) -> dict:
        """Calculate min/max/avg/last for a list of values."""
        if not values:
            return {"last": None, "avg": None, "min": None, "max": None}
        return {
            "last": values[-1],
            "avg": statistics.mean(values),
            "min": min(values),
            "max": max(values),
        }

    def format_ms(self, val) -> str:
        """Format milliseconds for display."""
        if val is None:
            return "N/A"
        return f"{val:.0f}ms"

    def get_stt_stats(self) -> str:
        """Get STT statistics as markdown."""
        metrics = metrics_store.get_metrics()
        values = [m.stt_ttfb_ms for m in metrics if m.stt_ttfb_ms is not None]
        stats = self.calculate_stats(values)
        return f"""**Last:** {self.format_ms(stats['last'])}
**Avg:** {self.format_ms(stats['avg'])}
**Min:** {self.format_ms(stats['min'])}
**Max:** {self.format_ms(stats['max'])}"""

    def get_llm_stats(self) -> str:
        """Get LLM statistics as markdown."""
        metrics = metrics_store.get_metrics()
        values = [m.llm_ttfb_ms for m in metrics if m.llm_ttfb_ms is not None]
        stats = self.calculate_stats(values)
        return f"""**Last:** {self.format_ms(stats['last'])}
**Avg:** {self.format_ms(stats['avg'])}
**Min:** {self.format_ms(stats['min'])}
**Max:** {self.format_ms(stats['max'])}"""

    def get_tts_stats(self) -> str:
        """Get TTS statistics as markdown."""
        metrics = metrics_store.get_metrics()
        values = [m.tts_ttfb_ms for m in metrics if m.tts_ttfb_ms is not None]
        stats = self.calculate_stats(values)
        return f"""**Last:** {self.format_ms(stats['last'])}
**Avg:** {self.format_ms(stats['avg'])}
**Min:** {self.format_ms(stats['min'])}
**Max:** {self.format_ms(stats['max'])}"""

    def get_total_stats(self) -> str:
        """Get Total latency statistics as markdown."""
        metrics = metrics_store.get_metrics()
        values = [m.total_ms for m in metrics if m.total_ms is not None]
        stats = self.calculate_stats(values)
        return f"""### Total Latency
**Last:** {self.format_ms(stats['last'])} | **Avg:** {self.format_ms(stats['avg'])} | **Min:** {self.format_ms(stats['min'])} | **Max:** {self.format_ms(stats['max'])}"""

    def create_latency_chart(self):
        """Create Plotly line chart for latency over time."""
        metrics = metrics_store.get_metrics()
        if not metrics:
            fig = go.Figure()
            fig.add_annotation(text="No data yet", xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False)
            fig.update_layout(height=400, template="plotly_dark")
            return fig

        turns = [m.turn_number for m in metrics]
        stt_values = [m.stt_ttfb_ms for m in metrics]
        llm_values = [m.llm_ttfb_ms for m in metrics]
        tts_values = [m.tts_ttfb_ms for m in metrics]

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=turns, y=stt_values, name="STT", line=dict(color="#00D4FF", width=2)))
        fig.add_trace(go.Scatter(x=turns, y=llm_values, name="LLM", line=dict(color="#4ECDC4", width=2)))
        fig.add_trace(go.Scatter(x=turns, y=tts_values, name="TTS", line=dict(color="#FFE66D", width=2)))

        fig.update_layout(
            title="TTFB Latency Over Time",
            xaxis_title="Turn",
            yaxis_title="Latency (ms)",
            height=400,
            template="plotly_dark",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=50, r=50, t=80, b=50),
        )

        return fig

    def get_metrics_table(self) -> str:
        """Return recent metrics as markdown table."""
        metrics = metrics_store.get_metrics()
        recent = list(metrics)[-15:]  # Last 15

        if not recent:
            return "No metrics recorded yet."

        rows = ["| Turn | STT | LLM | TTS | Total |", "|------|-----|-----|-----|-------|"]

        for m in reversed(recent):  # Most recent first
            rows.append(f"| {m.turn_number} | {self.format_ms(m.stt_ttfb_ms)} | {self.format_ms(m.llm_ttfb_ms)} | {self.format_ms(m.tts_ttfb_ms)} | {self.format_ms(m.total_ms)} |")

        return "\n".join(rows)

    # === Build Gradio Interface ===

    def build_interface(self) -> gr.Blocks:
        """Build Gradio interface."""
        with gr.Blocks(
            title="TARS Conversation App",
            theme=gr.themes.Soft(primary_hue="cyan", neutral_hue="slate"),
        ) as demo:

            gr.Markdown("# TARS Conversation App")
            gr.Markdown("Real-time voice AI conversation with integrated metrics")

            # Timers for updates (slower intervals to reduce re-rendering)
            timer_fast = gr.Timer(value=2)  # 2 second updates
            timer_medium = gr.Timer(value=3)  # 3 second updates
            timer_slow = gr.Timer(value=5)  # 5 second updates

            # Top status bar
            with gr.Row():
                status_display = gr.Markdown()
                service_info = gr.Markdown()
                turn_count = gr.Markdown()

            # Only update status and turn count regularly (service info rarely changes)
            timer_fast.tick(fn=self.get_status_display, outputs=status_display)
            timer_fast.tick(fn=self.get_turn_count, outputs=turn_count)
            timer_slow.tick(fn=self.get_service_badges, outputs=service_info)

            with gr.Tabs():
                # === Conversation Tab ===
                with gr.Tab("Conversation"):
                    gr.Markdown("### Live Conversation")
                    audio_mode_md = gr.Markdown(f"*Audio: {metrics_store.get_audio_mode()}*")

                    if metrics_store.get_audio_mode() == "Browser (SmallWebRTC)":
                        gr.HTML(_WEBRTC_CLIENT_HTML)

                    chatbot = gr.Chatbot(
                        value=[],
                        height=500,
                        label="Conversation History",
                        show_copy_button=True,
                        type="tuples",
                    )

                    timer_fast.tick(fn=self.get_conversation_history, outputs=chatbot)
                    timer_slow.tick(
                        fn=lambda: f"*Audio: {metrics_store.get_audio_mode()}*",
                        outputs=audio_mode_md,
                    )

                # === Metrics Tab ===
                with gr.Tab("Metrics"):
                    # Stats cards row
                    with gr.Row():
                        with gr.Column(scale=1):
                            gr.Markdown("### STT")
                            stt_stats = gr.Markdown()
                        with gr.Column(scale=1):
                            gr.Markdown("### LLM")
                            llm_stats = gr.Markdown()
                        with gr.Column(scale=1):
                            gr.Markdown("### TTS")
                            tts_stats = gr.Markdown()

                    timer_fast.tick(fn=self.get_stt_stats, outputs=stt_stats)
                    timer_fast.tick(fn=self.get_llm_stats, outputs=llm_stats)
                    timer_fast.tick(fn=self.get_tts_stats, outputs=tts_stats)

                    # Total latency
                    total_stats = gr.Markdown()
                    timer_fast.tick(fn=self.get_total_stats, outputs=total_stats)

                    # Charts (slower updates for heavy components)
                    latency_chart = gr.Plot()
                    timer_slow.tick(fn=self.create_latency_chart, outputs=latency_chart)

                    # Metrics table
                    gr.Markdown("### Recent Turns")
                    metrics_table = gr.Markdown()
                    timer_fast.tick(fn=self.get_metrics_table, outputs=metrics_table)

                    # Clear button
                    with gr.Row():
                        clear_btn = gr.Button("Clear Metrics", variant="secondary")
                        clear_status = gr.Markdown("")

                        def clear():
                            metrics_store.clear_metrics()
                            return "Metrics cleared"

                        clear_btn.click(clear, outputs=clear_status)

                # === Settings Tab ===
                with gr.Tab("Settings"):
                    connection_info = gr.Markdown()
                    # Connection info rarely changes, update less frequently
                    timer_slow.tick(fn=self.get_connection_info, outputs=connection_info)

                    gr.Markdown("""
### About

**TARS Conversation App** - Real-time voice AI assistant

**Audio Architecture:**
- Robot mode: Pi mic/speaker via WebRTC
- Browser mode: Web client audio via SmallWebRTC

**Pipeline:** STT → LLM → TTS

**Metrics:** TTFB tracking for each service
                    """)

            return demo

    def launch(self, port: int = 7860, share: bool = False):
        """Launch the Gradio app."""
        demo = self.build_interface()
        demo.launch(
            server_name="127.0.0.1",
            server_port=port,
            share=share,
            show_error=True,
            prevent_thread_lock=False,
            quiet=False,
            show_api=False,  # Disable API docs to avoid schema generation bug
        )
