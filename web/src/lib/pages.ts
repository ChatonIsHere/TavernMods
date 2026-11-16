import { useState } from "react"

export interface Paged<T> {
  items: T[]
  page: number
  pages: number
  setPage: (page: number) => void
  size: number
  total: number
}

// One page of items at a time, back on the first whenever reset changes (a new search, say).
export function usePage<T>(items: T[], size: number, reset: string): Paged<T> {
  const [at, setAt] = useState({ page: 0, reset })
  const pages = Math.max(1, Math.ceil(items.length / size))
  const page = Math.min(at.reset === reset ? at.page : 0, pages - 1)
  return {
    items: items.slice(page * size, (page + 1) * size),
    page,
    pages,
    setPage: (to) => setAt({ page: to, reset }),
    size,
    total: items.length,
  }
}
