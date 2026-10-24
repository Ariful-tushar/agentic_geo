import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useHealth } from '@/api/hooks'

const SLOW_AFTER_MS = 3000

// The free API server sleeps when idle. If /api/health is slow (> 3 s) or fails, say so;
// useHealth keeps asking every 5 s, and when the server answers we reload the page data.
export function WakingBanner() {
  const { data, isPending, isError } = useHealth()
  const [slow, setSlow] = useState(false)
  const wasDown = useRef(false)
  const queryClient = useQueryClient()

  useEffect(() => {
    if (!isPending) return
    const timer = setTimeout(() => setSlow(true), SLOW_AFTER_MS)
    return () => clearTimeout(timer)
  }, [isPending])

  const waking = (isPending && slow) || isError || (data !== undefined && data.status !== 'ok')

  useEffect(() => {
    if (waking) {
      wasDown.current = true
    } else if (wasDown.current && data?.status === 'ok') {
      wasDown.current = false
      void queryClient.invalidateQueries()
    }
  }, [waking, data, queryClient])

  if (!waking) return null
  return (
    <div
      role="status"
      className="border-b border-amber-400/20 bg-amber-500/10 px-4 py-2 text-sm text-amber-200"
    >
      Waking up the demo server, about 1 minute on the free tier.
    </div>
  )
}
