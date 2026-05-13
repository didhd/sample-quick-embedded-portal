import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import "./index.css";

// StrictMode double-invokes effects in dev; it would cause two dashboard loads
// in rapid succession against the embed API. Skip it for this SPA.
createRoot(document.getElementById("root")).render(<App />);
