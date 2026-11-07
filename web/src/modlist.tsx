import { StrictMode } from "react"
import { createRoot } from "react-dom/client"

import "./index.css"
import { ModlistPage } from "./modlist/modlist"

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ModlistPage />
  </StrictMode>,
)
