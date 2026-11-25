import { type ComponentProps, type ReactNode, useId, useRef, useState } from "react"
import { CircleAlertIcon, PlusIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { cn } from "@/lib/utils"
import { type Choice, sha256Of } from "./manifest"

export function Hint({ className, ...props }: ComponentProps<"p">) {
  return <p className={cn("text-sm text-muted-foreground", className)} {...props} />
}

// Announced when it changes; empty until there's something to say.
export function Status({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <p role="status" className={cn("min-h-[1.6em] text-sm text-muted-foreground", className)}>
      {children}
    </p>
  )
}

export function Section({ title, hint, children }: { title: string; hint?: ReactNode; children: ReactNode }) {
  const id = useId()
  return (
    <section aria-labelledby={id}>
      <Card className="text-base">
        <CardHeader>
          <CardTitle>
            <h2 id={id} className="text-xl font-bold text-primary">{title}</h2>
          </CardTitle>
          {hint && <Hint className="max-w-prose">{hint}</Hint>}
        </CardHeader>
        <CardContent className="grid gap-4">{children}</CardContent>
      </Card>
    </section>
  )
}

// A nested block inside a section: one build, or one of its libraries.
export function Item({ title, action, children, className }: { title: string; action?: ReactNode; children: ReactNode; className?: string }) {
  const Heading = title.startsWith("Library") ? "h4" : "h3"
  return (
    <div className={cn("grid gap-4 rounded-lg border bg-muted p-3 sm:p-4", className)}>
      <div className="flex min-h-8 items-center justify-between gap-2">
        <Heading className="font-heading text-lg font-bold">{title}</Heading>
        {action}
      </div>
      {children}
    </div>
  )
}

interface FieldProps {
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  mono?: boolean
  list?: string
  className?: string
  onEnter?: () => void
}

export function Field({ label, value, onChange, placeholder, mono, list, className, onEnter }: FieldProps) {
  const id = useId()
  return (
    <div className={cn("grid min-w-0 content-start gap-1.5", className)}>
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type="text"
        autoComplete="off"
        spellCheck={mono ? false : undefined}
        value={value}
        placeholder={placeholder}
        list={list}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onEnter && ((e) => { if (e.key === "Enter") onEnter() })}
        className={cn("h-9 bg-background text-base md:text-base dark:bg-background", mono && "font-mono text-sm md:text-sm")}
      />
    </div>
  )
}

