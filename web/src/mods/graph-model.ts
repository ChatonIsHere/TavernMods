import { type Mod, MODS, text } from "@/lib/mods"

export interface GNode {
  id: string
  mod: Mod | null // null: a dependency that isn't in this index
  label: string
  needs: GEdge[]
  neededBy: GEdge[]
  r: number
  x: number
  y: number
  vx: number
  vy: number
  fixed: boolean
}

export interface GEdge {
  from: GNode
  to: GNode
  min: string
}

export interface Graph {
  nodes: GNode[]
  edges: GEdge[]
  // The view, kept here so it survives searching and switching views.
  k: number
  tx: number
  ty: number
  fitted: boolean
  viewMoved: boolean
  selected: GNode | null
}

// A small force layout: every pair repels, each link pulls toward a set
// length, and a weak pull keeps loose mods near the middle.
export function tick(g: Graph, alpha: number) {
  const { nodes, edges } = g
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i], b = nodes[j]
      let dx = b.x - a.x, dy = b.y - a.y, d2 = dx * dx + dy * dy
      if (d2 < 1) { dx = Math.random() - 0.5; dy = Math.random() - 0.5; d2 = 1 }
      const d = Math.sqrt(d2), f = (5000 * alpha) / d2
      a.vx -= (dx / d) * f; a.vy -= (dy / d) * f
      b.vx += (dx / d) * f; b.vy += (dy / d) * f
    }
  }
  for (const e of edges) {
    const dx = e.to.x - e.from.x, dy = e.to.y - e.from.y, d = Math.hypot(dx, dy) || 1
    const f = ((d - 150) / d) * 0.08 * alpha
    e.from.vx += dx * f; e.from.vy += dy * f
    e.to.vx -= dx * f; e.to.vy -= dy * f
  }
  for (const n of nodes) {
    if (n.fixed) { n.vx = n.vy = 0; continue }
    n.vx = (n.vx - n.x * 0.012 * alpha) * 0.6
    n.vy = (n.vy - n.y * 0.012 * alpha) * 0.6
    n.x += n.vx; n.y += n.vy
  }
}

function build(mods: Mod[]): Graph {
  const nodes: GNode[] = []
  const byId = new Map<string, GNode>()
  const add = (id: string, mod: Mod | null, label: string) => {
    const n: GNode = { id, mod, label, needs: [], neededBy: [], r: 0, x: 0, y: 0, vx: 0, vy: 0, fixed: false }
    nodes.push(n)
    byId.set(id, n)
    return n
  }
  for (const m of mods) add(m.id, m, text(m.name))
  const edges: GEdge[] = []
  for (const m of mods) {
    for (const [dep, min] of Object.entries(m.dependencies || {})) {
      const to = byId.get(dep) ?? add(dep, null, dep)
      edges.push({ from: byId.get(m.id)!, to, min: text(min) })
    }
  }
  nodes.forEach((n, i) => {
    n.needs = edges.filter((e) => e.from === n)
    n.neededBy = edges.filter((e) => e.to === n)
    n.r = 7 + 2.2 * Math.sqrt(n.neededBy.length)
    const a = (i / nodes.length) * 2 * Math.PI
    n.x = Math.cos(a) * 160
    n.y = Math.sin(a) * 160
  })
  const g: Graph = { nodes, edges, k: 1, tx: 0, ty: 0, fitted: false, viewMoved: false, selected: null }
  // Settle before the first paint, so the graph opens still.
  for (let alpha = 1; alpha > 0.005; alpha *= 0.985) tick(g, alpha)
  return g
}

// Built once, on first use.
let graph: Graph | null = null
export const getGraph = () => (graph ??= build(MODS))
export const keepSelection = (n: GNode | null) => { getGraph().selected = n }

export const nodeMatches = (n: GNode, query: string) =>
  !query || `${n.id} ${n.label} ${text(n.mod?.author)}`.toLowerCase().includes(query)

// Everything reachable from start by next, start itself excluded.
export function closure(start: GNode, next: (n: GNode) => GNode[]) {
  const seen = new Set<GNode>(), todo = [start]
  while (todo.length) {
    for (const m of next(todo.pop()!)) {
      if (m !== start && !seen.has(m)) { seen.add(m); todo.push(m) }
    }
  }
  return seen
}
