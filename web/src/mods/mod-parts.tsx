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

// The mod's name, linked to its source; the index owner's own mods get a star.
export function ModName({ mod }: { mod: Mod }) {
  return (
    <OutLink href={repoUrl(mod)} title="Source on GitHub">
      {mod.own && (
        <>
          <StarIcon aria-hidden className="mr-1 inline size-4 fill-primary align-[-2px] text-primary" />
          <span className="sr-only">From this index's owner: </span>
        </>
      )}
      {text(mod.name)}
    </OutLink>
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