// A text field that suggests from `choices` as you type, searching their value, label and detail. Any text is
// still allowed; the problem list says if it isn't one of them. Once the value is one of the choices, every
// choice shows again, so another can be picked without clearing it.
export function SearchField({ label, value, onChange, choices, placeholder, mono, className }:
  Omit<FieldProps, "list" | "onEnter"> & { choices: Choice[] }) {
  const id = useId()
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const q = value.trim().toLowerCase()
  const shown = (!q || choices.some((c) => c.value === value) ? choices
    : choices.filter((c) => [c.value, c.label, c.detail].some((t) => t?.toLowerCase().includes(q)))).slice(0, 50)
  const expanded = open && shown.length > 0
  const pick = (c: Choice) => { onChange(c.value); setOpen(false) }
  return (
    <div className={cn("relative grid min-w-0 content-start gap-1.5", className)}>
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type="text"
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={expanded}
        aria-controls={`${id}-list`}
        aria-activedescendant={expanded ? `${id}-${Math.min(active, shown.length - 1)}` : undefined}
        autoComplete="off"
        spellCheck={false}
        value={value}
        placeholder={placeholder}
        onChange={(e) => { onChange(e.target.value); setOpen(true); setActive(0) }}
        onFocus={() => { setOpen(true); setActive(0) }}
        onBlur={() => setOpen(false)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown" || e.key === "ArrowUp") {
            e.preventDefault()
            setOpen(true)
            if (shown.length) setActive((i) => (Math.min(i, shown.length - 1) + (e.key === "ArrowDown" ? 1 : shown.length - 1)) % shown.length)
          } else if (e.key === "Enter" && expanded) {
            e.preventDefault()
            pick(shown[Math.min(active, shown.length - 1)])
          } else if (e.key === "Escape") setOpen(false)
        }}
        className={cn("h-9 bg-background text-base md:text-base dark:bg-background", mono && "font-mono text-sm md:text-sm")}
      />
      {expanded && (
        <ul id={`${id}-list`} role="listbox" aria-label={label}
          className="absolute top-full left-0 z-30 mt-1 max-h-72 w-full min-w-72 overflow-auto rounded-lg border bg-popover p-1 text-popover-foreground shadow-lg">
          {shown.map((c, i) => (
            <li key={c.value} id={`${id}-${i}`} role="option" aria-selected={i === Math.min(active, shown.length - 1)}
              onMouseDown={(e) => { e.preventDefault(); pick(c) }}
              onMouseEnter={() => setActive(i)}
              className={cn("flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5",
                i === Math.min(active, shown.length - 1) && "bg-accent text-accent-foreground")}>
              {c.icon && <img src={c.icon} alt="" className="size-6 shrink-0 rounded" loading="lazy" />}
              <span className="min-w-0">
                <span className="block truncate">{c.label || c.value}</span>
                {(c.label && c.label !== c.value || c.detail) && (
                  <span className="block truncate text-xs text-muted-foreground">
                    {[c.label && c.label !== c.value ? c.value : "", c.detail].filter(Boolean).join(" · ")}
                  </span>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function CheckRow({ label, checked, onChange, disabled, note }: {
  label: string
  checked: boolean
  onChange: (on: boolean) => void
  disabled?: boolean
  note?: string
}) {
  const id = useId()
  return (
    <div className="flex min-h-6 items-start gap-2.5 py-0.5">
      <Checkbox id={id} checked={checked} disabled={disabled} onCheckedChange={(v) => onChange(v === true)} className="mt-1" />
      <Label
        htmlFor={id}
        className={cn("block text-base leading-snug font-normal peer-disabled:opacity-100", disabled && "text-muted-foreground")}
      >
        {label}
        {note && <span className="text-sm"> ({note})</span>}
      </Label>
    </div>
  )
}

export function AddButton({ children, ...props }: ComponentProps<typeof Button>) {
  return (
    <Button type="button" variant="outline" className="w-fit" {...props}>
      <PlusIcon aria-hidden />
      {children}
    </Button>
  )
}

export function RemoveButton({ what, onClick }: { what: string; onClick: () => void }) {
  return (
    <Button type="button" variant="destructive" aria-label={`Remove ${what}`} onClick={onClick}>
      Remove
    </Button>
  )
}

// Picks a file and hashes it in the browser; the file never leaves it.
export function HashButton({ what, onHash }: { what: string; onHash: (sha: string) => void }) {
  const input = useRef<HTMLInputElement>(null)
  const [error, setError] = useState("")
  return (
    <div className="grid gap-1">
      <Button type="button" variant="outline" className="w-fit" aria-label={`Hash a file for ${what}`} onClick={() => input.current?.click()}>
        Hash a file
      </Button>
      <input
        ref={input}
        type="file"
        tabIndex={-1}
        aria-hidden
        className="sr-only"
        onChange={async (e) => {
          const file = e.target.files?.[0]
          e.target.value = ""
          if (!file) return
          try {
            onHash(await sha256Of(file))
            setError("")
          } catch {
            setError("Couldn't hash the file here. Use fill-hashes, or a command from SUBMITTING.md.")
          }
        }}
      />
      {error && (
        <p role="alert" className="flex gap-1.5 text-sm text-destructive">
          <CircleAlertIcon aria-hidden className="mt-0.5 size-4 shrink-0" />
          {error}
        </p>
      )}
    </div>
  )
}
