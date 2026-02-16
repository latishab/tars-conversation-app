"""Gradio UI for TARS Conversation App - Real-time TTFB metrics dashboard."""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import gradio as gr
import plotly.graph_objects as go
from src.shared_state import metrics_store
from typing import List
import statistics


# === Helper Functions ===

def calculate_stats(values: List[float]) -> dict:
    """Calculate min/max/avg/last for a list of values."""
    if not values:
        return {"last": None, "avg": None, "min": None, "max": None}
    return {
        "last": values[-1],
        "avg": statistics.mean(values),
        "min": min(values),
        "max": max(values),
    }


def format_ms(val) -> str:
    """Format milliseconds for display."""
    if val is None:
        return "N/A"
    return f"{val:.0f}ms"


# === Stats Display Functions ===

def get_service_badges() -> str:
    """Return service info as markdown badges."""
    info = metrics_store.get_service_info()
    if not info:
        return "⏳ Waiting for connection..."
    return f"**STT:** {info.get('stt', 'N/A')} | **Memory:** {info.get('memory', 'N/A')} | **LLM:** {info.get('llm', 'N/A')} | **TTS:** {info.get('tts', 'N/A')}"


def get_turn_count() -> str:
    """Return turn count."""
    count = len(metrics_store.get_metrics())
    return f"**Turns tracked:** {count}"


def get_stt_stats() -> str:
    """Get STT statistics as markdown."""
    metrics = metrics_store.get_metrics()
    values = [m.stt_ttfb_ms for m in metrics if m.stt_ttfb_ms is not None]
    stats = calculate_stats(values)
    return f"""**Last:** {format_ms(stats['last'])}
**Avg:** {format_ms(stats['avg'])}
**Min:** {format_ms(stats['min'])}
**Max:** {format_ms(stats['max'])}"""


def get_memory_stats() -> str:
    """Get Memory statistics as markdown."""
    metrics = metrics_store.get_metrics()
    values = [m.memory_latency_ms for m in metrics if m.memory_latency_ms is not None]
    stats = calculate_stats(values)
    return f"""**Last:** {format_ms(stats['last'])}
**Avg:** {format_ms(stats['avg'])}
**Min:** {format_ms(stats['min'])}
**Max:** {format_ms(stats['max'])}"""


def get_llm_stats() -> str:
    """Get LLM statistics as markdown."""
    metrics = metrics_store.get_metrics()
    values = [m.llm_ttfb_ms for m in metrics if m.llm_ttfb_ms is not None]
    stats = calculate_stats(values)
    return f"""**Last:** {format_ms(stats['last'])}
**Avg:** {format_ms(stats['avg'])}
**Min:** {format_ms(stats['min'])}
**Max:** {format_ms(stats['max'])}"""


def get_tts_stats() -> str:
    """Get TTS statistics as markdown."""
    metrics = metrics_store.get_metrics()
    values = [m.tts_ttfb_ms for m in metrics if m.tts_ttfb_ms is not None]
    stats = calculate_stats(values)
    return f"""**Last:** {format_ms(stats['last'])}
**Avg:** {format_ms(stats['avg'])}
**Min:** {format_ms(stats['min'])}
**Max:** {format_ms(stats['max'])}"""


def get_total_stats() -> str:
    """Get Total latency statistics as markdown."""
    metrics = metrics_store.get_metrics()
    values = [m.total_ms for m in metrics if m.total_ms is not None]
    stats = calculate_stats(values)
    return f"""### Total Latency
**Last:** {format_ms(stats['last'])} | **Avg:** {format_ms(stats['avg'])} | **Min:** {format_ms(stats['min'])} | **Max:** {format_ms(stats['max'])}"""


# === Chart Functions ===

def create_latency_chart():
    """Create Plotly line chart for latency over time."""
    metrics = metrics_store.get_metrics()

    if not metrics:
        fig = go.Figure()
        fig.add_annotation(text="No data yet", xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False)
        fig.update_layout(height=400, template="plotly_dark")
        return fig

    turns = [m.turn_number for m in metrics]

    fig = go.Figure()

    # Add traces for each metric
    stt_values = [m.stt_ttfb_ms for m in metrics]
    memory_values = [m.memory_latency_ms for m in metrics]
    llm_values = [m.llm_ttfb_ms for m in metrics]
    tts_values = [m.tts_ttfb_ms for m in metrics]

    fig.add_trace(go.Scatter(x=turns, y=stt_values, name="STT", line=dict(color="#00D4FF", width=2)))
    fig.add_trace(go.Scatter(x=turns, y=memory_values, name="Memory", line=dict(color="#FF6B6B", width=2)))
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


