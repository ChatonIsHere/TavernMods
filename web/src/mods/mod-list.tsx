import { useId, useState } from "react"

import { Pager } from "@/components/pager"
import { usePage } from "@/lib/pages"
import { SiteHeader } from "@/components/site-header"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { TooltipProvider } from "@/components/ui/tooltip"
import { MODS, PLATFORMS, plural, runsOn } from "@/lib/mods"
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
  const [targets, setTargets] = useState<string[]>([])
  const q = query.trim().toLowerCase()
  const shown = MODS.filter((m) => (!q || `${m.id} ${m.name} ${m.author}`.toLowerCase().includes(q)) && runsOn(m, targets))
  const paged = usePage(shown, view === "table" ? 50 : 24, `${q}|${view}|${targets}`)
  const toggleTarget = (t: string) => setTargets((prev) => (prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]))

  const changeView = (next: string) => {
    setView(next as View)
    try { localStorage.setItem("view", next) } catch { /* storage blocked */ }
  }

  let count = `${shown.length} of ${plural(MODS.length, "mod")}`
  let note = MODS.length === 0 ? "This index has no mods in it yet." : shown.length === 0 ? "No mods match that search and filter." : ""
  if (view === "graph" && MODS.length) {
    const graph = getGraph()
    const lit = graph.nodes.filter((n) => n.mod && nodeMatches(n, q, targets)).length
    count = `${lit} of ${plural(MODS.length, "mod")}, ${plural(graph.edges.length, "dependency link")}`
    note = lit === 0 ? "No mods match that search and filter." : ""
  }

  return (
    <TooltipProvider>
      <SiteHeader current="mods" />
      <Tabs value={view} onValueChange={changeView} className="gap-0">
        <main className="w-full px-4 pt-6 pb-12 sm:px-6">
          <div className="flex flex-wrap items-end gap-x-6 gap-y-4 border-b pb-5">
            <div className="min-w-0 flex-[1_1_24rem]">
              <h1 className="text-3xl font-bold text-primary">Community Mods</h1>
              <p className="mt-2 max-w-prose">
                Players install these from <strong>Mod Manager &gt; Get Mods</strong> in TavernLauncher. Server hosts can{" "}
                <a href="#modlist" className="text-primary underline underline-offset-4">make a modlist</a>, and mod authors
                can <a href="#builder" className="text-primary underline underline-offset-4">build a manifest</a>.
              </p>
            </div>
            <div className="flex w-full flex-wrap items-end gap-3 sm:w-auto">
              <div className="grid w-full gap-1.5 sm:w-72">
                <Label htmlFor={searchId}>Search</Label>
                <Input
                  id={searchId}
                  type="search"
                  autoComplete="off"
                  placeholder="Name, author or id"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  className="h-9 text-base md:text-base"
                />
              </div>
              <div role="group" aria-label="Has a build for" className="flex h-9 items-center gap-1 rounded-lg bg-muted p-[3px]">
                {PLATFORMS.map(({ target, label }) => (
                  <Button
                    key={target}
                    type="button"
                    variant="ghost"
                    aria-pressed={targets.includes(target)}
                    onClick={() => toggleTarget(target)}
                    className="h-full px-3 text-base aria-pressed:bg-primary aria-pressed:text-primary-foreground aria-pressed:hover:bg-primary/80"
                  >
                    {label}
                  </Button>
                ))}
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
            <ModCards mods={paged.items} />
          </TabsContent>
          <TabsContent value="table" className="text-base">
            <ModTable mods={paged.items} />
          </TabsContent>
          <TabsContent value="graph" className="text-base">
            {MODS.length > 0 && <DependencyGraph query={q} targets={targets} />}
          </TabsContent>
          {view !== "graph" && <Pager {...paged} />}
          {note && <p className="py-6 text-muted-foreground">{note}</p>}
        </main>
      </Tabs>
    </TooltipProvider>
  )
}
