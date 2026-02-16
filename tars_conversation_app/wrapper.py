"""TarsApp wrapper for tars-conversation-app.

This wrapper allows the existing tars_bot.py to run within the TarsApp framework.
It runs tars_bot.py as a subprocess and manages its lifecycle.
"""

import threading
import subprocess
import signal
import sys
import os
from pathlib import Path
from typing import Optional

# Import TarsApp from tars-daemon
try:
    from tars_app import TarsApp
    from tars_sdk import TarsClient
except ImportError:
    # Fallback for development/testing
    print("Warning: tars_app not found. Install from tars-daemon first.")
    class TarsApp:
        name = ""
        description = ""
        version = ""
        custom_app_url = None
        def run(self, tars, stop_event): pass
        def on_start(self): pass
        def on_stop(self): pass
    class TarsClient:
        pass


class ConversationApp(TarsApp):
    """Wrapper for tars_bot.py - runs the full conversation pipeline as a TarsApp.

    This wrapper demonstrates how to integrate existing complex apps into the
    TarsApp framework. It runs tars_bot.py as a subprocess and manages its lifecycle.
    """

    # App metadata (also defined in manifest.json)
    name = "Conversation App"
    description = "Real-time conversational AI with WebRTC, memory, and vision"
    author = "TARS Team"
    version = "1.0.0"

    # Gradio dashboard URL (shows metrics and status)
    custom_app_url = "http://localhost:7860"

    def __init__(self):
        """Initialize the conversation app wrapper."""
        self.process: Optional[subprocess.Popen] = None
        self.app_dir = Path(__file__).parent.parent

    def on_start(self):
        """Called before run() starts."""
        print(f"Starting {self.name}...")
        print(f"  Version: {self.version}")
        print(f"  Dashboard: {self.custom_app_url}")

    def run(self, tars: TarsClient, stop_event: threading.Event):
        """Run tars_bot.py as a subprocess.

        The subprocess runs the full conversation pipeline including:
        - WebRTC audio streaming
        - Speech-to-text (Deepgram/Speechmatics)
        - LLM conversation (DeepInfra)
        - Text-to-speech (ElevenLabs/Piper)
        - Memory management (ChromaDB + BM25)
        - Vision analysis (Moondream)
        - Gradio metrics dashboard

        Args:
            tars: TarsClient instance (not used - tars_bot.py manages its own connection)
            stop_event: Event that signals when to stop
        """
        # Find Python executable in venv
        venv_python = self.app_dir / "venv" / "bin" / "python"
        if not venv_python.exists():
            print(f"Error: Virtual environment not found at {venv_python}")
            print("Run install.sh first")
            return

        # Path to tars_bot.py
        script = self.app_dir / "tars_bot.py"
        if not script.exists():
            print(f"Error: tars_bot.py not found at {script}")
            return

        # Set up environment (inherit current env)
        env = os.environ.copy()

        # Load .env file if it exists
        env_file = self.app_dir / ".env"
        if env_file.exists():
            print(f"Loading environment from {env_file}")
            with open(env_file) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        env[key.strip()] = value.strip()

        try:
            # Start tars_bot.py subprocess
            print(f"Starting tars_bot.py subprocess...")
            self.process = subprocess.Popen(
                [str(venv_python), str(script)],
                cwd=str(self.app_dir),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                # Don't use shell=True for better control
                shell=False
            )

            print(f"✓ Subprocess started with PID: {self.process.pid}")
            print(f"✓ Gradio dashboard should be available at {self.custom_app_url}")

            # Wait for stop signal or process exit
            while not stop_event.is_set():
                # Check if process died unexpectedly
                if self.process.poll() is not None:
                    # Process exited
                    return_code = self.process.returncode
                    print(f"tars_bot.py exited with code {return_code}")

                    # Print stderr if available
                    if self.process.stderr:
                        stderr = self.process.stderr.read().decode('utf-8', errors='ignore')
                        if stderr:
                            print(f"Subprocess stderr:\n{stderr}")

                    break

                # Wait a bit before checking again (allows graceful shutdown)
                if stop_event.wait(timeout=1.0):
                    break  # stop_event was set

        except Exception as e:
            print(f"Error running tars_bot.py: {e}")
            import traceback
            traceback.print_exc()

    def on_stop(self):
        """Stop the subprocess gracefully.

        Sends SIGTERM first for graceful shutdown, then SIGKILL if it doesn't stop.
        """
        print(f"Stopping {self.name}...")

        if self.process and self.process.poll() is None:
            # Process is still running
            print(f"Sending SIGTERM to PID {self.process.pid}...")

            try:
                # Send SIGTERM for graceful shutdown
                self.process.terminate()

                # Wait up to 5 seconds for graceful shutdown
                try:
                    self.process.wait(timeout=5.0)
                    print("✓ Process stopped gracefully")
                except subprocess.TimeoutExpired:
                    # Force kill if not stopped
                    print("Process didn't stop, sending SIGKILL...")
                    self.process.kill()
                    self.process.wait()
                    print("✓ Process killed")

            except Exception as e:
                print(f"Error stopping process: {e}")

        print(f"✓ {self.name} stopped")


# For testing the wrapper directly
if __name__ == "__main__":
    print("Testing ConversationApp wrapper...")

    app = ConversationApp()
    print(f"App: {app.name}")
    print(f"Version: {app.version}")
    print(f"Description: {app.description}")
    print(f"Dashboard URL: {app.custom_app_url}")

    # Test lifecycle (won't actually run without proper setup)
    app.on_start()
    print("Wrapper initialized successfully!")
