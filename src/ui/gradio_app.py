"""Integrated Gradio UI for TARS Conversation App."""

import gradio as gr
import plotly.graph_objects as go
from typing import List
import statistics
import threading

from shared_state import metrics_store


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
