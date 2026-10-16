import "./index.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";

import { App } from "./App";
import { ErrorBoundary, LoadFailed } from "./components/ErrorBoundary";
import { AppProviders } from "./providers";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary fallback={(error) => <LoadFailed error={error} what="MarketMood" />}>
      <AppProviders>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </AppProviders>
    </ErrorBoundary>
  </StrictMode>,
);
