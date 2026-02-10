import type { Metadata } from 'next'
import './globals.css'
import { MetricsProvider } from './lib/MetricsContext'

export const metadata: Metadata = {
  title: 'TARS Omni',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body>
        <MetricsProvider>{children}</MetricsProvider>
      </body>
    </html>
  )
}
