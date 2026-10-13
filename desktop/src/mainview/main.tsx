import "./theme-init"
import { Agentation } from "agentation"
import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import "./index.css"
import App from "./App"

createRoot(document.getElementById("root")!).render(
    <StrictMode>
        <>
            <App />
            {process.env.NODE_ENV === "development" && <Agentation />}
        </>
    </StrictMode>
)
