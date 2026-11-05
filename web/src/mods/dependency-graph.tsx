import { type KeyboardEvent, useLayoutEffect, useRef, useState } from "react"
import { XIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { repoUrl, text } from "@/lib/mods"
import { cn } from "@/lib/utils"
import { closure, type GEdge, type GNode, getGraph, keepSelection, nodeMatches, tick } from "./graph-model"
import { ModBadges, ModByline, OutLink } from "./mod-parts"
import "./graph.css"

const LABEL_PX = 14 // labels draw at this size on screen, whatever the zoom

export function DependencyGraph({ query }: { query: string }) {
  const g = getGraph()
  const svgRef = useRef<SVGSVGElement>(null)
  const viewportRef = useRef<SVGGElement>(null)
  const nodeEls = useRef(new Map<GNode, SVGGElement>())
  const labelEls = useRef(new Map<GNode, SVGTextElement>())
  const edgeEls = useRef(new Map<GEdge, SVGLineElement>())
  const fitRef = useRef<() => void>(() => {})
  const [selected, setSelected] = useState<GNode | null>(g.selected)
  const [hover, setHover] = useState<GNode | null>(null)
  const [focused, setFocused] = useState<GNode | null>(null)

  const select = (n: GNode | null) => {
    keepSelection(n)
    setSelected(n)
  }

  // Positions move every frame, so they're written straight to the DOM;
  // React only renders the marks and their highlight classes.
  useLayoutEffect(() => {
    const g = getGraph()
    const svg = svgRef.current!, viewport = viewportRef.current!
    const { nodes, edges } = g

    const draw = () => {
      viewport.setAttribute("transform", `translate(${g.tx},${g.ty}) scale(${g.k})`)
      for (const e of edges) {
        const line = edgeEls.current.get(e)
        if (!line) continue
        const dx = e.to.x - e.from.x, dy = e.to.y - e.from.y, d = Math.hypot(dx, dy) || 1
        line.setAttribute("x1", String(e.from.x + (dx / d) * e.from.r))
        line.setAttribute("y1", String(e.from.y + (dy / d) * e.from.r))
        line.setAttribute("x2", String(e.to.x - (dx / d) * (e.to.r + 2)))
        line.setAttribute("y2", String(e.to.y - (dy / d) * (e.to.r + 2)))
      }
      const size = LABEL_PX / g.k
      for (const n of nodes) {
        nodeEls.current.get(n)?.setAttribute("transform", `translate(${n.x},${n.y})`)
        const label = labelEls.current.get(n)
        if (label) {
          label.setAttribute("font-size", String(size))
          label.setAttribute("stroke-width", String(size / 4))
          label.setAttribute("y", String(n.r + size + 2))
        }
      }
    }

    let alpha = 0, frame = 0
    const step = () => {
      tick(g, alpha)
      draw()
      alpha *= 0.97
      frame = alpha > 0.005 ? requestAnimationFrame(step) : 0
    }
    const heat = (to: number) => {
      if (matchMedia("(prefers-reduced-motion: reduce)").matches) return
      alpha = Math.max(alpha, to)
      if (!frame) frame = requestAnimationFrame(step)
    }

    const fit = () => {
      const w = svg.clientWidth, h = svg.clientHeight
      if (!w || h <= 0) return
      let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
      for (const n of nodes) {
        x0 = Math.min(x0, n.x - n.r - 60); x1 = Math.max(x1, n.x + n.r + 60)
        y0 = Math.min(y0, n.y - n.r - 12); y1 = Math.max(y1, n.y + n.r + 28)
      }
      g.k = Math.max(0.25, Math.min(1.6, w / (x1 - x0), h / (y1 - y0)))
      g.tx = w / 2 - ((x0 + x1) / 2) * g.k
      g.ty = h / 2 - ((y0 + y1) / 2) * g.k
      g.fitted = true
      g.viewMoved = false
      draw()
    }
    fitRef.current = fit

    const nodeAt = (target: EventTarget | null) => {
      const el = (target as Element | null)?.closest?.(".node")
      return el ? nodes.find((n) => nodeEls.current.get(n) === el) ?? null : null
    }
    const local = (p: { x: number; y: number }) => {
      const box = svg.getBoundingClientRect()
      return [p.x - box.left, p.y - box.top]
    }
    const toWorld = (ev: PointerEvent) => {
      const [x, y] = local({ x: ev.clientX, y: ev.clientY })
      return [(x - g.tx) / g.k, (y - g.ty) / g.k]
    }
    // Zoom to `next`, keeping the world point under (sx, sy) on screen still.
    const zoomAt = (next: number, sx: number, sy: number, from = { k: g.k, tx: g.tx, ty: g.ty }) => {
      next = Math.max(0.25, Math.min(3, next))
      g.tx = sx - ((sx - from.tx) * next) / from.k
      g.ty = sy - ((sy - from.ty) * next) / from.k
      g.k = next
      g.viewMoved = true
      draw()
    }

    // Drag a mod to move it, drag the background to pan, wheel or pinch to zoom.
    const pointers = new Map<number, { x: number; y: number }>()
    let drag: { n: GNode | null; sx: number; sy: number; tx: number; ty: number; moved: boolean } | null = null
    let pinch: { d: number; mx: number; my: number; from: { k: number; tx: number; ty: number } } | null = null
    const down = (ev: PointerEvent) => {
      if (ev.button !== 0) return
      pointers.set(ev.pointerId, { x: ev.clientX, y: ev.clientY })
      svg.setPointerCapture(ev.pointerId)
      if (pointers.size === 2) {
        // A second finger turns the gesture into a pinch.
        if (drag?.n) drag.n.fixed = false
        drag = null
        const [a, b] = [...pointers.values()]
        const [mx, my] = local({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 })
        pinch = { d: Math.hypot(a.x - b.x, a.y - b.y) || 1, mx, my, from: { k: g.k, tx: g.tx, ty: g.ty } }
        return
      }
      const n = nodeAt(ev.target)
      drag = { n, sx: ev.clientX, sy: ev.clientY, tx: g.tx, ty: g.ty, moved: false }
      if (n) n.fixed = true
      else svg.dataset.panning = ""
    }
    const move = (ev: PointerEvent) => {
      if (pointers.has(ev.pointerId)) pointers.set(ev.pointerId, { x: ev.clientX, y: ev.clientY })
      if (pinch && pointers.size === 2) {
        const [a, b] = [...pointers.values()]
        const [mx, my] = local({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 })
        const scale = Math.hypot(a.x - b.x, a.y - b.y) / pinch.d
        zoomAt(pinch.from.k * scale, pinch.mx, pinch.my, pinch.from)
        g.tx += mx - pinch.mx
        g.ty += my - pinch.my
        draw()
        return
      }
      if (!drag) return
      if (!drag.moved && Math.hypot(ev.clientX - drag.sx, ev.clientY - drag.sy) <= 3) return
      drag.moved = true
      if (drag.n) {
        [drag.n.x, drag.n.y] = toWorld(ev)
        draw()
        heat(0.3)
      } else {
        g.tx = drag.tx + ev.clientX - drag.sx
        g.ty = drag.ty + ev.clientY - drag.sy
        g.viewMoved = true
        draw()
      }
    }
    const release = (ev: PointerEvent) => {
      pointers.delete(ev.pointerId)
      if (pointers.size < 2) pinch = null
      if (!drag) return
      if (drag.n) drag.n.fixed = false
      if (!drag.moved) {
        const n = drag.n && drag.n !== g.selected ? drag.n : null
        g.selected = n
        setSelected(n)
      }
      delete svg.dataset.panning
      drag = null
    }
    const wheel = (ev: WheelEvent) => {
      ev.preventDefault()
      const [sx, sy] = local({ x: ev.clientX, y: ev.clientY })
      zoomAt(g.k * Math.exp(-ev.deltaY * 0.0015), sx, sy)
    }
    const over = (ev: PointerEvent) => setHover(nodeAt(ev.target))
    const leave = () => setHover(null)

    svg.addEventListener("pointerdown", down)
    svg.addEventListener("pointermove", move)
    svg.addEventListener("pointerup", release)
    svg.addEventListener("pointercancel", release)
    svg.addEventListener("pointerover", over)
    svg.addEventListener("pointerleave", leave)
    svg.addEventListener("wheel", wheel, { passive: false })
    // Follow the page's size until the reader moves the view themselves.
    const resize = new ResizeObserver(() => { if (g.fitted && !g.viewMoved) fit() })
    resize.observe(svg)
    if (g.fitted) draw()
    else fit()

    return () => {
      cancelAnimationFrame(frame)
      resize.disconnect()
      svg.removeEventListener("pointerdown", down)
      svg.removeEventListener("pointermove", move)
      svg.removeEventListener("pointerup", release)
      svg.removeEventListener("pointercancel", release)
      svg.removeEventListener("pointerover", over)
      svg.removeEventListener("pointerleave", leave)
      svg.removeEventListener("wheel", wheel)
    }
  }, [])

  // The focused mod lights up its whole chain: what it needs, and what needs it.
  // With none, searching dims the mods that don't match instead of removing them.
  const focus = hover || focused || selected
  let lit: Set<GNode>
  let hot: (e: GEdge) => boolean = () => false
  if (focus) {
    const up = closure(focus, (n) => n.needs.map((e) => e.to))
    const down = closure(focus, (n) => n.neededBy.map((e) => e.from))
    lit = new Set([focus, ...up, ...down])
    hot = (e) => ((e.from === focus || up.has(e.from)) && up.has(e.to))
      || ((e.to === focus || down.has(e.to)) && down.has(e.from))
  } else {
    lit = new Set(g.nodes.filter((n) => nodeMatches(n, query)))
  }

  const onKeyDown = (ev: KeyboardEvent) => {
    const n = g.nodes.find((x) => nodeEls.current.get(x) === ev.target)
    if (n && (ev.key === "Enter" || ev.key === " ")) { ev.preventDefault(); select(n) }
    else if (ev.key === "Escape") select(null)
  }

  return (
    <div className="tm-graph overflow-hidden rounded-xl border bg-card" onKeyDown={onKeyDown}>
      <div className="relative">
        <svg
          ref={svgRef}
          role="group"
          aria-label="Mods and the mods they need"
          className="block h-[min(72vh,46rem)] min-h-[22rem] w-full"
        >
          <defs>
            {(["arrow", "arrow-hot", "arrow-dim"] as const).map((id) => (
              <marker key={id} id={`tm-${id}`} viewBox="0 0 10 10" refX={10} refY={5} markerWidth={9} markerHeight={9}
                orient="auto" markerUnits="userSpaceOnUse">
                <path d="M0,0 L10,5 L0,10 z" className={cn("arrow", id === "arrow-hot" && "hot", id === "arrow-dim" && "dim")} />
              </marker>
            ))}
          </defs>
          <g ref={viewportRef}>
            <g>
              {g.edges.map((e, i) => {
                const on = hot(e)
                const dim = focus ? !on : !(lit.has(e.from) || lit.has(e.to))
                return (
                  <line
                    key={i}
                    ref={(el) => { if (el) edgeEls.current.set(e, el); return () => { edgeEls.current.delete(e) } }}
                    className={cn("edge", on && "hot", dim && "dim")}
                    markerEnd={`url(#tm-arrow${on ? "-hot" : dim ? "-dim" : ""})`}
                  >
                    <title>{`${e.from.label} needs ${e.to.label} ${e.min} or later`}</title>
                  </line>
                )
              })}
            </g>
            <g>
              {g.nodes.map((n) => (
                <g
                  key={n.id}
                  ref={(el) => { if (el) nodeEls.current.set(n, el); return () => { nodeEls.current.delete(n) } }}
                  className={cn("node", !n.mod && "external", !lit.has(n) && "dim",
                    !!focus && n !== focus && lit.has(n) && "hot", n === selected && "selected")}
                  tabIndex={0}
                  role="button"
                  aria-pressed={n === selected}
                  aria-label={n.mod ? n.label : `${n.label}, not in this index`}
                  onFocus={(ev) => { if (ev.currentTarget.matches(":focus-visible")) setFocused(n) }}
                  onBlur={() => setFocused(null)}
                >
                  <circle className="hit" r={Math.max(n.r, 12)} />
                  <circle className="focus-ring" r={n.r + 4} />
                  <circle className="dot" r={n.r} />
                  <text ref={(el) => { if (el) labelEls.current.set(n, el); return () => { labelEls.current.delete(n) } }}>
                    {n.label}
                  </text>
                </g>
              ))}
            </g>
          </g>
        </svg>
        <div className="absolute top-2 left-2">
          <Button type="button" variant="outline" className="bg-background" onClick={() => fitRef.current()}>
            Fit
          </Button>
        </div>
        {selected && <NodeDetails node={selected} onSelect={select} />}
      </div>
      <p className="border-t px-3 py-2 text-sm text-muted-foreground">
        Arrows point to what a mod needs. Drag a mod to move it, drag the background to pan, scroll or pinch to zoom,
        click a mod for details. With the keyboard, Tab to a mod and press Enter; Escape closes the details.
      </p>
    </div>
  )
}

function NodeList({ title, items, onSelect }: { title: string; items: [GNode, string][]; onSelect: (n: GNode) => void }) {
  if (!items.length) return null
  return (
    <>
      <h3 className="mt-3 text-sm font-semibold">{title}</h3>
      <ul className="mt-1 list-disc pl-5">
        {items.map(([n, min]) => (
          <li key={n.id}>
            <Button type="button" variant="link" className="h-auto min-h-6 p-0 text-base whitespace-normal" onClick={() => onSelect(n)}>
              {n.label}
            </Button>
            {min && <span className="ml-1 font-mono text-sm whitespace-nowrap text-muted-foreground">{min} or later</span>}
          </li>
        ))}
      </ul>
    </>
  )
}

function NodeDetails({ node: n, onSelect }: { node: GNode; onSelect: (n: GNode | null) => void }) {
  return (
    <section
      aria-label="Mod details"
      className="m-2 rounded-lg border bg-background p-3 sm:absolute sm:top-0 sm:right-0 sm:max-h-[calc(100%-1rem)] sm:w-80 sm:max-w-[calc(100%-1rem)] sm:overflow-auto"
    >
      <Button type="button" variant="ghost" size="icon" aria-label="Close details" className="float-right ml-2" onClick={() => onSelect(null)}>
        <XIcon />
      </Button>
      {n.mod ? (
        <>
          <h2 className="text-lg font-bold wrap-anywhere">
            <OutLink href={repoUrl(n.mod)} title="Source on GitHub">{n.label}</OutLink>
          </h2>
          <ModByline mod={n.mod} />
          <ModBadges mod={n.mod} className="mt-2" />
          <p className="mt-2">{text(n.mod.description)}</p>
        </>
      ) : (
        <>
          <h2 className="text-lg font-bold break-all">{n.label}</h2>
          <p className="mt-2">Not in this index. Mods that need it install only once a source that has it is added.</p>
        </>
      )}
      <NodeList title="Needs" items={n.needs.map((e) => [e.to, e.min])} onSelect={onSelect} />
      <NodeList title="Needed by" items={n.neededBy.map((e) => [e.from, ""])} onSelect={onSelect} />
    </section>
  )
}
