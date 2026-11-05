import { type ComponentProps, type ReactNode, useId, useRef, useState } from "react"
import { CircleAlertIcon, PlusIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { cn } from "@/lib/utils"
import { sha256Of } from "./manifest"

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
        Hash a file…
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
