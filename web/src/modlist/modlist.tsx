import { useEffect, useId, useMemo, useRef, useState } from "react"
import { CircleAlertIcon, CircleCheckIcon } from "lucide-react"

import { SiteHeader } from "@/components/site-header"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Label } from "@/components/ui/label"
import { TooltipProvider } from "@/components/ui/tooltip"
import { Field, Hint, RemoveButton, Section, Status } from "@/builder/fields"
import { plural } from "@/lib/mods"
import { ModBadges, ModByline } from "@/mods/mod-parts"
import {
  dependencyClosure, entries, FILE_NAME, fetchRepository, modlistText, type Pick, problems, readModlist,
  type Repository, serverMods,
} from "./model"

const CONTAINER = "https://github.com/ModdingTavern/a-township-container"

function savedPicks(): Pick[] {
  try {
    const draft = JSON.parse(localStorage.getItem("modlist-draft") || "null")
    if (Array.isArray(draft)) return draft.filter((p) => typeof p?.id === "string").map((p) => ({ id: p.id, version: String(p.version || "") }))
  } catch { /* no draft, or storage blocked */ }
  return []
}

const download = (text: string) => {
  const a = document.createElement("a")
  a.href = URL.createObjectURL(new Blob([text], { type: "application/json" }))
  a.download = FILE_NAME
  a.click()
  URL.revokeObjectURL(a.href)
}

