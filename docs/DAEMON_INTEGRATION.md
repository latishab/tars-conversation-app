# Daemon Dashboard Integration

Guide for integrating tars-conversation-app with tars-daemon dashboard app management.

## Overview

The tars-daemon dashboard should provide install/uninstall buttons for managing TARS apps like this one.

## App Discovery

The daemon scans for apps with `app.json` manifest files:

```python
import json
from pathlib import Path

def discover_apps(apps_directory="/home/mac/tars-apps"):
    """Discover all TARS apps with manifests"""
    apps = []
    apps_dir = Path(apps_directory)

    for app_path in apps_dir.iterdir():
        manifest_path = app_path / "app.json"
        if manifest_path.exists():
            with open(manifest_path) as f:
                manifest = json.load(f)
                apps.append({
                    "path": str(app_path),
                    "manifest": manifest,
                    "installed": (app_path / "venv").exists()
                })

    return apps
```

## Installation Flow

When user clicks "Install" button:

```python
import subprocess
from pathlib import Path

def install_app(app_path):
    """Install a TARS app"""
    app_dir = Path(app_path)
    manifest_path = app_dir / "app.json"

    # Read manifest
    with open(manifest_path) as f:
        manifest = json.load(f)

    # Get install script
    install_script = manifest.get("install_script", "install.sh")
    script_path = app_dir / install_script

    if not script_path.exists():
        raise FileNotFoundError(f"Install script not found: {script_path}")

    # Run installation
    result = subprocess.run(
        ["bash", str(script_path)],
        cwd=str(app_dir),
        capture_output=True,
        text=True
    )

    return {
        "success": result.returncode == 0,
        "stdout": result.stdout,
        "stderr": result.stderr
    }
```

## Uninstallation Flow

When user clicks "Uninstall" button:

```python
def uninstall_app(app_path):
    """Uninstall a TARS app"""
    app_dir = Path(app_path)
    manifest_path = app_dir / "app.json"

    # Read manifest
    with open(manifest_path) as f:
        manifest = json.load(f)

    # Get uninstall script
    uninstall_script = manifest.get("uninstall_script", "uninstall.sh")
    script_path = app_dir / uninstall_script

    if not script_path.exists():
        raise FileNotFoundError(f"Uninstall script not found: {script_path}")

    # Run uninstallation
    result = subprocess.run(
        ["bash", str(script_path)],
        cwd=str(app_dir),
        capture_output=True,
        text=True
    )

    return {
        "success": result.returncode == 0,
        "stdout": result.stdout,
        "stderr": result.stderr
    }
```

## Dashboard UI (Gradio Example)

```python
import gradio as gr
from pathlib import Path

def get_app_status(app_path):
    """Check if app is installed"""
    return (Path(app_path) / "venv").exists()

def create_app_tab():
    """Create app management tab in dashboard"""

    # Discover apps
    apps = discover_apps()

    with gr.Tab("Apps"):
        for app in apps:
            manifest = app["manifest"]

            with gr.Row():
                gr.Markdown(f"### {manifest['name']}")
                gr.Markdown(manifest.get("description", ""))

            with gr.Row():
                gr.Markdown(f"**Version:** {manifest.get('version', 'unknown')}")
                status = "Installed" if app["installed"] else "Not Installed"
                gr.Markdown(f"**Status:** {status}")

            with gr.Row():
                install_btn = gr.Button(
                    "Install",
                    visible=not app["installed"]
                )
                uninstall_btn = gr.Button(
                    "Uninstall",
                    visible=app["installed"]
                )
                output = gr.Textbox(
                    label="Output",
                    lines=5,
                    max_lines=10
                )

            # Install handler
            install_btn.click(
                fn=lambda path=app["path"]: install_app(path),
                outputs=output
            )

            # Uninstall handler
            uninstall_btn.click(
                fn=lambda path=app["path"]: uninstall_app(path),
                outputs=output
            )

            gr.Markdown("---")

# Add to dashboard
with gr.Blocks() as dashboard:
    create_app_tab()

dashboard.launch()
```

## Recommended Directory Structure

```
/home/mac/
├── tars-daemon/              # Main daemon
│   ├── tars_daemon.py
│   ├── dashboard.py          # Gradio dashboard with app management
│   └── app_manager.py        # App discovery and management
│
└── tars-apps/                # Apps directory
    ├── tars-conversation-app/
    │   ├── app.json          # Manifest
    │   ├── install.sh        # Install script
    │   ├── uninstall.sh      # Uninstall script
    │   └── ...
    │
    └── another-app/
        ├── app.json
        └── ...
```

## Environment Variables

Apps should auto-detect deployment:

