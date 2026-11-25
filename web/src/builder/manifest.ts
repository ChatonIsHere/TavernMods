// The manifest builder's model: its form state, the manifest it makes, and the
// same rules as tools/modindex.py validate (hashes are only checked for shape here).

export const TARGETS = [
  ["client_windows", "Windows client (SteamVR, Quest over Link, flycam)"],
  ["server", "Server"],
  ["client_android", "Android client (standalone Quest; nothing installs it yet)"],
] as const
export const SCENES = [["normal", "Normal"], ["quest", "Quest"], ["tutorial", "Tutorial"]] as const
export const SHA_PLACEHOLDER = "run: python tools/modindex.py fill-hashes"
export const USER_RE = /^[A-Za-z0-9](?:-?[A-Za-z0-9]){0,38}$/
export const REPO_RE = /^[A-Za-z0-9._-]{1,100}$/
const VERSION_RE = /^\d+\.\d+\.\d+$/
const SHA_RE = /^[0-9a-f]{64}$/
const SHOT_RE = /\.(png|jpe?g|webp|gif)$/i
export const ICON_SIZES = [128, 256, 512] as const

// The index this page belongs to: <owner>.github.io/<repo>/ on Pages, else the default.
export const INDEX = (() => {
  const host = location.hostname, first = location.pathname.split("/")[1]
  return host.endsWith(".github.io") && first
    ? { owner: host.split(".")[0], repo: first, branch: "main" }
    : { owner: "ModdingTavern", repo: "TavernMods", branch: "main" }
})()
export const RAW = `https://raw.githubusercontent.com/${INDEX.owner}/${INDEX.repo}/${INDEX.branch}`

export interface Library { name: string; download_url: string; sha256: string; filename: string }
export interface Artifact { targets: string[]; download_url: string; sha256: string; library_dependencies: Library[] }
export interface Dependency { id: string; version: string }
export interface Incompatibility { id: string; note: string; below: string }
export const NOTE_MAX = 300
export const CHANGELOG_MAX = 2000
export interface State {
  owner: string
  repo: string
  version: string
  name: string
  author: string
  description: string
  changelog: string
  parity: boolean
  scenes: string[]
  dependencies: Dependency[]
  incompatible: Incompatibility[]
  icons: Record<number, string>   // size -> link
  screenshots: string[]
  artifacts: Artifact[]
}
// repository.json's "mods": id -> major -> what that major's highest version says.
export interface IndexEntry { versions?: string[]; name?: string; author?: string; icons?: { size: number; url: string }[] }
export type IndexMods = Record<string, Record<string, IndexEntry>>

// One suggestion in a search field: the value it fills in, and how it's shown.
export interface Choice { value: string; label?: string; detail?: string; icon?: string }

export const blankArtifact = (): Artifact => ({ targets: [], download_url: "", sha256: "", library_dependencies: [] })
export const blankLibrary = (): Library => ({ name: "", download_url: "", sha256: "", filename: "" })
export const blankState = (): State => ({
  owner: "", repo: "", version: "", name: "", author: "", description: "", changelog: "",
  parity: true, scenes: [], dependencies: [], incompatible: [], icons: {}, screenshots: [], artifacts: [blankArtifact()],
})

type VKey = number[]
const vkey = (v: string): VKey => v.split(".").map(Number)
const vcmp = (a: VKey, b: VKey) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2]
// Published versions of id, highest first; [] if it isn't in the index.
export const publishedOf = (mods: IndexMods | null, id: string) => Object.values((mods || {})[id] || {})
  .flatMap((e) => e.versions || []).filter((v) => VERSION_RE.test(v)).sort((a, b) => vcmp(vkey(b), vkey(a)))

export const splitId = (id: string) => id.split(/\.(.*)/s)

// The newest major's entry, which says what the mod is called now.
const newest = (mods: IndexMods, id: string) => {
  const majors = Object.keys(mods[id] || {}).filter((m) => /^\d+$/.test(m)).sort((a, b) => Number(b) - Number(a))
  return majors.length ? mods[id][majors[0]] : undefined
}
const smallIcon = (e?: IndexEntry) => (Array.isArray(e?.icons) ? [...e.icons].sort((a, b) => a.size - b.size)[0]?.url : undefined)

