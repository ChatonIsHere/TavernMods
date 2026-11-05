import { useId, useState } from "react"

import { SiteHeader } from "@/components/site-header"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { TooltipProvider } from "@/components/ui/tooltip"
import { MODS, plural } from "@/lib/mods"
import { DependencyGraph } from "./dependency-graph"
import { getGraph, nodeMatches } from "./graph-model"
import { ModCards } from "./mod-cards"
import { ModTable } from "./mod-table"

const VIEWS = [["cards", "Cards"], ["table", "Table"], ["graph", "Graph"]] as const
type View = (typeof VIEWS)[number][0]

const savedView = (): View => {
  try {
    const v = localStorage.getItem("view")
    if (VIEWS.some(([k]) => k === v)) return v as View
  } catch { /* storage blocked */ }
  return "cards"
}

export function ModList() {
  const searchId = useId()
  const [query, setQuery] = useState("")
  const [view, setView] = useState<View>(savedView)
  const q = query.trim().toLowerCase()
  const shown = q ? MODS.filter((m) => `${m.id} ${m.name} ${m.author}`.toLowerCase().includes(q)) : MODS

  const changeView = (next: string) => {
    setView(next as View)
    try { localStorage.setItem("view", next) } catch { /* storage blocked */ }
  }

  let count = `${shown.length} of ${plural(MODS.length, "mod")}`
  let note = MODS.length === 0 ? "This index has no mods in it yet." : shown.length === 0 ? "Nothing here matches that." : ""
  if (view === "graph" && MODS.length) {
    const graph = getGraph()
    const lit = graph.nodes.filter((n) => n.mod && nodeMatches(n, q)).length
    count = `${lit} of ${plural(MODS.length, "mod")}, ${plural(graph.edges.length, "dependency link")}`
    note = lit === 0 ? "Nothing here matches that." : ""
  }

  return (
    <TooltipProvider>
      <SiteHeader current="mods" />
      <Tabs value={view} onValueChange={changeView} className="gap-0">
        <main className="mx-auto w-full max-w-screen-2xl px-4 pt-6 pb-12 sm:px-6">
          <div className="flex flex-wrap items-end gap-x-6 gap-y-4 border-b pb-5">
            <div className="min-w-0 flex-[1_1_24rem]">
              <h1 className="text-3xl font-bold text-primary">Community Mods</h1>
              <p className="mt-2 max-w-prose">
                Install from <strong>Mod Manager → Get Mods</strong> in TavernLauncher. A headless server takes the same
                ids in its <code className="text-info">modlist</code>. Mod authors:{" "}
                <a href="builder.html" className="text-primary underline underline-offset-4">build a manifest</a>.
              </p>
            </div>
            <div className="flex w-full flex-wrap items-end gap-3 sm:w-auto">
              <div className="grid w-full gap-1.5 sm:w-72">
                <Label htmlFor={searchId}>Search</Label>
                <Input
                  id={searchId}
                  type="search"
                  autoComplete="off"
                  placeholder="Mods, authors, ids…"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  className="h-9 text-base md:text-base"
                />
              </div>
              <TabsList aria-label="View" className="h-9 group-data-horizontal/tabs:h-9">
                {VIEWS.map(([key, label]) => (
                  <TabsTrigger key={key} value={key} className="px-3 text-base">
                    {label}
                  </TabsTrigger>
                ))}
              </TabsList>
            </div>
          </div>

          <p className="mt-4 mb-3 text-sm text-muted-foreground" aria-live="polite">{count}</p>
          <TabsContent value="cards" className="text-base">
            <ModCards mods={shown} />
          </TabsContent>
          <TabsContent value="table" className="text-base">
            <ModTable mods={shown} />
          </TabsContent>
          <TabsContent value="graph" className="text-base">
            {MODS.length > 0 && <DependencyGraph query={q} />}
          </TabsContent>
          {note && <p className="py-6 text-muted-foreground">{note}</p>}
        </main>
      </Tabs>
    </TooltipProvider>
  )
}
