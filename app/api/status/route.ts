import { NextResponse } from 'next/server'

export async function GET() {
  try {
    // Check if Pipecat service is running
    const pipecatRunning = await fetch('http://localhost:8765', {
      method: 'GET',
      signal: AbortSignal.timeout(1000),
    }).then(() => true).catch(() => false)

    return NextResponse.json({
      status: 'ok',
      services: {
        nextjs: true,
        pipecat: pipecatRunning,
      },
      timestamp: new Date().toISOString(),
    })
  } catch (error) {
    return NextResponse.json({
      status: 'error',
      message: error instanceof Error ? error.message : 'Unknown error',
    }, { status: 500 })
  }
}