// Every published mod but `except`, by name.
export function modChoices(mods: IndexMods | null, except = ""): Choice[] {
  return Object.keys(mods || {}).filter((id) => id.toLowerCase() !== except.toLowerCase()).map((id) => {
    const e = newest(mods!, id), latest = publishedOf(mods, id)[0]
    return { value: id, label: e?.name || id, detail: [e?.author && `by ${e.author}`, latest && `latest ${latest}`].filter(Boolean).join(", "), icon: smallIcon(e) }
  }).sort((a, b) => a.label.localeCompare(b.label, undefined, { sensitivity: "base" }))
}

// A mod's published versions, highest first.
export const versionChoices = (mods: IndexMods | null, id: string): Choice[] =>
  publishedOf(mods, id).map((v, i) => ({ value: v, detail: i === 0 ? "latest" : undefined }))

export function ownerChoices(mods: IndexMods | null): Choice[] {
  const count: Record<string, number> = {}
  for (const id of Object.keys(mods || {})) count[splitId(id)[0]] = (count[splitId(id)[0]] || 0) + 1
  return Object.keys(count).sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" }))
    .map((o) => ({ value: o, detail: `${count[o]} mod${count[o] === 1 ? "" : "s"}` }))
}

export const repoChoices = (mods: IndexMods | null, owner: string): Choice[] =>
  Object.keys(mods || {}).filter((id) => !owner || splitId(id)[0].toLowerCase() === owner.toLowerCase())
    .map((id) => ({ value: splitId(id)[1], label: splitId(id)[1], detail: newest(mods!, id)?.name, icon: smallIcon(newest(mods!, id)) }))
    .sort((a, b) => a.value.localeCompare(b.value, undefined, { sensitivity: "base" }))
export const modId = (s: State) => `${s.owner}.${s.repo}`
export const basename = (url: string) => {
  try { return decodeURIComponent(new URL(url).pathname.split("/").pop() || "") } catch { return "" }
}

export function manifest(s: State) {
  const m: Record<string, unknown> = {
    manifest_version: 2, id: modId(s), name: s.name || modId(s), version: s.version,
    author: s.author || s.owner, description: s.description,
  }
  if (s.changelog.trim()) m.changelog = s.changelog
  const icons = ICON_SIZES.filter((n) => s.icons[n]).map((n) => ({ size: n, url: s.icons[n] }))
  if (icons.length) m.icons = icons
  const shots = s.screenshots.filter(Boolean)
  if (shots.length) m.screenshots = shots
  m.parity_required = s.parity
  if (s.scenes.length) m.scenes = [...s.scenes]
  m.dependencies = Object.fromEntries(s.dependencies.filter((d) => d.id).map((d) => [d.id, d.version]))
  const incompatible = s.incompatible.filter((x) => x.id)
  if (incompatible.length) m.incompatible_with = Object.fromEntries(incompatible.map((x) =>
    [x.id, x.below ? { note: x.note, below: x.below } : { note: x.note }]))
  m.artifacts = s.artifacts.map((a) => ({
    targets: [...a.targets],
    download_url: a.download_url,
    sha256: a.sha256 || SHA_PLACEHOLDER,
    library_dependencies: a.library_dependencies.map((l) => ({
      name: l.name, download_url: l.download_url, sha256: l.sha256 || SHA_PLACEHOLDER,
      filename: l.filename || basename(l.download_url),
    })),
  }))
  return m as { artifacts: Artifact[]; icons?: { size: number; url: string }[]; screenshots?: string[] } & Record<string, unknown>
}

export const manifestText = (s: State) => JSON.stringify(manifest(s), null, 2) + "\n"
export const fileName = (s: State) => `${s.version || "<version>"}.json`
export const submissionPath = (s: State) => `submissions/${s.owner || "<owner>"}.${s.repo || "<repo>"}/${fileName(s)}`

function isHttps(url: string) { try { return new URL(url).protocol === "https:" } catch { return false } }
function ownedBy(s: State, url: string) {
  try {
    const u = new URL(url), parts = u.pathname.split("/").filter(Boolean)
    // A tagged release asset, as modindex.py's _release_asset: nothing a fork or a later release can change.
    return u.protocol === "https:" && u.hostname.toLowerCase() === "github.com" && parts.length === 6
      && parts[0].toLowerCase() === s.owner.toLowerCase() && parts[1].toLowerCase() === s.repo.toLowerCase()
      && parts[2] === "releases" && parts[3] === "download"
  } catch { return false }
}
// Mirrors _image_url_error in tools/modindex.py: the mod's own repo, and immutable.
function imageHosted(s: State, url: string) {
  try {
    const u = new URL(url), parts = u.pathname.split("/").filter(Boolean)
    if (u.protocol !== "https:" || parts.length < 3 || parts[0].toLowerCase() !== s.owner.toLowerCase()
      || parts[1].toLowerCase() !== s.repo.toLowerCase()) return false
    const host = u.hostname.toLowerCase()
    return host === "github.com" ? ownedBy(s, url) : host === "raw.githubusercontent.com" && /^[0-9a-f]{40}$/.test(parts[2])
  } catch { return false }
}
const versionProblem = (v: string, what: string) => !VERSION_RE.test(v) ? `${what} must be MAJOR.MINOR.PATCH, like 1.0.0.`
  : v.split(".").some((x) => Number(x) > 2147483647) ? `${what} has a number over 2147483647.` : null
