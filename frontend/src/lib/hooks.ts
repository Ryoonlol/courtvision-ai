import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import type { Meta, WeekKey } from './types'

export interface AsyncState<T> {
  data: T | null
  error: Error | null
  loading: boolean
  reload: () => void
}

/** Run an async loader whenever deps change; stale responses are ignored. */
export function useAsync<T>(loader: () => Promise<T>, deps: unknown[], enabled = true): AsyncState<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const [loading, setLoading] = useState(enabled)
  const [nonce, setNonce] = useState(0)
  const seq = useRef(0)

  useEffect(() => {
    if (!enabled) return
    const id = ++seq.current
    setLoading(true)
    setError(null)
    loader()
      .then((d) => { if (id === seq.current) setData(d) })
      .catch((e: Error) => { if (id === seq.current) setError(e) })
      .finally(() => { if (id === seq.current) setLoading(false) })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce, enabled])

  const reload = useCallback(() => setNonce((n) => n + 1), [])
  return { data, error, loading, reload }
}

export interface AppState {
  meta: Meta | null
  week: WeekKey
  setWeek: (w: WeekKey) => void
  reloadMeta: () => void
}

export const AppContext = createContext<AppState>({
  meta: null, week: 'next', setWeek: () => {}, reloadMeta: () => {},
})

export const useApp = () => useContext(AppContext)

export function useDebounced<T>(value: T, ms = 200): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}
