import { lazy, Suspense } from "react";
import { Route, Routes } from "react-router";

import { Layout } from "./components/Layout";
import { Dashboard } from "./pages/Dashboard";
import { NotFound } from "./pages/NotFound";

const HowItWorks = lazy(() => import("./pages/HowItWorks").then((m) => ({ default: m.HowItWorks })));

export function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route
          path="/how-it-works"
          element={
            <Suspense fallback={<p className="pt-10 text-center text-ink-3">Loading…</p>}>
              <HowItWorks />
            </Suspense>
          }
        />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </Layout>
  );
}