const bareName = (n: string) => n && n !== "." && n !== ".." && !/[/\\:]/.test(n)

// Mirrors version_floor_error in tools/modindex.py: each major is its own line.
function versionFloorProblem(pub: string[], v: string) {
  const k = vkey(v), show = (x: VKey) => x.join(".")
  if (pub.includes(v)) return `${v} is already published. Bump the version.`
  const inMajor = pub.map(vkey).filter((p) => p[0] === k[0])
  if (inMajor.length && vcmp(k, inMajor[0]) < 0)
    return `${v} is lower than ${show(inMajor[0])}, the highest published ${k[0]}.x. Use a higher version.`
  if (!inMajor.length && pub.length && k[0] < vkey(pub[0])[0])
    return `${v} would start major ${k[0]}, below the newest published version ${pub[0]}. Use a higher version.`
  return null
}

export function problems(s: State, mods: IndexMods | null) {
  const m = manifest(s), out: string[] = [], hashless: string[] = []
  if (!USER_RE.test(s.owner)) out.push("The owner must be a GitHub user or organisation name.")
  if (!REPO_RE.test(s.repo) || s.repo === "." || s.repo === "..") out.push("The repo must be a GitHub repository name.")
  const vp = versionProblem(s.version, "The version")
  if (vp) out.push(vp)
  else if (USER_RE.test(s.owner) && REPO_RE.test(s.repo)) {
    const fp = versionFloorProblem(publishedOf(mods, modId(s)), s.version)
    if (fp) out.push(fp)
  }
  for (const d of s.dependencies) {
    if (!d.id) continue
    const [u, r] = splitId(d.id)
    if (!r || !USER_RE.test(u) || !REPO_RE.test(r)) out.push(`Dependency "${d.id}" isn't an owner.repo id.`)
    else if (d.id === modId(s)) out.push("A mod can't depend on itself.")
    const p = versionProblem(d.version, `Dependency ${d.id}'s minimum version`)
    if (p) out.push(p)
  }
  if (s.changelog.length > CHANGELOG_MAX) out.push(`The changelog is over ${CHANGELOG_MAX} characters.`)
  // Mirrors incompatibility_errors in tools/modindex.py.
  const deps = new Set(s.dependencies.map((d) => d.id.toLowerCase()))
  for (const x of s.incompatible) {
    if (!x.id) continue
    const [u, r] = splitId(x.id)
    if (!r || !USER_RE.test(u) || !REPO_RE.test(r)) out.push(`"${x.id}" under "Doesn't work with" isn't an owner.repo id.`)
    else if (x.id.toLowerCase() === modId(s).toLowerCase()) out.push("A mod can't be listed as not working with itself.")
    else if (mods && !(x.id in mods)) out.push(`${x.id} isn't in this repository (ids are case-sensitive), so it can't be listed as not working with this mod.`)
    if (deps.has(x.id.toLowerCase())) out.push(`${x.id} is a dependency, so it can't also be listed as not working with this mod.`)
    if (!x.note.trim()) out.push(`Say why ${x.id || "the mod"} doesn't work with this one.`)
    else if (x.note.length > NOTE_MAX) out.push(`The note for ${x.id} is over ${NOTE_MAX} characters.`)
    const p = x.below && versionProblem(x.below, `The first version of ${x.id} that works`)
    if (p) out.push(p)
  }
  if (s.scenes.length === SCENES.length) out.push("All scenes are ticked: untick them all instead, which means the same.")
  const claimed: Record<string, number> = {}
  m.artifacts.forEach((a, i) => {
    const n = `Build ${i + 1}`
    if (!a.targets.length) out.push(`${n} has no target ticked.`)
    for (const t of a.targets) {
      if (t in claimed) out.push(`${n} and build ${claimed[t] + 1} both target ${t}. Each target can have only one build.`)
      else claimed[t] = i
    }
    if (!a.download_url) out.push(`${n} needs its release asset link.`)
    else if (!ownedBy(s, a.download_url)) out.push(`${n}'s link must be a release asset: github.com/${s.owner || "owner"}/${s.repo || "repo"}/releases/download/<tag>/<file>.`)
    if (a.sha256 === SHA_PLACEHOLDER) hashless.push(n)
    else if (!SHA_RE.test(a.sha256)) out.push(`${n}'s SHA-256 must be 64 lowercase hex characters.`)
    a.library_dependencies.forEach((l, j) => {
      const ln = `${n}, library ${j + 1}`
      if (!l.name) out.push(`${ln} needs a name.`)
      if (!isHttps(l.download_url)) out.push(`${ln} needs an https:// download link.`)
      if (!bareName(l.filename)) out.push(`${ln}'s file name must be a plain file name.`)
      if (l.sha256 === SHA_PLACEHOLDER) hashless.push(ln)
      else if (!SHA_RE.test(l.sha256)) out.push(`${ln}'s SHA-256 must be 64 lowercase hex characters.`)
    })
  })
  ;(m.icons || []).forEach(({ size, url }) => {
    if (!imageHosted(s, url) || !/\.png$/i.test(new URL(url).pathname))
      out.push(`The ${size} px icon must be a .png release asset of your repo, or a raw.githubusercontent.com link to it pinned to a commit.`)
  })
  ;(m.screenshots || []).forEach((u, i) => {
    if (!isHttps(u) || !SHOT_RE.test(new URL(u).pathname)) out.push(`Screenshot ${i + 1} must be an https:// .png, .jpg, .webp or .gif link.`)
  })
  return { errors: out, hashless }
}

