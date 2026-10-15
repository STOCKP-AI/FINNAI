// TC-FE-07: check a Lighthouse JSON report against the targets in the test plan.
// Usage: node scripts/lighthouse-check.mjs <report.json> [label]
// Mobile targets: performance >= 85, accessibility >= 95. Best practices and SEO are reported only.
import { appendFileSync, readFileSync } from "node:fs";

const [file, label = "mobile"] = process.argv.slice(2);
if (!file) {
  console.error("Usage: node scripts/lighthouse-check.mjs <report.json> [label]");
  process.exit(2);
}
const report = JSON.parse(readFileSync(file, "utf8"));
const targets = label === "mobile" ? { performance: 85, accessibility: 95 } : {};
const rows = Object.values(report.categories).map((c) => {
  const score = Math.round((c.score ?? 0) * 100);
  const target = targets[c.id];
  const ok = target === undefined || score >= target;
  return { name: c.title, score, target: target ?? "-", ok };
});
const metric = (id) => report.audits[id]?.displayValue ?? "-";
const lines = [
  `### Lighthouse (${label}): ${report.finalDisplayedUrl ?? report.requestedUrl}`,
  "",
  "| Category | Score | Target | Result |",
  "|---|---|---|---|",
  ...rows.map((r) => `| ${r.name} | ${r.score} | ${r.target} | ${r.ok ? "pass" : "**below target**"} |`),
  "",
  `LCP ${metric("largest-contentful-paint")} · TBT ${metric("total-blocking-time")} · CLS ${metric("cumulative-layout-shift")} · FCP ${metric("first-contentful-paint")}`,
  "",
];
console.log(lines.join("\n"));
if (process.env.GITHUB_STEP_SUMMARY) appendFileSync(process.env.GITHUB_STEP_SUMMARY, lines.join("\n") + "\n");
process.exit(rows.every((r) => r.ok) ? 0 : 1);
