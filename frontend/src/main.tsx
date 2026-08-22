import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { importCapabilityFromLocation } from "./lib/capability";
import "./index.css";

importCapabilityFromLocation();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