def create_breakdown_chart():
    """Create stacked bar chart showing latency breakdown for recent turns."""
    metrics = metrics_store.get_metrics()[-10:]  # Last 10 turns

    if not metrics:
        fig = go.Figure()
        fig.add_annotation(text="No data yet", xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False)
        fig.update_layout(height=300, template="plotly_dark")
        return fig

    turns = [f"Turn {m.turn_number}" for m in metrics]

    fig = go.Figure(data=[
        go.Bar(name="STT", x=turns, y=[m.stt_ttfb_ms or 0 for m in metrics], marker_color="#00D4FF"),
        go.Bar(name="Memory", x=turns, y=[m.memory_latency_ms or 0 for m in metrics], marker_color="#FF6B6B"),
        go.Bar(name="LLM", x=turns, y=[m.llm_ttfb_ms or 0 for m in metrics], marker_color="#4ECDC4"),
        go.Bar(name="TTS", x=turns, y=[m.tts_ttfb_ms or 0 for m in metrics], marker_color="#FFE66D"),
    ])

    fig.update_layout(
        barmode='stack',
        title="Latency Breakdown (Last 10 Turns)",
        yaxis_title="Latency (ms)",
        height=300,
        template="plotly_dark",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=50, r=50, t=80, b=50),
    )

    return fig


# === Table Functions ===

def get_metrics_table() -> str:
    """Return recent metrics as markdown table."""
    metrics = metrics_store.get_metrics()[-15:]  # Last 15

    if not metrics:
        return "No metrics recorded yet."

    rows = ["| Turn | STT | Memory | LLM | TTS | Total |", "|------|-----|--------|-----|-----|-------|"]

    for m in reversed(metrics):  # Most recent first
        rows.append(f"| {m.turn_number} | {format_ms(m.stt_ttfb_ms)} | {format_ms(m.memory_latency_ms)} | {format_ms(m.llm_ttfb_ms)} | {format_ms(m.tts_ttfb_ms)} | {format_ms(m.total_ms)} |")

    return "\n".join(rows)


# === Transcription Functions ===

def get_transcription_history() -> List[List[str]]:
    """Get transcription history for chatbot display."""
    transcriptions = metrics_store.get_transcriptions()
    history = []

    for t in transcriptions:
        if t["role"] == "user":
            history.append([t["text"], None])
        else:
            if history and history[-1][1] is None:
                history[-1][1] = t["text"]
            else:
                history.append([None, t["text"]])

    return history


# === Action Functions ===

def clear_all_metrics():
    """Clear all stored metrics."""
    metrics_store.clear_metrics()
    return "Metrics cleared"


# === Build Gradio Interface ===

with gr.Blocks(
    title="TARS Conversation App",
    theme=gr.themes.Soft(primary_hue="cyan", neutral_hue="slate"),
    css="""
        .stat-card { padding: 10px; border-radius: 8px; background: #1a1a2e; }
        .stat-card h3 { margin: 0 0 10px 0; color: #00D4FF; }
    """
) as demo:

    gr.Markdown("# TARS Conversation App")
    gr.Markdown("Real-time TTFB metrics from Pipecat pipeline")

    # Service info and turn count
    with gr.Row():
        service_info = gr.Markdown(get_service_badges, every=2)
        turn_count = gr.Markdown(get_turn_count, every=1)

    with gr.Tabs():
        # === Latency Dashboard Tab ===
        with gr.Tab("Latency Dashboard"):

            # Stats cards row
            with gr.Row():
                with gr.Column(scale=1):
                    gr.Markdown("### STT")
                    stt_stats = gr.Markdown(get_stt_stats, every=1)
                with gr.Column(scale=1):
                    gr.Markdown("### Memory")
                    memory_stats = gr.Markdown(get_memory_stats, every=1)
                with gr.Column(scale=1):
                    gr.Markdown("### LLM")
                    llm_stats = gr.Markdown(get_llm_stats, every=1)
                with gr.Column(scale=1):
                    gr.Markdown("### TTS")
                    tts_stats = gr.Markdown(get_tts_stats, every=1)

            # Total latency
            total_stats = gr.Markdown(get_total_stats, every=1)

            # Charts
            latency_chart = gr.Plot(create_latency_chart, every=2)
            breakdown_chart = gr.Plot(create_breakdown_chart, every=2)

            # Metrics table
            gr.Markdown("### Recent Turns")
            metrics_table = gr.Markdown(get_metrics_table, every=1)

            # Clear button
            with gr.Row():
                clear_btn = gr.Button("Clear Metrics", variant="secondary")
                clear_status = gr.Markdown("")
                clear_btn.click(clear_all_metrics, outputs=clear_status)

        # === Transcription Tab ===
        with gr.Tab("Conversation"):
            gr.Markdown("### Live Transcription")
            gr.Markdown("*Voice interaction happens via WebRTC connection to TARS*")

            chatbot = gr.Chatbot(
                value=get_transcription_history,
                every=1,
                height=500,
                label="Conversation History"
            )

        # === Connection Tab ===
        with gr.Tab("Connection"):
            gr.Markdown("### WebRTC Connection")
            gr.Markdown("""
**To connect to TARS:**

1. Ensure bot pipeline is running: `python bot.py`
2. Open WebRTC client in browser
3. Pipeline will connect automatically

**Endpoints:**
- WebRTC Signaling: Handled by SmallWebRTC transport
- Health Check: Check bot.py logs for status

**Architecture:**
- Pipecat pipeline with STT, LLM, TTS
- Observers collect metrics and transcriptions
- Shared state stores data for this UI
- WebRTC for audio streaming
            """)


# === Launch ===

def launch_app(port: int = 7861, share: bool = False):
    """Launch the Gradio app."""
    demo.launch(
        server_port=port,
        share=share,
        show_error=True,
    )


if __name__ == "__main__":
    launch_app()
