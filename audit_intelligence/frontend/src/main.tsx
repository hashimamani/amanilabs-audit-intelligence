import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource-variable/inter";
import "./index.css";
import { App } from "./App.tsx";
import { configureAuth } from "./auth/AuthContext";
import { loadConfig } from "./config";

void loadConfig().then(() => {
  configureAuth();
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
});