// -- loading -----------------------------------------------------------------------

/* eslint-disable @typescript-eslint/no-explicit-any -- a manifest from the network or a file: anything goes */
export function loadManifest(m: any): State {
  if (!m || typeof m !== "object" || !Array.isArray(m.artifacts)) throw new Error("That isn't a manifest_version 2 manifest.")
  const [owner, repo] = splitId(String(m.id || "."))
  const s: State = {
    owner: owner || "", repo: repo || "", version: m.version || "", name: m.name || "",
    author: m.author || "", description: m.description || "",
    changelog: typeof m.changelog === "string" ? m.changelog : "",
    parity: m.parity_required !== false,
    scenes: Array.isArray(m.scenes) ? m.scenes.filter((x: string) => SCENES.some(([k]) => k === x)) : [],
    dependencies: Object.entries(m.dependencies || {}).map(([id, version]) => ({ id, version: String(version) })),
    incompatible: Object.entries(m.incompatible_with && typeof m.incompatible_with === "object" ? m.incompatible_with : {})
      .map(([id, x]: [string, any]) => ({ id, note: String(x?.note || ""), below: String(x?.below || "") })),
    icons: Object.fromEntries((Array.isArray(m.icons) ? m.icons : [])
      .filter((i: any) => ICON_SIZES.includes(i?.size) && typeof i.url === "string").map((i: any) => [i.size, i.url])),
    screenshots: Array.isArray(m.screenshots) ? m.screenshots.slice(0, 4) : [],
    artifacts: m.artifacts.map((a: any) => ({
      targets: TARGETS.map(([t]) => t as string).filter((t) => (a.targets || []).includes(t)),
      download_url: a.download_url || "", sha256: SHA_RE.test(a.sha256 || "") ? a.sha256 : "",
      library_dependencies: (a.library_dependencies || []).map((l: any) => ({
        name: l.name || "", download_url: l.download_url || "",
        sha256: SHA_RE.test(l.sha256 || "") ? l.sha256 : "", filename: l.filename || "",
      })),
    })),
  }
  if (!s.artifacts.length) s.artifacts = [blankArtifact()]
  return s
}

// -- start from a release ------------------------------------------------------------

