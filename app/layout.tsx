import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'TARS Omni',
  description: 'Real-time Voice AI powered by Qwen, Speechmatics & ElevenLabs',
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
