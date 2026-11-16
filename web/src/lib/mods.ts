// One of a mod's square PNG icons (128, 256 or 512 px).
export interface Icon {
  size: number
  url: string
}

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
  icons: Icon[]
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

// What players and hosts call each target, for the filter and the tags.
export const PLATFORMS = [
  { target: "client_windows", label: "PCVR" },
  { target: "client_android", label: "Quest" },
  { target: "server", label: "Server" },
] as const

// Whether m has a build for any of the targets; true when none are picked.
export const runsOn = (m: Mod, targets: string[]) => !targets.length || targets.some((t) => hasTarget(m, t))

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
    key: "windows", label: "PCVR", className: "border-info text-info", shown: (m) => hasTarget(m, "client_windows"),
    explain: "Has a build for the game on Windows: SteamVR, a Quest over Link, or flycam.",
  },
  {
    key: "server", label: "Server", className: "border-success text-success", shown: (m) => hasTarget(m, "server"),
    explain: "Has a build for game servers.",
  },
  {
    key: "android", label: "Quest", className: "border-chart-7 text-chart-7", shown: (m) => hasTarget(m, "client_android"),
    explain: "Has a build for the standalone Quest headset, not over Link. Nothing installs these yet.",
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

// The URL of mod's smallest icon at least px across, else its largest; undefined when it has none.
export const iconUrl = (m: Mod, px: number) => {
  const icons = (m.icons || []).filter((i) => i && typeof i.url === "string").sort((a, b) => a.size - b.size)
  return (icons.find((i) => i.size >= px) || icons[icons.length - 1])?.url
}

export const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`
