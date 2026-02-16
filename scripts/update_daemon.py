#!/usr/bin/env python3
"""
TARS Daemon Remote Update Script

Updates the TARS daemon on the Raspberry Pi via SSH.
Supports git-based updates, backup, health checks, and rollback.

Usage:
    python scripts/update_daemon.py --check-only
    python scripts/update_daemon.py --method git
    python scripts/update_daemon.py --method git --version v0.2.1
    python scripts/update_daemon.py --rollback /path/to/backup
"""

import argparse
import subprocess
import sys
import json
from datetime import datetime
from pathlib import Path

# SSH configuration
PI_HOST = "tars-pi"
PI_USER = "mac"
DAEMON_DIR = "~/tars-daemon"
BACKUP_DIR = "~/tars-daemon-backups"
SERVICE_NAME = "tars"


def run_ssh(cmd: str, check: bool = True) -> tuple[int, str, str]:
    """Run command on Pi via SSH."""
    ssh_cmd = f'ssh {PI_HOST} "{cmd}"'
    result = subprocess.run(
        ssh_cmd,
        shell=True,
        capture_output=True,
        text=True
    )
    if check and result.returncode != 0:
        print(f"Error: {result.stderr}")
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def get_current_version() -> dict:
    """Get current daemon version info."""
    code, out, err = run_ssh(
        f"cd {DAEMON_DIR} && source venv/bin/activate && "
        "python -c 'from tars_sdk import __version__; import json; "
        "print(json.dumps({\"version\": __version__}))'",
        check=False
    )
    if code == 0:
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            pass

    # Fallback: try git
    code, out, _ = run_ssh(f"cd {DAEMON_DIR} && git describe --tags --always", check=False)
    return {"version": out if code == 0 else "unknown", "git": True}


def get_git_status() -> dict:
    """Get git status on Pi."""
    info = {}

    code, out, _ = run_ssh(f"cd {DAEMON_DIR} && git rev-parse --short HEAD", check=False)
    info["commit"] = out if code == 0 else "unknown"

    code, out, _ = run_ssh(f"cd {DAEMON_DIR} && git branch --show-current", check=False)
    info["branch"] = out if code == 0 else "main"

    code, out, _ = run_ssh(f"cd {DAEMON_DIR} && git status --porcelain", check=False)
    info["dirty"] = bool(out) if code == 0 else False

    code, out, _ = run_ssh(f"cd {DAEMON_DIR} && git describe --tags --always", check=False)
    info["tag"] = out if code == 0 else ""

    return info


def check_daemon_health() -> bool:
    """Check if daemon is running and healthy."""
    code, out, _ = run_ssh(f"systemctl is-active {SERVICE_NAME}", check=False)
    if code == 0 and out == "active":
        return True

    # Try curl health endpoint
    code, out, _ = run_ssh("curl -s http://localhost:8001/api/health", check=False)
    if code == 0 and "running" in out.lower():
        return True

    return False


def stop_daemon() -> bool:
    """Stop the daemon service."""
    print("Stopping daemon...")
    code, _, _ = run_ssh(f"sudo systemctl stop {SERVICE_NAME}", check=False)
    if code != 0:
        code, _, _ = run_ssh("pkill -f tars_daemon.py", check=False)
    return True


def start_daemon() -> bool:
    """Start the daemon service."""
    print("Starting daemon...")
    code, _, err = run_ssh(f"sudo systemctl start {SERVICE_NAME}", check=False)
    if code != 0:
        print(f"Warning: systemctl start failed: {err}")
        # Try direct start
        code, _, _ = run_ssh(
            f"cd {DAEMON_DIR} && source venv/bin/activate && "
            "nohup python tars_daemon.py > /dev/null 2>&1 &",
            check=False
        )
    return code == 0


