// Simple Next.js server for WebRTC setup
// The frontend connects directly to the FastAPI server on port 7860
// No WebSocket proxy needed - WebRTC handles communication directly

const { createServer } = require('http')
const { parse } = require('url')
const next = require('next')

const dev = process.env.NODE_ENV !== 'production'
const hostname = 'localhost'
const port = parseInt(process.env.PORT || '3000', 10)

const app = next({ dev, hostname, port })
const handle = app.getRequestHandler()

app.prepare().then(() => {
  const server = createServer(async (req, res) => {
    try {
      const parsedUrl = parse(req.url, true)
      await handle(req, res, parsedUrl)
    } catch (err) {
      console.error('Error occurred handling', req.url, err)
      res.statusCode = 500
      res.end('internal server error')
    }
  })

  server
    .once('error', (err) => {
      console.error(err)
      process.exit(1)
    })
    .listen(port, () => {
      console.log(`> Next.js ready on http://${hostname}:${port}`)
      console.log(`> Frontend connects directly to FastAPI WebRTC server at ${process.env.NEXT_PUBLIC_PIPECAT_URL || 'http://localhost:7860'}`)
      console.log(`> Make sure to run: python3 pipecat_service.py`)
    })
})

