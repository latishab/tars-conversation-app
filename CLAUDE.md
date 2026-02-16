# TARS Omni

AI brain that connects to Raspberry Pi hardware daemon.

## Pi Access
```
ssh tars-pi  # 100.84.133.74, user: mac, repo: ~/tars-daemon
```

## Install

Pi (from tars-daemon dashboard):
- Apps tab → Install button

Pi (manual):
```bash
ssh tars-pi "cd ~/tars-conversation-app && bash install.sh"
```

See: docs/INSTALLATION_GUIDE.md

## Run

1. Pi: `ssh tars-pi "cd ~/tars && python tars_daemon.py"`
2. Mac: `python tars_bot.py`

---

## Docs

- Installation: docs/INSTALLATION_GUIDE.md
- App Development: docs/DEVELOPING_APPS.md
- Daemon Integration: docs/DAEMON_INTEGRATION.md
- Dashboard Update: docs/DASHBOARD_UPDATE_SUMMARY.md

## Dashboard Install

tars-daemon dashboard now supports app management:
- Apps tab shows all apps in ~/tars-apps/
- Install/Uninstall buttons
- Start/Stop controls
- Auto-discovery via app.json

## Claude Code Guidelines

- No emojis, no [NEW] markers, no "vs" comparisons
- Concise, technical, factual only
- No fluff, benefits sections, or marketing language
- Commits: imperative mood, no emojis
- Comments: minimal, explain "why" not "what"
