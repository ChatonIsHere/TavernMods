import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { type Mod, text } from "@/lib/mods"
import { cn } from "@/lib/utils"
import { ModBadges, ModByline, ModName } from "./mod-parts"

function ModCard({ mod }: { mod: Mod }) {
  const shot = (mod.screenshots || [])[0]
  return (
    <Card className={cn("gap-3 pt-0 text-base", mod.own && "ring-2 ring-primary")}>
      <div className="grid aspect-video place-items-center border-b bg-muted text-center">
        {shot ? (
          <img loading="lazy" alt="" src={shot} className="size-full object-cover" />
        ) : (
          <span aria-hidden className="p-3 font-heading text-lg font-bold wrap-anywhere text-primary">{text(mod.name)}</span>
        )}
      </div>
      <CardHeader>
        <CardTitle>
          <h2 className="text-lg font-bold wrap-anywhere">
            <ModName mod={mod} />
          </h2>
        </CardTitle>
        <ModByline mod={mod} />
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-3">
        <p className="flex-1">{text(mod.description)}</p>
        <ModBadges mod={mod} />
      </CardContent>
    </Card>
  )
}

export function ModCards({ mods }: { mods: Mod[] }) {
  return (
    <ul className="grid grid-cols-[repeat(auto-fill,minmax(min(100%,18rem),1fr))] gap-4">
      {mods.map((m) => (
        <li key={m.id} className="grid">
          <ModCard mod={m} />
        </li>
      ))}
    </ul>
  )
}