```python
# In app configuration
def get_grpc_address():
    """Auto-detect if running on Pi or remotely"""
    # Check if on Raspberry Pi
    try:
        with open("/proc/cpuinfo") as f:
            if "Raspberry Pi" in f.read():
                return "localhost:50051"  # Local daemon
    except:
        pass

    # Remote connection
    return os.getenv("RPI_GRPC", "100.84.133.74:50051")
```

## Installation Validation

The daemon should validate before installation:

```python
def validate_app(app_path):
    """Validate app before installation"""
    app_dir = Path(app_path)
    errors = []

    # Check manifest exists
    manifest_path = app_dir / "app.json"
    if not manifest_path.exists():
        errors.append("Missing app.json manifest")
        return errors

    # Read manifest
    with open(manifest_path) as f:
        manifest = json.load(f)

    # Check required fields
    required = ["name", "version", "install_script"]
    for field in required:
        if field not in manifest:
            errors.append(f"Missing required field: {field}")

    # Check scripts exist
    install_script = app_dir / manifest.get("install_script", "install.sh")
    if not install_script.exists():
        errors.append(f"Install script not found: {install_script}")

    # Check Python version
    if "dependencies" in manifest:
        py_version = manifest["dependencies"].get("python", "")
        if py_version:
            # Validate version string format
            import re
            if not re.match(r">=?\d+\.\d+", py_version):
                errors.append(f"Invalid Python version: {py_version}")

    return errors
```

## Running Apps

After installation, provide run buttons:

```python
def run_app(app_path, mode="robot"):
    """Run an installed app"""
    app_dir = Path(app_path)
    manifest_path = app_dir / "app.json"

    with open(manifest_path) as f:
        manifest = json.load(f)

    # Get command for mode
    modes = manifest.get("modes", [])
    command = None

    for m in modes:
        if m["name"] == mode:
            command = m["command"]
            break

    if not command:
        # Fallback to main
        command = f"python {manifest['main']}"

    # Activate venv and run
    venv_python = app_dir / "venv" / "bin" / "python"

    subprocess.Popen(
        [str(venv_python)] + command.split()[1:],
        cwd=str(app_dir)
    )
```

## Security Considerations

1. **Script Validation** - Verify scripts don't contain malicious commands
2. **Sandboxing** - Consider running installations in containers
3. **User Permissions** - Require confirmation before installation
4. **API Keys** - Warn users to configure API keys before running

## Example Dashboard Integration

```python
# In tars-daemon/dashboard.py

import gradio as gr
from app_manager import discover_apps, install_app, uninstall_app

def create_dashboard():
    with gr.Blocks() as dashboard:
        gr.Markdown("# TARS Daemon Dashboard")

        with gr.Tabs():
            # Hardware tab
            with gr.Tab("Hardware"):
                gr.Markdown("Robot hardware controls...")

            # Apps tab
            with gr.Tab("Apps"):
                apps = discover_apps("/home/mac/tars-apps")

                for app in apps:
                    manifest = app["manifest"]

                    with gr.Accordion(manifest["name"], open=False):
                        gr.Markdown(manifest.get("description", ""))
                        gr.JSON(manifest, label="Manifest")

                        with gr.Row():
                            install_btn = gr.Button(
                                "Install",
                                visible=not app["installed"]
                            )
                            uninstall_btn = gr.Button(
                                "Uninstall",
                                visible=app["installed"]
                            )
                            run_btn = gr.Button(
                                "Run",
                                visible=app["installed"]
                            )

                        output = gr.Textbox(label="Output", lines=10)

                        # Event handlers
                        install_btn.click(
                            fn=lambda p=app["path"]: install_app(p),
                            outputs=output
                        ).then(
                            fn=lambda: gr.update(visible=False),
                            outputs=install_btn
                        ).then(
                            fn=lambda: gr.update(visible=True),
                            outputs=[uninstall_btn, run_btn]
                        )

            # Logs tab
            with gr.Tab("Logs"):
                gr.Markdown("System logs...")

    return dashboard

if __name__ == "__main__":
    dashboard = create_dashboard()
    dashboard.launch(server_name="0.0.0.0", server_port=7860)
```

## Testing Installation

From the Pi:

```bash
# Test install
cd ~/tars-apps/tars-conversation-app
bash install.sh

# Verify
ls -la venv/
source venv/bin/activate
python -c "import pipecat; print('OK')"

# Test uninstall
bash uninstall.sh
```

## Next Steps

1. Implement app discovery in tars-daemon
2. Add Apps tab to dashboard
3. Create app_manager.py module
4. Test with tars-conversation-app
5. Document for other developers
