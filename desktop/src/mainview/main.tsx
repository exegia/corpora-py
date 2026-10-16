import "./theme-init"
import { Agentation } from "agentation"
import { StrictMode } from "react"
import { Provider } from "jotai"
import { store } from "@/shared/store"
import { createRoot } from "react-dom/client"
import "./index.css"
import App from "./App"

createRoot(document.getElementById("root")!).render(
    <StrictMode>
        <Provider store={store}>
            <App />
            {process.env.NODE_ENV === "development" && (
                <Agentation endpoint={import.meta.env.VITE_AGENTATION_ENDPOINT || "http://127.0.0.1:4747"} />
            )}
        </Provider>
    </StrictMode>
)
