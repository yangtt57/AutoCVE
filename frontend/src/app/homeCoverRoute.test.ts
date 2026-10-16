import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";

const sourceRoot = resolve(import.meta.dirname, "..");

test("home route renders the cover page instead of the agent audit entry", () => {
  const routesSource = readFileSync(resolve(sourceRoot, "app/routes.tsx"), "utf8");

  assert.match(routesSource, /import HomeCover from ['"]@\/pages\/HomeCover['"]/);
  assert.match(routesSource, /path: '\/', element: <HomeCover \/>/);
  assert.doesNotMatch(routesSource, /path: '\/', element: <AgentAudit \/>/);
});

test("home offers audit creation and retains the one-click CVE entry", () => {
  const homeSource = readFileSync(resolve(sourceRoot, "pages/HomeCover.tsx"), "utf8");
  const oneClickSource = readFileSync(resolve(sourceRoot, "pages/OneClickCVE.tsx"), "utf8");

  assert.match(homeSource, /<CreateAgentTaskDialog/);
  assert.match(homeSource, /\/one-click-cve\?start=1/);
  assert.match(homeSource, /新建审计/);
  assert.match(oneClickSource, /new URLSearchParams\(location\.search\)/);
  assert.match(oneClickSource, /setDialogOpen\(true\)/);
});

test("home cover keeps the app sidebar visible", () => {
  const appSource = readFileSync(resolve(sourceRoot, "app/App.tsx"), "utf8");

  assert.doesNotMatch(appSource, /isHomeCover/);
  assert.match(appSource, /<Sidebar collapsed=\{collapsed\} setCollapsed=\{setCollapsed\} \/>/);
  assert.match(appSource, /collapsed \? "md:ml-\[72px\]" : "md:ml-\[224px\]"/);
});
