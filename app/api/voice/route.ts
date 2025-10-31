import { NextRequest } from 'next/server'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

// WebRTC endpoints are now handled directly by the FastAPI server
// This route provides info about the WebRTC service
export async function GET(request: NextRequest) {
  const pipcatUrl = process.env.NEXT_PUBLIC_PIPECAT_URL || 'http://localhost:7860'
  return new Response(
    JSON.stringify({
      message: 'Voice endpoint migrated to WebRTC',
      webrtcEndpoint: `${pipcatUrl}/api/offer`,
      note: 'Connect directly to the FastAPI server for WebRTC communication',
    }),
    {
      status: 200,
      headers: {
        'Content-Type': 'application/json',
      },
    }
  )
}

