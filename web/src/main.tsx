import { StrictMode } from "react"
import { createRoot } from "react-dom/client"

import "./index.css"
import { ModList } from "./mods/mod-list"

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ModList />
  </StrictMode>,
)
