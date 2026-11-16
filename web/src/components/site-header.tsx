import { cn } from "@/lib/utils"

const PAGES = [
  { key: "mods", href: "#mods", label: "Mods" },
  { key: "modlist", href: "#modlist", label: "Server modlist" },
  { key: "builder", href: "#builder", label: "Manifest builder" },
] as const

// The bar every page shares: the site's name and a link to each page.
export function SiteHeader({ current }: { current: (typeof PAGES)[number]["key"] }) {
  return (
    <header className="border-b bg-card">
      <nav aria-label="Site" className="flex flex-wrap items-center gap-x-6 gap-y-1 px-4 py-2 sm:px-6">
        <span className="font-heading text-lg font-bold text-primary">The Modding Tavern</span>
        <ul className="flex flex-wrap gap-x-1">
          {PAGES.map((p) => (
            <li key={p.key}>
              <a
                href={p.href}
                aria-current={p.key === current ? "page" : undefined}
                className={cn(
                  "inline-flex min-h-8 items-center rounded-md px-2 underline-offset-4 hover:underline",
                  // Same weight either way, so picking a page doesn't shift its neighbours.
                  p.key === current ? "text-foreground underline decoration-primary decoration-2" : "text-muted-foreground hover:text-foreground",
                )}
              >
                {p.label}
              </a>
            </li>
          ))}
        </ul>
      </nav>
    </header>
  )
}