def create_backup() -> str:
    """Create backup of current installation."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{BACKUP_DIR}/tars-daemon-{timestamp}"

    print(f"Creating backup at {backup_path}...")

    # Create backup directory
    run_ssh(f"mkdir -p {BACKUP_DIR}")

    # Copy current installation
    code, _, err = run_ssh(f"cp -r {DAEMON_DIR} {backup_path}")
    if code != 0:
        print(f"Error creating backup: {err}")
        return ""

    # Remove venv from backup to save space
    run_ssh(f"rm -rf {backup_path}/venv", check=False)

    print(f"Backup created: {backup_path}")
    return backup_path


def restore_backup(backup_path: str) -> bool:
    """Restore from backup."""
    print(f"Restoring from {backup_path}...")

    # Verify backup exists
    code, _, _ = run_ssh(f"test -d {backup_path}", check=False)
    if code != 0:
        print(f"Error: Backup not found at {backup_path}")
        return False

    stop_daemon()

    # Move current to temp
    run_ssh(f"mv {DAEMON_DIR} {DAEMON_DIR}.old", check=False)

    # Restore backup
    code, _, err = run_ssh(f"cp -r {backup_path} {DAEMON_DIR}")
    if code != 0:
        print(f"Error restoring backup: {err}")
        # Try to restore old
        run_ssh(f"mv {DAEMON_DIR}.old {DAEMON_DIR}", check=False)
        return False

    # Recreate venv
    print("Recreating virtual environment...")
    run_ssh(
        f"cd {DAEMON_DIR} && python3 -m venv venv && "
        "source venv/bin/activate && pip install -e .",
        check=False
    )

    # Cleanup
    run_ssh(f"rm -rf {DAEMON_DIR}.old", check=False)

    start_daemon()
    return True


def update_git(version: str = None) -> bool:
    """Update daemon using git."""
    git_info = get_git_status()
    print(f"Current: {git_info['commit']} on {git_info['branch']}")

    if git_info["dirty"]:
        print("Warning: Working directory has uncommitted changes")

    # Create backup
    backup_path = create_backup()
    if not backup_path:
        print("Error: Failed to create backup")
        return False

    stop_daemon()

    # Fetch latest
    print("Fetching updates...")
    code, _, err = run_ssh(f"cd {DAEMON_DIR} && git fetch --all --tags")
    if code != 0:
        print(f"Error fetching: {err}")
        return False

    # Checkout version or pull latest
    if version:
        print(f"Checking out {version}...")
        code, _, err = run_ssh(f"cd {DAEMON_DIR} && git checkout {version}")
    else:
        print("Pulling latest...")
        code, _, err = run_ssh(f"cd {DAEMON_DIR} && git pull --ff-only")

    if code != 0:
        print(f"Error: {err}")
        print("Rolling back...")
        restore_backup(backup_path)
        return False

    # Update dependencies
    print("Updating dependencies...")
    code, _, err = run_ssh(
        f"cd {DAEMON_DIR} && source venv/bin/activate && pip install -e ."
    )
    if code != 0:
        print(f"Error installing: {err}")
        print("Rolling back...")
        restore_backup(backup_path)
        return False

    # Regenerate proto files if needed
    print("Regenerating proto files...")
    run_ssh(
        f"cd {DAEMON_DIR} && source venv/bin/activate && "
        "python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. "
        "--pyi_out=. tars_sdk/proto/tars.proto",
        check=False
    )

    # Start daemon
    start_daemon()

    # Health check
    import time
    print("Waiting for daemon to start...")
    time.sleep(3)

    if check_daemon_health():
        print("Daemon is healthy")
        new_info = get_git_status()
        print(f"Updated to: {new_info['commit']}")
        return True
    else:
        print("Error: Daemon health check failed")
        print("Rolling back...")
        restore_backup(backup_path)
        return False


def list_backups():
    """List available backups."""
    code, out, _ = run_ssh(f"ls -la {BACKUP_DIR}", check=False)
    if code == 0:
        print("Available backups:")
        print(out)
    else:
        print("No backups found")


def main():
    parser = argparse.ArgumentParser(
        description="Update TARS daemon on Raspberry Pi",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --check-only           Show current version
  %(prog)s --method git           Update via git pull
  %(prog)s --version v0.2.1       Checkout specific version
  %(prog)s --rollback ~/backup    Restore from backup
  %(prog)s --list-backups         List available backups
        """
    )

    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Show current version and status only"
    )
    parser.add_argument(
        "--method",
        choices=["git"],
        default="git",
        help="Update method (default: git)"
    )
    parser.add_argument(
        "--version",
        help="Specific version/tag to checkout (e.g., v0.2.1)"
    )
    parser.add_argument(
        "--rollback",
        metavar="PATH",
        help="Restore from backup path"
    )
    parser.add_argument(
        "--list-backups",
        action="store_true",
        help="List available backups"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip confirmation prompts"
    )

    args = parser.parse_args()

    print("=" * 60)
    print("TARS Daemon Update Tool")
    print("=" * 60)

    # Test SSH connection
    code, _, _ = run_ssh("echo ok", check=False)
    if code != 0:
        print(f"Error: Cannot connect to {PI_HOST}")
        print("Check SSH configuration and try again.")
        sys.exit(1)

    print(f"Connected to {PI_HOST}")
    print()

    # Get current status
    version_info = get_current_version()
    git_info = get_git_status()
    healthy = check_daemon_health()

    print(f"Current version: {version_info.get('version', 'unknown')}")
    print(f"Git commit: {git_info['commit']} ({git_info['branch']})")
    print(f"Daemon status: {'healthy' if healthy else 'not running'}")
    print()

    if args.list_backups:
        list_backups()
        sys.exit(0)

    if args.check_only:
        sys.exit(0)

    if args.rollback:
        if not args.force:
            confirm = input(f"Restore from {args.rollback}? [y/N] ")
            if confirm.lower() != "y":
                print("Cancelled")
                sys.exit(0)

        success = restore_backup(args.rollback)
        sys.exit(0 if success else 1)

    # Update
    if not args.force:
        msg = f"Update to {args.version}" if args.version else "Update to latest"
        confirm = input(f"{msg}? [y/N] ")
        if confirm.lower() != "y":
            print("Cancelled")
            sys.exit(0)

    if args.method == "git":
        success = update_git(args.version)
    else:
        print(f"Unknown method: {args.method}")
        sys.exit(1)

    if success:
        print()
        print("=" * 60)
        print("Update completed successfully")
        print("=" * 60)

        # Show new version
        new_version = get_current_version()
        print(f"New version: {new_version.get('version', 'unknown')}")
    else:
        print()
        print("=" * 60)
        print("Update failed - system has been rolled back")
        print("=" * 60)
        sys.exit(1)


if __name__ == "__main__":
    main()
