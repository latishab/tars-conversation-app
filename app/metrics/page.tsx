'use client'

import { useEffect, useState, useMemo } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import { useMetrics, MetricsDataPoint } from '../lib/MetricsContext'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'

interface StatsData {
  current: number | null
  avg: number
  min: number
  max: number
}

export default function MetricsPage() {
  const { metrics, serviceInfo, clearMetrics } = useMetrics()
  const [isClient, setIsClient] = useState(false)

  // Handle SSR - only render chart on client
  useEffect(() => {
    setIsClient(true)
  }, [])

  // Debug: Log service info when it changes
  useEffect(() => {
    console.log('📊 [MetricsPage] Service info updated:', serviceInfo)
  }, [serviceInfo])

  // Calculate statistics for each metric type (memoized to prevent recalculation on every render)
  const { sttStats, mem0Stats, llmStats, ttsStats, visionStats, totalStats } = useMemo(() => {
    const calculateStats = (key: keyof MetricsDataPoint): StatsData => {
      const values = metrics
        .map((m) => m[key])
        .filter((v): v is number => typeof v === 'number')

      if (values.length === 0) {
        return { current: null, avg: 0, min: 0, max: 0 }
      }

      const current = values[values.length - 1] || null
      const avg = values.reduce((sum, v) => sum + v, 0) / values.length
      const min = Math.min(...values)
      const max = Math.max(...values)

      return { current, avg, min, max }
    }

    return {
      sttStats: calculateStats('stt_ttfb_ms'),
      mem0Stats: calculateStats('mem0_latency_ms'),
      llmStats: calculateStats('llm_ttfb_ms'),
      ttsStats: calculateStats('tts_ttfb_ms'),
      visionStats: calculateStats('vision_latency_ms'),
      totalStats: calculateStats('total_ms'),
    }
  }, [metrics])

  // Transform metrics for Recharts (memoized)
  const chartData = useMemo(() =>
    metrics.map((m) => ({
      turn: m.turn_number,
      STT: m.stt_ttfb_ms || null,
      Memory: m.mem0_latency_ms || null,
      LLM: m.llm_ttfb_ms || null,
      TTS: m.tts_ttfb_ms || null,
      Vision: m.vision_latency_ms || null,
      Total: m.total_ms || null,
    }))
  , [metrics])

  // Get last 20 metrics for table (memoized)
  const recentMetrics = useMemo(() => metrics.slice(-20).reverse(), [metrics])

  const formatMs = (ms: number | null | undefined): string => {
    if (ms == null) return 'N/A'
    return `${ms.toFixed(0)}ms`
  }

  return (
    <main className="min-h-screen p-8 bg-gray-50">
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex justify-between items-center">
          <div>
            <h1 className="text-4xl font-bold text-gray-900">Real-Time Latency Dashboard</h1>
            <p className="text-lg text-gray-600 mt-2">
              TTFB metrics for STT, LLM, and TTS services
            </p>
            {serviceInfo && (
              <div className="flex gap-3 mt-3">
                <Badge variant="secondary" className="text-base px-3 py-1">
                  STT: <span className="font-semibold">{serviceInfo.stt}</span>
                </Badge>
                <Badge variant="secondary" className="text-base px-3 py-1">
                  Memory: <span className="font-semibold">{serviceInfo.mem0}</span>
                </Badge>
                <Badge variant="secondary" className="text-base px-3 py-1">
                  LLM: <span className="font-semibold">{serviceInfo.llm}</span>
                </Badge>
                <Badge variant="secondary" className="text-base px-3 py-1">
                  TTS: <span className="font-semibold">{serviceInfo.tts}</span>
                </Badge>
              </div>
            )}
          </div>
          <div className="flex items-center gap-4">
            <Badge variant="outline" className="text-lg px-4 py-2">
              {metrics.length} turns tracked
            </Badge>
            {metrics.length > 0 && (
              <Button
                variant="destructive"
                onClick={() => {
                  if (confirm(`Clear all ${metrics.length} metrics?\n\nThis will delete all stored metrics data.`)) {
                    clearMetrics()
                  }
                }}
              >
                🗑️ Clear Metrics
              </Button>
            )}
          </div>
        </div>

        {/* Stats Cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4">
          {/* STT Card */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-gray-600">
                STT Latency
              </CardTitle>
              {serviceInfo && (
                <p className="text-xs text-gray-500 mt-1">
                  {serviceInfo.stt}
                </p>
              )}
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold text-blue-600">
                {formatMs(sttStats.current)}
              </div>
              <div className="mt-2 space-y-1 text-xs text-gray-500">
                <div className="flex justify-between">
                  <span>Avg:</span>
                  <span>{formatMs(sttStats.avg)}</span>
                </div>
                <div className="flex justify-between">
                  <span>Min:</span>
                  <span>{formatMs(sttStats.min)}</span>
                </div>
                <div className="flex justify-between">
                  <span>Max:</span>
                  <span>{formatMs(sttStats.max)}</span>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Memory Card */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-gray-600">
                Memory Latency
              </CardTitle>
              {serviceInfo && (
                <p className="text-xs text-gray-500 mt-1">
                  {serviceInfo.mem0}
                </p>
              )}
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold text-indigo-600">
                {formatMs(mem0Stats.current)}
              </div>
              <div className="mt-2 space-y-1 text-xs text-gray-500">
                <div className="flex justify-between">
                  <span>Avg:</span>
                  <span>{formatMs(mem0Stats.avg)}</span>
                </div>
                <div className="flex justify-between">
                  <span>Min:</span>
                  <span>{formatMs(mem0Stats.min)}</span>
                </div>
                <div className="flex justify-between">
                  <span>Max:</span>
                  <span>{formatMs(mem0Stats.max)}</span>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* LLM Card */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-gray-600">
                LLM Latency
              </CardTitle>
              {serviceInfo && (
                <p className="text-xs text-gray-500 mt-1">
                  {serviceInfo.llm}
                </p>
              )}
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold text-purple-600">
                {formatMs(llmStats.current)}
              </div>
              <div className="mt-2 space-y-1 text-xs text-gray-500">
                <div className="flex justify-between">
                  <span>Avg:</span>
                  <span>{formatMs(llmStats.avg)}</span>
                </div>
                <div className="flex justify-between">
                  <span>Min:</span>
                  <span>{formatMs(llmStats.min)}</span>
                </div>
                <div className="flex justify-between">
                  <span>Max:</span>
                  <span>{formatMs(llmStats.max)}</span>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* TTS Card */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-gray-600">
                TTS Latency
              </CardTitle>
              {serviceInfo && (
                <p className="text-xs text-gray-500 mt-1">
                  {serviceInfo.tts}
                </p>
              )}
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold text-green-600">
                {formatMs(ttsStats.current)}
              </div>
              <div className="mt-2 space-y-1 text-xs text-gray-500">
                <div className="flex justify-between">
                  <span>Avg:</span>
                  <span>{formatMs(ttsStats.avg)}</span>
                </div>
                <div className="flex justify-between">
                  <span>Min:</span>
                  <span>{formatMs(ttsStats.min)}</span>
                </div>
                <div className="flex justify-between">
                  <span>Max:</span>
                  <span>{formatMs(ttsStats.max)}</span>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Vision Latency Card */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-gray-600">
                Vision Latency
              </CardTitle>
              <p className="text-xs text-gray-500 mt-1">
                Request → Response
              </p>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold text-pink-600">
                {formatMs(visionStats.current)}
              </div>
              <div className="mt-2 space-y-1 text-xs text-gray-500">
                <div className="flex justify-between">
                  <span>Avg:</span>
                  <span>{formatMs(visionStats.avg)}</span>
                </div>
                <div className="flex justify-between">
                  <span>Min:</span>
                  <span>{formatMs(visionStats.min)}</span>
                </div>
                <div className="flex justify-between">
                  <span>Max:</span>
                  <span>{formatMs(visionStats.max)}</span>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Total Card */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-gray-600">
                Total Latency
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold text-orange-600">
                {formatMs(totalStats.current)}
              </div>
              <div className="mt-2 space-y-1 text-xs text-gray-500">
                <div className="flex justify-between">
                  <span>Avg:</span>
                  <span>{formatMs(totalStats.avg)}</span>
                </div>
                <div className="flex justify-between">
                  <span>Min:</span>
                  <span>{formatMs(totalStats.min)}</span>
                </div>
                <div className="flex justify-between">
                  <span>Max:</span>
                  <span>{formatMs(totalStats.max)}</span>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Line Chart */}
        <Card>
          <CardHeader>
            <CardTitle>Latency Trends</CardTitle>
          </CardHeader>
          <CardContent>
            {!isClient ? (
              <div className="h-96 flex items-center justify-center text-gray-500">
                Loading chart...
              </div>
            ) : metrics.length === 0 ? (
              <div className="h-96 flex items-center justify-center text-gray-500">
                No metrics data yet. Start a voice session to collect metrics.
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={400}>
                <LineChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                  <XAxis
                    dataKey="turn"
                    label={{ value: 'Conversation Turn', position: 'insideBottom', offset: -5 }}
                    stroke="#6b7280"
                  />
                  <YAxis
                    label={{ value: 'Latency (ms)', angle: -90, position: 'insideLeft' }}
                    stroke="#6b7280"
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: '#fff',
                      border: '1px solid #e5e7eb',
                      borderRadius: '0.5rem',
                    }}
                  />
                  <Legend />
                  <Line
                    type="monotone"
                    dataKey="STT"
                    stroke="#3b82f6"
                    strokeWidth={2}
                    dot={{ r: 4 }}
                    connectNulls
                    name="STT"
                  />
                  <Line
                    type="monotone"
                    dataKey="Memory"
                    stroke="#6366f1"
                    strokeWidth={2}
                    dot={{ r: 4 }}
                    connectNulls
                    name="Memory"
                  />
                  <Line
                    type="monotone"
                    dataKey="LLM"
                    stroke="#a855f7"
                    strokeWidth={2}
                    dot={{ r: 4 }}
                    connectNulls
                    name="LLM"
                  />
                  <Line
                    type="monotone"
                    dataKey="TTS"
                    stroke="#22c55e"
                    strokeWidth={2}
                    dot={{ r: 4 }}
                    connectNulls
                    name="TTS"
                  />
                  <Line
                    type="monotone"
                    dataKey="Vision"
                    stroke="#ec4899"
                    strokeWidth={2}
                    dot={{ r: 4 }}
                    connectNulls
                    name="Vision"
                  />
                  <Line
                    type="monotone"
                    dataKey="Total"
                    stroke="#f97316"
                    strokeWidth={2}
                    strokeDasharray="5 5"
                    dot={{ r: 4 }}
                    connectNulls
                    name="Total"
                  />
                </LineChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        {/* Metrics Table */}
        <Card>
          <CardHeader>
            <CardTitle>Recent Metrics (Last 20 Turns)</CardTitle>
          </CardHeader>
          <CardContent>
            {metrics.length === 0 ? (
              <div className="text-center text-gray-500 py-8">
                No metrics data yet. Start a voice session to collect metrics.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="border-b">
                    <tr className="text-left">
                      <th className="pb-2 font-semibold text-gray-700">Turn #</th>
                      <th className="pb-2 font-semibold text-gray-700">Timestamp</th>
                      <th className="pb-2 font-semibold text-blue-600">STT (ms)</th>
                      <th className="pb-2 font-semibold text-indigo-600">Memory (ms)</th>
                      <th className="pb-2 font-semibold text-purple-600">LLM (ms)</th>
                      <th className="pb-2 font-semibold text-green-600">TTS (ms)</th>
                      <th className="pb-2 font-semibold text-pink-600">Vision (ms)</th>
                      <th className="pb-2 font-semibold text-orange-600">Total (ms)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recentMetrics.map((metric, idx) => (
                      <tr key={idx} className="border-b last:border-b-0">
                        <td className="py-2 font-mono">{metric.turn_number}</td>
                        <td className="py-2 text-gray-600">
                          {new Date(metric.timestamp).toLocaleTimeString()}
                        </td>
                        <td className="py-2 font-mono text-blue-600">
                          {formatMs(metric.stt_ttfb_ms)}
                        </td>
                        <td className="py-2 font-mono text-indigo-600">
                          {formatMs(metric.mem0_latency_ms)}
                        </td>
                        <td className="py-2 font-mono text-purple-600">
                          {formatMs(metric.llm_ttfb_ms)}
                        </td>
                        <td className="py-2 font-mono text-green-600">
                          {formatMs(metric.tts_ttfb_ms)}
                        </td>
                        <td className="py-2 font-mono text-pink-600">
                          {formatMs(metric.vision_latency_ms)}
                        </td>
                        <td className="py-2 font-mono text-orange-600 font-semibold">
                          {formatMs(metric.total_ms)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </main>
  )
}
