import { useEffect, useState } from "react"

import { Builder } from "./builder/builder"
import { ModlistPage } from "./modlist/modlist"
import { ModList } from "./mods/mod-list"

// One page for the whole site; the part after # picks what it shows. Pages can't rewrite paths, and the mod list is
// baked into index.html, so every route loads that file.
const ROUTES = {
  mods: { title: "Community Mods", Page: ModList },
  modlist: { title: "Server Modlist", Page: ModlistPage },
  builder: { title: "Manifest Builder", Page: Builder },
} as const
type Route = keyof typeof ROUTES

const routeOf = (hash: string): Route => {
  const key = hash.replace(/^#\/?/, "")
  return key in ROUTES ? (key as Route) : "mods"
}

export function App() {
  const [route, setRoute] = useState(() => routeOf(location.hash))
  useEffect(() => {
    const onHash = () => {
      setRoute(routeOf(location.hash))
      window.scrollTo(0, 0)
    }
    addEventListener("hashchange", onHash)
    return () => removeEventListener("hashchange", onHash)
  }, [])
  useEffect(() => { document.title = `${ROUTES[route].title} | The Modding Tavern` }, [route])
  const { Page } = ROUTES[route]
  return <Page />
}
