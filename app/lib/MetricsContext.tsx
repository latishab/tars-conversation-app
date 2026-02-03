'use client'

import React, { createContext, useContext, useState, useCallback, useEffect } from 'react'

export interface MetricsDataPoint {
  turn_number: number
  timestamp: number
  stt_ttfb_ms?: number
  llm_ttfb_ms?: number
  tts_ttfb_ms?: number
  total_ms?: number
}

export interface ServiceInfo {
  stt: string
  llm: string
  tts: string
}

interface MetricsContextType {
  metrics: MetricsDataPoint[]
  serviceInfo: ServiceInfo | null
  addMetric: (metric: MetricsDataPoint) => void
  setServiceInfo: (info: ServiceInfo) => void
  clearMetrics: () => void
}

const MetricsContext = createContext<MetricsContextType | undefined>(undefined)

const MAX_METRICS = 100 // Keep last 100 turns
const STORAGE_KEY = 'tars-metrics'
const SERVICE_INFO_KEY = 'tars-service-info'

export function MetricsProvider({ children }: { children: React.ReactNode }) {
  const [metrics, setMetrics] = useState<MetricsDataPoint[]>(() => {
    // Initialize from localStorage if available
    if (typeof window !== 'undefined') {
      try {
        const stored = localStorage.getItem(STORAGE_KEY)
        if (stored) {
          return JSON.parse(stored)
        }
      } catch (e) {
        console.error('Failed to load metrics from localStorage:', e)
      }
    }
    return []
  })

  const [serviceInfo, setServiceInfoState] = useState<ServiceInfo | null>(() => {
    // Initialize from localStorage if available
    if (typeof window !== 'undefined') {
      try {
        const stored = localStorage.getItem(SERVICE_INFO_KEY)
        if (stored) {
          return JSON.parse(stored)
        }
      } catch (e) {
        console.error('Failed to load service info from localStorage:', e)
      }
    }
    return null
  })

  // Debounce localStorage writes to prevent rapid updates
  useEffect(() => {
    if (typeof window === 'undefined') return

    const timeoutId = setTimeout(() => {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(metrics))
      } catch (e) {
        console.error('Failed to save metrics to localStorage:', e)
      }
    }, 500) // Wait 500ms after last change before saving

    return () => clearTimeout(timeoutId)
  }, [metrics])

  // Listen for storage changes from other tabs
  useEffect(() => {
    if (typeof window === 'undefined') return

    const handleStorageChange = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY && e.newValue) {
        try {
          const newMetrics = JSON.parse(e.newValue)
          setMetrics(newMetrics)
          console.log('📊 MetricsContext: Synced from other tab')
        } catch (err) {
          console.error('Failed to sync metrics:', err)
        }
      }
    }

    window.addEventListener('storage', handleStorageChange)
    return () => window.removeEventListener('storage', handleStorageChange)
  }, [])

  const addMetric = useCallback((newMetric: MetricsDataPoint) => {
    setMetrics((prev) => {
      // Find existing metric with same turn_number
      const existingIndex = prev.findIndex((m) => m.turn_number === newMetric.turn_number)

      let updated: MetricsDataPoint[]
      if (existingIndex !== -1) {
        // Merge with existing metric (incremental updates)
        updated = [...prev]
        updated[existingIndex] = {
          ...updated[existingIndex],
          ...newMetric,
        }
      } else {
        // Add new metric
        updated = [...prev, newMetric]
      }

      // Keep only last MAX_METRICS
      if (updated.length > MAX_METRICS) {
        updated = updated.slice(updated.length - MAX_METRICS)
      }

      return updated
    })
  }, [])

  const setServiceInfo = useCallback((info: ServiceInfo) => {
    setServiceInfoState(info)
    if (typeof window !== 'undefined') {
      try {
        localStorage.setItem(SERVICE_INFO_KEY, JSON.stringify(info))
      } catch (e) {
        console.error('Failed to save service info to localStorage:', e)
      }
    }
  }, [])

  const clearMetrics = useCallback(() => {
    setMetrics([])
    if (typeof window !== 'undefined') {
      try {
        localStorage.removeItem(STORAGE_KEY)
      } catch (e) {
        console.error('Failed to clear metrics from localStorage:', e)
      }
    }
  }, [])

  return (
    <MetricsContext.Provider value={{ metrics, serviceInfo, addMetric, setServiceInfo, clearMetrics }}>
      {children}
    </MetricsContext.Provider>
  )
}

export function useMetrics() {
  const context = useContext(MetricsContext)
  if (!context) {
    throw new Error('useMetrics must be used within a MetricsProvider')
  }
  return context
}