const RELEASE_RE = /^https:\/\/github\.com\/([^/]+)\/([^/]+)\/releases\/(?:tag\/([^/?#]+)|download\/([^/]+)\/([^/?#]+))/i
const BUILD_RE = /\.(dll|zip)$/i
const assetSha = (a: any) => (/^sha256:([0-9a-f]{64})$/.exec(a?.digest || "") || [])[1] || ""

async function gh(path: string) {
  const r = await fetch(`https://api.github.com/${path}`, { headers: { Accept: "application/vnd.github+json" } })
  if (r.status === 404) return null
  if (!r.ok) throw new Error(r.status === 403 || r.status === 429 ? "GitHub's hourly limit for this network is used up. Try again later" : `GitHub answered ${r.status}`)
  return r.json()
}

// Reads a release through GitHub's API and returns the form to show (if any) and
// what to tell the author. `reading` is called once the link looks right.
export async function fillFromRelease(link: string, mods: IndexMods | null, reading: () => void): Promise<{ state?: State; status: string }> {
  const match = RELEASE_RE.exec(link)
  if (!match) return { status: "That isn't a GitHub release link. It should end in /releases/tag/<tag> or /releases/download/<tag>/<file>." }
  let [, owner, repo] = match
  const tag = decodeURIComponent(match[3] || match[4]), picked = match[5] && decodeURIComponent(match[5])
  const version = (tag.match(/\d+\.\d+\.\d+/) || [""])[0]
  reading()
  let release, info
  try {
    release = await gh(`repos/${owner}/${repo}/releases/tags/${encodeURIComponent(tag)}`)
    if (!release) return { status: `${owner}/${repo} has no release tagged ${tag}.` }
    info = await gh(`repos/${owner}/${repo}`)
  } catch (e) { return { status: "Couldn't read the release: " + (e as Error).message } }
  if (info) [owner, repo] = info.full_name.split("/") // GitHub's own capitalisation
  const assets: any[] = (release.assets || []).filter((a: any) => BUILD_RE.test(a.name))

  const listed = Object.keys(mods || {}).find((k) => k.toLowerCase() === `${owner}.${repo}`.toLowerCase())
  let base = null
  if (listed) {
    const [o, r] = splitId(listed)
    try { const res = await fetch(`${RAW}/manifests/${o}/${r}/latest.json`, { cache: "no-store" }); if (res.ok) base = await res.json() } catch { /* start fresh */ }
  }
  const used = new Set<any>()
  let s: State
  if (base) {
    try { s = loadManifest(base) } catch (e) { return { status: "Couldn't read the published manifest: " + (e as Error).message } }
    s.changelog = ""    // it described the published version
    // Each build keeps its file name, with the old version swapped for the new one.
    for (const a of s.artifacts) {
      const want = basename(a.download_url).split(base.version).join(version || base.version)
      const asset = assets.find((x) => x.name === want && !used.has(x))
      if (asset) used.add(asset)
      a.download_url = asset ? asset.browser_download_url : ""
      a.sha256 = asset ? assetSha(asset) : ""
    }
    const pick = picked && assets.find((x) => x.name === picked)
    const empty = s.artifacts.find((a) => !a.download_url)
    if (pick && !used.has(pick) && empty) { empty.download_url = pick.browser_download_url; empty.sha256 = assetSha(pick); used.add(pick) }
  } else {
    const chosen = picked ? assets.filter((x) => x.name === picked) : assets.slice(0, TARGETS.length)
    s = {
      ...blankState(), owner, repo, name: repo, description: info?.description || "",
      artifacts: chosen.length ? chosen.map((x) => ({ ...blankArtifact(), download_url: x.browser_download_url, sha256: assetSha(x) })) : [blankArtifact()],
    }
    chosen.forEach((x) => used.add(x))
  }
  s.version = version

  const notes = []
  notes.push(base ? `Started from the published ${base.version}.` : `New mod: ${used.size} build${used.size === 1 ? "" : "s"} from ${tag}; tick each one's targets.`)
  if (!version) notes.push(`The tag ${tag} has no MAJOR.MINOR.PATCH version; enter it below.`)
  const missing = s.artifacts.filter((a) => !a.download_url).length
  if (missing) notes.push(`${missing} build${missing === 1 ? "" : "s"} had no matching file in ${tag}; paste the link and hash it.`)
  const unhashed = s.artifacts.filter((a) => a.download_url && !a.sha256).length
  if (unhashed) notes.push(`GitHub gave no hash for ${unhashed} file${unhashed === 1 ? "" : "s"}; hash it below.`)
  if (base && s.artifacts.some((a) => a.library_dependencies.length)) notes.push("Libraries are kept as published; update them if they changed.")
  return { state: s, status: notes.join(" ") }
}
/* eslint-enable @typescript-eslint/no-explicit-any */

export async function sha256Of(file: File) {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer())
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("")
}
