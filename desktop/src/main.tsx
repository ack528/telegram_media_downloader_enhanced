import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import "./styles/global.css";

// Keep the native context menu out of the app except inside editable fields.
window.addEventListener("contextmenu", (event) => {
  const target = event.target as HTMLElement;
  if (!target.closest("input, textarea, .selectable, .logview")) event.preventDefault();
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
