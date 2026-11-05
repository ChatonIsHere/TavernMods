// The mod rows `modindex.py site` bakes into index.html as window.MODS.
export interface Mod {
  id: string
  name: string
  author: string
  description: string
  targets: string[]
  parity_required: boolean
  latest: string
  dependencies: Record<string, string>
  screenshots: string[]
  own: boolean
}

declare global {
  interface Window {
    MODS?: Mod[]
  }
}

export const MODS: Mod[] = Array.isArray(window.MODS) ? window.MODS : []

export const text = (s: unknown) => String(s ?? "")

const hasTarget = (m: Mod, t: string) => (m.targets || []).includes(t)

// Parity is only enforced on a mod a server runs that also has a client build.
const parityApplies = (m: Mod) =>
  m.parity_required && hasTarget(m, "server") && (hasTarget(m, "client_windows") || hasTarget(m, "client_android"))

export interface Tag {
  key: string
  label: string
  explain: string
  className: string
}

const TAGS: (Tag & { shown: (m: Mod) => boolean })[] = [
  {
    key: "windows", label: "Windows", className: "border-info text-info", shown: (m) => hasTarget(m, "client_windows"),
    explain: "Has a build for the game on Windows: SteamVR, a Quest over Link, or flycam.",
  },
  {
    key: "server", label: "Server", className: "border-success text-success", shown: (m) => hasTarget(m, "server"),
    explain: "Has a build for game servers.",
  },
  {
    key: "android", label: "Android", className: "border-chart-7 text-chart-7", shown: (m) => hasTarget(m, "client_android"),
    explain: "Has a build for the standalone Quest headset (Android). Nothing installs these yet.",
  },
  {
    key: "parity", label: "Parity", className: "border-destructive text-destructive", shown: parityApplies,
    explain: "You need the server's exact version of this mod to join.",
  },
]

export const tagsOf = (m: Mod): Tag[] => TAGS.filter((t) => t.shown(m))

// The id is a validated GitHub owner.repo; owners can't contain dots.
const ownerOf = (m: Mod) => text(m.id).split(".")[0]
export const repoUrl = (m: Mod) => `https://github.com/${ownerOf(m)}/${text(m.id).slice(ownerOf(m).length + 1)}`
export const ownerUrl = (m: Mod) => `https://github.com/${ownerOf(m)}`

export const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`