export function ModlistPage() {
  const [repo, setRepo] = useState<Repository | null>(null)
  const [repoError, setRepoError] = useState("")
  const [picks, setPicks] = useState<Pick[]>(savedPicks)
  const [query, setQuery] = useState("")
  const [needed, setNeeded] = useState<Map<string, string>>(new Map())
  const [listStatus, setListStatus] = useState("")
  const [outStatus, setOutStatus] = useState("")
  const loadFile = useRef<HTMLInputElement>(null)
  const versionId = useId()

  useEffect(() => {
    fetchRepository().then(setRepo).catch((e) => setRepoError(`Couldn't load the mod list: ${(e as Error).message}. Reload to try again.`))
  }, [])
  useEffect(() => { try { localStorage.setItem("modlist-draft", JSON.stringify(picks)) } catch { /* storage blocked */ } }, [picks])
  useEffect(() => {
    let live = true
    dependencyClosure(picks, new Set(Object.keys(repo?.mods || {}))).then((n) => { if (live) setNeeded(n) })
    return () => { live = false }
  }, [picks, repo])

  const mods = useMemo(() => (repo ? serverMods(repo) : []), [repo])
  const byId = useMemo(() => new Map(mods.map((m) => [m.id, m])), [mods])
  const picked = new Map(picks.map((p) => [p.id, p]))
  const nameOf = (id: string) => byId.get(id)?.name || id
  const q = query.trim().toLowerCase()
  const shown = q ? mods.filter((m) => `${m.id} ${m.name} ${m.author} ${m.description}`.toLowerCase().includes(q)) : mods

  const issues = problems(picks, mods, repo)
  const text = modlistText(picks)
  const envValue = entries(picks).join(",")
  // Players joining need these too, at the server's version; the launcher matches them on joining.
  const players = [...picks.map((p) => p.id), ...needed.keys()].map((id) => byId.get(id))
    .filter((m) => m && m.parity_required && m.targets.some((t) => t === "client_windows" || t === "client_android"))
    .map((m) => m!.name)

  const toggle = (id: string, on: boolean) =>
    setPicks((prev) => (on ? [...prev.filter((p) => p.id !== id), { id, version: "" }] : prev.filter((p) => p.id !== id)))
  const setVersion = (id: string, version: string) => setPicks((prev) => prev.map((p) => (p.id === id ? { ...p, version } : p)))
  const copy = async (value: string, what: string) => {
    try { await navigator.clipboard.writeText(value); setOutStatus(`Copied ${what}.`) }
    catch { setOutStatus("Couldn't copy; select the text instead.") }
  }

  return (
    <TooltipProvider>
      <SiteHeader current="modlist" />
      <main className="mx-auto max-w-[80rem] px-4 pt-6 pb-12 sm:px-6">
        <div className="mb-6 border-b pb-5">
          <h1 className="text-3xl font-bold text-primary">Server Modlist</h1>
          <p className="mt-2 max-w-prose">
            Pick the mods a server should run and download its <code className="text-info">{FILE_NAME}</code>. Each time
            the server starts it installs and updates those mods and their dependencies, and turns off any other mod it
            manages. It's the file TavernLauncher's Mod Manager exports, so it imports there too.
          </p>
        </div>

        <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,28rem)]">
          <Section
            title="Mods with a server build"
            hint={<>Tick each mod the server should run; you don't need to tick their dependencies. Latest updates the mod
              whenever the server starts; a version keeps it there.</>}
          >
            <Field label="Search" value={query} onChange={setQuery} placeholder="Mods, authors, ids…" />
            <p className="text-sm text-muted-foreground" aria-live="polite">
              {repo ? `${shown.length} of ${plural(mods.length, "mod")}` : repoError || "Loading the mod list…"}
            </p>
            <ul className="grid gap-3">
              {shown.map((m) => {
                const pick = picked.get(m.id)
                const box = `pick-${m.id}`
                return (
                  <li key={m.id} className="flex flex-wrap items-start gap-x-3 gap-y-2 rounded-lg border bg-muted p-3 sm:p-4">
                    <Checkbox id={box} checked={!!pick} onCheckedChange={(v) => toggle(m.id, v === true)} className="mt-1.5" />
                    <div className="grid min-w-0 flex-[1_1_16rem] gap-1.5">
                      <div className="flex flex-wrap items-baseline gap-x-3">
                        <Label htmlFor={box} className="text-lg font-bold">{m.name}</Label>
                        <code className="text-sm break-all text-muted-foreground">{m.id}</code>
                      </div>
                      <ModByline mod={m} />
                      {m.description && <p>{m.description}</p>}
                      <ModBadges mod={m} />
                    </div>
                    {pick && (
                      <div className="grid gap-1.5">
                        <Label htmlFor={`${versionId}-${m.id}`}>Version</Label>
                        <select
                          id={`${versionId}-${m.id}`}
                          value={pick.version}
                          onChange={(e) => setVersion(m.id, e.target.value)}
                          className="h-9 rounded-lg border border-input bg-background px-2 text-base outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                        >
                          <option value="">Latest ({m.latest})</option>
                          {m.versions.map((v) => <option key={v} value={v}>{v}</option>)}
                        </select>
                      </div>
                    )}
                  </li>
                )
              })}
            </ul>
            {repo && q && !shown.length && <p className="text-muted-foreground">Nothing here matches that.</p>}
          </Section>

          <aside aria-labelledby="out-title" className="lg:sticky lg:top-4">
            <Card className="text-base">
              <CardHeader>
                <CardTitle>
                  <h2 id="out-title" className="text-xl font-bold text-primary">Your modlist</h2>
                </CardTitle>
                <Hint aria-live="polite">
                  {plural(picks.length, "mod")}{needed.size ? `, plus ${needed.size} ${needed.size === 1 ? "dependency" : "dependencies"}` : ""}
                </Hint>
              </CardHeader>
              <CardContent className="grid gap-4">
                {picks.length > 0 && (
                  <ul className="grid gap-2" aria-label="Picked mods">
                    {[...picks].sort((a, b) => nameOf(a.id).localeCompare(nameOf(b.id))).map((p) => (
                      <li key={p.id} className="flex items-center justify-between gap-2">
                        <span className="min-w-0 break-words">
                          {nameOf(p.id)} <span className="text-sm text-muted-foreground">{p.version || "latest"}</span>
                        </span>
                        <RemoveButton what={nameOf(p.id)} onClick={() => toggle(p.id, false)} />
                      </li>
                    ))}
                  </ul>
                )}
                {needed.size > 0 && (
                  <div>
                    <Hint>Installed with them</Hint>
                    <ul className="grid gap-1 text-sm">
                      {[...needed].map(([id, by]) => <li key={id}>{nameOf(id)} <span className="text-muted-foreground">(for {nameOf(by)})</span></li>)}
                    </ul>
                  </div>
                )}
                {players.length > 0 && (
                  <Hint>Players need {players.join(", ")} too, at the server's version. The launcher matches them when they join.</Hint>
                )}
                {issues.length ? (
                  <Alert variant="destructive" role={undefined} className="text-base">
                    <CircleAlertIcon aria-hidden />
                    <AlertTitle aria-live="polite" className="text-base">{plural(issues.length, "thing")} to check</AlertTitle>
                    <ul className="col-start-2 mt-1 grid list-disc gap-1 pl-5 text-sm text-foreground">
                      {issues.map((p) => <li key={p}>{p}</li>)}
                    </ul>
                  </Alert>
                ) : picks.length ? (
                  <Alert role={undefined} className="border-success text-success">
                    <CircleCheckIcon aria-hidden />
                    <AlertTitle aria-live="polite" className="text-base">Ready.</AlertTitle>
                    <AlertDescription className="text-foreground">The server fetches each mod from the index when it starts.</AlertDescription>
                  </Alert>
                ) : (
                  <Hint>Nothing picked yet. An empty modlist turns off every mod the server manages.</Hint>
                )}
                <div className="flex flex-wrap gap-2">
                  <Button type="button" disabled={!picks.length} onClick={() => { download(text); setOutStatus(`Saved ${FILE_NAME}.`) }}>Download</Button>
                  <Button type="button" variant="outline" disabled={!picks.length} onClick={() => copy(text, "the file")}>Copy</Button>
                  <Button type="button" variant="outline" disabled={!repo} onClick={() => loadFile.current?.click()}>Load a modlist…</Button>
                  <Button type="button" variant="outline" disabled={!picks.length} onClick={() => { setPicks([]); setOutStatus("Cleared.") }}>Clear</Button>
                  <input
                    ref={loadFile}
                    type="file"
                    accept=".json,application/json"
                    tabIndex={-1}
                    aria-hidden
                    className="sr-only"
                    onChange={async (e) => {
                      const f = e.target.files?.[0]
                      e.target.value = ""
                      if (!f || !repo) return
                      try {
                        const { picks: loaded, notes } = readModlist(await f.text(), repo)
                        setPicks(loaded)
                        setListStatus([`Loaded ${f.name}.`, ...notes].join(" "))
                      } catch (err) { setListStatus(`Couldn't load ${f.name}: ${(err as Error).message}.`) }
                    }}
                  />
                </div>
                <Status className="min-h-0">{[listStatus, outStatus].filter(Boolean).join(" ")}</Status>

                <div className="grid gap-2">
                  <h3 className="font-heading text-lg font-bold">Where it goes</h3>
                  <ul className="grid list-disc gap-2 pl-5">
                    <li>A server TavernLauncher runs: <strong>Mod Manager → Import Modlist</strong>.</li>
                    <li>
                      A headless server: save it in TavernLib's folder,{" "}
                      <code className="text-sm break-words text-info">%APPDATA%\TheModdingTavern</code> for the account the
                      server runs as, and add <code className="text-sm text-info">/modlist {FILE_NAME}</code> to its launch
                      options.
                    </li>
                    <li>
                      The <a href={CONTAINER} target="_blank" rel="noopener" className="text-primary underline underline-offset-4">Docker image</a>:
                      put it in <code className="text-sm text-info">tavern-config</code>, or set{" "}
                      <code className="text-sm text-info">MODLIST</code> to the line below.
                    </li>
                  </ul>
                  <div className="flex flex-wrap items-center gap-2">
                    <code tabIndex={0} aria-label="MODLIST value" className="min-w-0 flex-1 rounded-lg border bg-background p-2 text-sm break-all">
                      {envValue || "(empty)"}
                    </code>
                    <Button type="button" variant="outline" disabled={!envValue} onClick={() => copy(envValue, "the MODLIST value")}>Copy</Button>
                  </div>
                </div>

                <pre tabIndex={0} aria-label="Modlist JSON" className="max-h-[22rem] overflow-auto rounded-lg border bg-background p-3 text-sm leading-relaxed">
                  {text}
                </pre>
              </CardContent>
            </Card>
          </aside>
        </div>
      </main>
    </TooltipProvider>
  )
}
