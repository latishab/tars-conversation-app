# TARS Web UI

Next.js web interface for browser mode.

## Development

```bash
cd web
npm install
npm run dev
```

Open http://localhost:3000

## Build

```bash
npm run build
npm run start
```

## Structure

```
web/
├── app/              # Next.js app router pages
├── lib/              # Utilities
├── components.json   # shadcn/ui config
├── package.json      # Dependencies
└── next.config.js    # Next.js configuration
```

## Backend

The web UI communicates with the Python backend (pipecat_service.py) which must be running:

```bash
# From project root
python pipecat_service.py
```

See parent README for full setup instructions.
