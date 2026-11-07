// The server modlist page's model: the index's mods with a server build, the picks, and the
// modlist.json they make. The file is the one TavernLauncher's Mod Manager exports (schema 1):
// TavernLib reads only `mods`, the launcher's import also checks `schema` and shows `repos`.
import { INDEX, publishedOf, RAW, splitId } from "@/builder/manifest"
import type { Mod } from "@/lib/mods"

export const SCHEMA = 1
export const FILE_NAME = "modlist.json"

// repository.json: id -> major -> what that major's latest says, and the replaced mods.
interface Major {
  name?: string
  author?: string
  description?: string
  parity_required?: boolean
  targets?: string[]
  versions?: string[]
}
export interface Repository {
  mods?: Record<string, Record<string, Major>>
  replaced?: Record<string, { by: string; note?: string }>
}

// A mod with a server build, as the list shows it. versions: those with a server build, highest first.
export type ServerMod = Mod & { versions: string[] }
// version "" means the latest, whatever it is when the server starts.
export interface Pick { id: string; version: string }

export async function fetchRepository(): Promise<Repository> {
  const r = await fetch(`${RAW}/repository.json`, { cache: "no-store" })
  if (!r.ok) throw new Error(`the index answered ${r.status}`)
  return r.json()
}

export function serverMods(repo: Repository): ServerMod[] {
  const out: ServerMod[] = []
  for (const [id, majors] of Object.entries(repo.mods || {})) {
    if (repo.replaced?.[id]) continue
    const server = Object.fromEntries(Object.entries(majors).filter(([, m]) => (m.targets || []).includes("server")))
    const versions = publishedOf({ [id]: server }, id)
    if (!versions.length) continue
    const top = server[versions[0].split(".")[0]]
    out.push({
      id, name: top.name || id, author: top.author || splitId(id)[0], description: top.description || "",
      targets: top.targets || [], parity_required: !!top.parity_required, latest: versions[0],
      dependencies: {}, screenshots: [], own: false, versions,
    })
  }
  return out.sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }))
}

// Sorted by id, as the launcher exports them.
export const entries = (picks: Pick[]) =>
  [...picks].sort((a, b) => a.id.localeCompare(b.id)).map((p) => (p.version ? `${p.id}@${p.version}` : p.id))

export const modlistText = (picks: Pick[]) =>
  JSON.stringify({ schema: SCHEMA, repos: [`${INDEX.owner}/${INDEX.repo}`], mods: entries(picks) }, null, 2) + "\n"

// A modlist file back into picks, as the launcher's import reads it: "id" or "id@version" (a bare "id@" is the
// latest), and a mod this index has replaced becomes its replacement at the latest.
export function readModlist(text: string, repo: Repository): { picks: Pick[]; notes: string[] } {
  const data = JSON.parse(text)
  if (data?.schema === undefined) throw new Error("it isn't a modlist (it has no schema)")
  if (data.schema !== SCHEMA) throw new Error(`it's schema ${JSON.stringify(data.schema)}; this page reads schema ${SCHEMA}`)
  if (!Array.isArray(data.mods) || data.mods.some((m: unknown) => typeof m !== "string")) throw new Error("its mods aren't a list of ids")
  const picks = new Map<string, Pick>()
  const notes: string[] = []
  for (const entry of data.mods as string[]) {
    const at = entry.indexOf("@")
    let id = (at < 0 ? entry : entry.slice(0, at)).trim(), version = at < 0 ? "" : entry.slice(at + 1).trim()
    const by = repo.replaced?.[id]?.by
    if (by) { notes.push(`${id} is replaced by ${by}, so that's listed instead, at its latest.`); id = by; version = "" }
    if (id) picks.set(id, { id, version })
  }
  return { picks: [...picks.values()], notes }
}

// What a server would trip over, one line each.
export function problems(picks: Pick[], mods: ServerMod[], repo: Repository | null): string[] {
  if (!repo) return []
  const byId = new Map(mods.map((m) => [m.id, m]))
  return picks.flatMap((p) => {
    const m = byId.get(p.id)
    if (!m) {
      return repo.mods?.[p.id]
        ? [`${p.id} has no server build, so a server leaves it out.`]
        : [`${p.id} isn't in this index. A server only installs it if it also trusts a source that has it.`]
    }
    if (p.version && !m.versions.includes(p.version)) return [`${m.name} ${p.version} isn't published with a server build.`]
    return []
  })
}

// The mods a server installs along with the picks: each one's dependencies, and theirs, from the published
// manifests. id -> the picked or needed mod that first needs it. Mods not in the index are skipped.
const manifestCache = new Map<string, Promise<Record<string, string>>>()
const dependenciesOf = (id: string, version: string) => {
  const [owner, repo] = splitId(id)
  const url = `${RAW}/manifests/${owner}/${repo}/${version || "latest"}.json`
  if (!manifestCache.has(url)) {
    manifestCache.set(url, fetch(url, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((m: { dependencies?: Record<string, string> } | null) => (m?.dependencies && typeof m.dependencies === "object" ? m.dependencies : {}))
      .catch(() => ({})))
  }
  return manifestCache.get(url)!
}

export async function dependencyClosure(picks: Pick[], known: Set<string>): Promise<Map<string, string>> {
  const picked = new Set(picks.map((p) => p.id))
  const needed = new Map<string, string>()
  let wave: Pick[] = picks.filter((p) => known.has(p.id))
  while (wave.length) {
    const next: Pick[] = []
    const lists = await Promise.all(wave.map((p) => dependenciesOf(p.id, p.version)))
    lists.forEach((deps, i) => {
      for (const dep of Object.keys(deps)) {
        if (picked.has(dep) || needed.has(dep)) continue
        needed.set(dep, wave[i].id)
        next.push({ id: dep, version: "" })
      }
    })
    wave = next
  }
  return needed
}
