import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { type Mod, ownerUrl, text } from "@/lib/mods"
import { cn } from "@/lib/utils"
import { ModBadges, ModIcon, ModName, ModStar, OutLink } from "./mod-parts"

// The first two columns, the star and the icon, have no visible heading.
const COLUMNS = [
  ["From this index's owner", "w-6 pr-0"],
  ["Icon", "w-11 pr-0"],
  ["Mod", "w-[16%]"],
  ["Id", "w-[17%]"],
  ["Author", "w-[11%]"],
  ["Latest", "w-24"],
  ["Tags", "w-56"],
  ["Description", ""],
] as const

// Below lg the table scrolls sideways in its own box; from lg up the box
// stops clipping, so the header row can stick to the top of the page.
export function ModTable({ mods }: { mods: Mod[] }) {
  return (
    <div className="lg:[&>[data-slot=table-container]]:overflow-visible">
      <p className="mb-2 text-sm text-muted-foreground lg:hidden">The table scrolls sideways; the cards view fits a narrow screen.</p>
      <Table className="min-w-[68rem] text-base lg:min-w-0">
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            {COLUMNS.map(([label, width], i) => (
              <TableHead key={label} className={cn("sticky top-0 z-10 bg-background text-sm font-semibold", width)}>
                {i < 2 ? <span className="sr-only">{label}</span> : label}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {mods.map((m) => (
            <TableRow key={m.id} className="hover:bg-card">
              <TableCell className="pr-0">
                <ModStar mod={m} />
              </TableCell>
              <TableCell className="pr-0">
                <ModIcon mod={m} size={28} className="block" />
              </TableCell>
              <TableCell className="font-semibold whitespace-normal">
                <ModName mod={m} star={false} />
              </TableCell>
              <TableCell className="font-mono text-sm break-all whitespace-normal text-muted-foreground">{text(m.id)}</TableCell>
              <TableCell className="break-words whitespace-normal">
                <OutLink href={ownerUrl(m)}>{text(m.author)}</OutLink>
              </TableCell>
              <TableCell className="font-mono text-primary">{text(m.latest)}</TableCell>
              <TableCell>
                <ModBadges mod={m} version={false} />
              </TableCell>
              <TableCell className="whitespace-normal">{text(m.description)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
