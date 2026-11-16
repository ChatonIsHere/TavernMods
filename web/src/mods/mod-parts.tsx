import type { ComponentProps } from "react"
import { StarIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { type Mod, ownerUrl, repoUrl, tagsOf, text } from "@/lib/mods"
import { cn } from "@/lib/utils"

// Links open in a new tab; every string in them comes from mod authors and React escapes it.
export function OutLink({ className, ...props }: ComponentProps<"a">) {
  return (
    <a
      target="_blank"
      rel="noopener"
      className={cn("underline-offset-4 hover:text-primary hover:underline", className)}
      {...props}
    />
  )
}

// The star on the index owner's own mods; nothing on anyone else's.
export function ModStar({ mod, className }: { mod: Mod; className?: string }) {
  if (!mod.own) return null
  return (
    <>
      <StarIcon aria-hidden className={cn("inline size-4 fill-primary align-[-2px] text-primary", className)} />
      <span className="sr-only">From this index's owner: </span>
    </>
  )
}

// The mod's name, linked to its source, after its star unless star is false.
export function ModName({ mod, star = true }: { mod: Mod; star?: boolean }) {
  return (
    <OutLink href={repoUrl(mod)} title="Source on GitHub">
      {star && <ModStar mod={mod} className="mr-1" />}
      {text(mod.name)}
    </OutLink>
  )
}

// The mod's icon at size px, letting the browser pick the file; nothing when it has none.
export function ModIcon({ mod, size, className }: { mod: Mod; size: number; className?: string }) {
  const icons = (mod.icons || []).filter((i) => i && typeof i.url === "string")
  if (!icons.length) return null
  return (
    <img
      alt=""
      loading="lazy"
      width={size}
      height={size}
      src={icons[0].url}
      srcSet={icons.map((i) => `${i.url} ${i.size}w`).join(", ")}
      sizes={`${size}px`}
      className={cn("shrink-0", className)}
    />
  )
}

export function ModByline({ mod, className }: { mod: Mod; className?: string }) {
  return (
    <p className={cn("text-sm text-muted-foreground", className)}>
      by <OutLink href={ownerUrl(mod)}>{text(mod.author)}</OutLink>
    </p>
  )
}

const badgeClass = "h-auto min-h-6 px-2.5 text-sm"

// The latest version, then a tag per target and for parity, each explained on hover or focus.
export function ModBadges({ mod, version = true, className }: { mod: Mod; version?: boolean; className?: string }) {
  return (
    <ul className={cn("flex flex-wrap gap-1.5", className)} aria-label="Tags">
      {version && (
        <li>
          <Badge variant="outline" className={cn(badgeClass, "border-primary text-primary")}>
            <span className="sr-only">Latest version </span>
            {text(mod.latest)}
          </Badge>
        </li>
      )}
      {tagsOf(mod).map((t) => (
        <li key={t.key}>
          <Tooltip>
            <TooltipTrigger asChild>
              <Badge variant="outline" tabIndex={0} className={cn(badgeClass, "cursor-help", t.className)}>
                {t.label}
              </Badge>
            </TooltipTrigger>
            <TooltipContent className="text-sm">{t.explain}</TooltipContent>
          </Tooltip>
        </li>
      ))}
    </ul>
  )
}
