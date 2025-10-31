import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'TARS Omni - Real-time Voice AI',
  description: 'Real-time transcription and text-to-speech using Speechmatics and ElevenLabs',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}

