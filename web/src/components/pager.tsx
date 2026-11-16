import { Button } from "@/components/ui/button"
import type { Paged } from "@/lib/pages"

// Previous and Next with where you are; nothing when everything fits on one page.
export function Pager<T>({ page, pages, setPage, size, total }: Paged<T>) {
  if (pages < 2) return null
  const go = (to: number) => {
    setPage(to)
    window.scrollTo({ top: 0 })
  }
  const first = page * size + 1
  const last = Math.min(total, (page + 1) * size)
  return (
    <nav aria-label="Pages" className="mt-4 flex flex-wrap items-center gap-3">
      <Button type="button" variant="outline" disabled={page === 0} onClick={() => go(page - 1)}>Previous</Button>
      <p className="text-sm text-muted-foreground" aria-live="polite">
        {first} to {last} of {total}, page {page + 1} of {pages}
      </p>
      <Button type="button" variant="outline" disabled={page === pages - 1} onClick={() => go(page + 1)}>Next</Button>
    </nav>
  )
}
