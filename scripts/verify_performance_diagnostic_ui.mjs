// Actual compiled dashboard + real disposable API/SQL; no response interception.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const directory = process.env.QTRADES_BROWSER_QA_OUTPUT;
assert(directory, "Explicit task-owned QA output is required");
const ready = JSON.parse(fs.readFileSync(path.join(directory, "server-ready.json"), "utf8"));
const token = fs.readFileSync(path.join(directory, "access-token.txt"), "utf8").trim();
const origin = `http://127.0.0.1:${ready.port}`;
const commandKey = "qtrades-performance-diagnostic-command-v1";
const rejectedKey = "qtrades-performance-diagnostic-last-rejection-v1";
const labelsOnly = process.argv.includes("--labels-only");
const checks = [];
const posts = [];
const errors = [];
let failure = null;
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 1200 } });
const page = await context.newPage();
page.setDefaultTimeout(20000);
page.on("pageerror", error => errors.push(error.message));
page.on("request", request => {
  if (request.method() === "POST" && request.url().startsWith(origin + "/api/paper/diagnostics/"))
    posts.push({ path: new URL(request.url()).pathname, body: request.postData() });
});
const headers = { "x-qa-token": token };
const panel = () => page.getByRole("region", { name: "Performance diagnostic account", exact: true });
async function qa(mode) {
  const response = await page.request.post(origin + "/__qa/mode", { headers, data: { mode } });
  assert.equal(response.status(), 200);
}
async function probe(name) {
  const response = await page.request.get(origin + "/__qa/probe", { headers });
  assert.equal(response.status(), 200);
  const value = await response.json();
  fs.writeFileSync(path.join(directory, `${name}.json`), JSON.stringify(value, null, 2));
  assert.equal(value.tick_error, null);
  assert.equal(value.balance.balanced, true);
  assert.equal(value.baseline_financial_preserved, true);
  return value;
}
async function until(predicate, message, timeout = 15000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (await predicate()) return;
    await new Promise(resolve => setTimeout(resolve, 150));
  }
  throw new Error(message);
}
async function stored() { return page.evaluate(key => localStorage.getItem(key), commandKey); }
async function record(name) {
  // Capture fixed navigation at the top after inspector focus moves the viewport.
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
  await page.screenshot({ path: path.join(directory, `${name}.png`), fullPage: true });
  checks.push(name);
}
async function injectRetainedCommand(action, body) {
  await page.evaluate(({ key, action, body }) => localStorage.setItem(key,
    JSON.stringify({ action, body: JSON.stringify(body) })), { key: commandKey, action, body });
  await page.reload();
  await panel().waitFor();
}

try {
  if (labelsOnly) {
    await page.goto(origin + "/#accounts");
    await panel().waitFor();
    await until(() => panel().getByRole("button", { name: "Create performance account", exact: true }).isEnabled(),
      "Fresh disposable source status must enable the labels-only account");
    assert((await panel().innerText()).includes("Trades stay in shared history, labeled random performance activity."));
    assert((await panel().innerText()).includes("Their returns do not count toward strategy rankings or promotions."));
    assert(!(await panel().innerText()).includes("excluded from strategy research"));
    await panel().getByRole("button", { name: "Create performance account", exact: true }).click();
    await until(async () => (await stored()) === null && (await probe("labels-created")).diagnostics.created,
      "Actual source account creation must reopen for the focused labels check");
    const accountTable = page.getByRole("table", { name: "All paper accounts", exact: true });
    await until(async () => (await accountTable.innerText()).includes("Performance only · shared history"),
      "Normal account row must show the shared-history label");
    await page.locator(".accounts-toolbar").getByRole("button", { name: /^Performance/ }).click();
    await accountTable.getByRole("button", { name: "Performance Diagnostic", exact: true }).click();
    const inspector = page.getByRole("region", { name: "Selected account details", exact: true });
    await inspector.waitFor();
    assert((await inspector.innerText()).includes("Random performance activity in shared history."));
    assert((await inspector.innerText()).includes("Returns do not count toward strategy rankings or promotions."));
    assert((await inspector.innerText()).includes("Use the performance controls below to start or stop test activity."));
    const final = await probe("labels-final");
    assert.equal(final.diagnostic_funding_count, 1);
    assert.equal(final.diagnostic_run_count, 0);
    assert(!posts.some(post => post.path.endsWith("/start")));
    await record("shared-history-performance-labels");
  } else {
  await page.goto(origin + "/#accounts");
  await panel().waitFor();
  await until(() => panel().getByRole("button", { name: "Create performance account", exact: true }).isEnabled(),
    "Fresh actual status must enable account creation");
  const initial = await probe("01-before-create");
  assert.equal(initial.diagnostics.created, false);
  await qa("reject_next_create");
  await panel().getByRole("button", { name: "Create performance account", exact: true }).click();
  await until(async () => (await stored()) !== null, "Unconfirmed creation must retain exact intent");
  await until(() => panel().getByRole("button", { name: "Retry same create request", exact: true }).isEnabled(),
    "Fresh unchanged GET must permit the same creation retry");
  const savedCreate = await stored();
  await page.reload();
  await panel().waitFor();
  assert.equal(await stored(), savedCreate, "Reload must retain the same request bytes");
  await until(() => panel().getByRole("button", { name: "Retry same create request", exact: true }).isEnabled(),
    "Recovered creation retry must become usable");
  await panel().getByRole("button", { name: "Retry same create request", exact: true }).click();
  await until(async () => (await stored()) === null, "Actual creation receipt must confirm the saved intent");
  const created = await probe("02-created");
  assert.equal(created.diagnostic_funding_count, 1);
  assert.equal(created.diagnostics.account.funding, "1000000");
  assert.equal(created.diagnostics.account.purpose, "performance_diagnostic");
  const createPosts = posts.filter(post => post.path.endsWith("/create"));
  assert.equal(createPosts.length, 2);
  assert.equal(createPosts[0].body, createPosts[1].body, "Retry must reuse exact identity and body");
  await record("02-created-fake-million");

  await until(() => page.locator(".accounts-toolbar").getByRole("button", { name: /^Performance/ }).isVisible(),
    "Normal Accounts filter must appear");
  await page.locator(".accounts-toolbar").getByRole("button", { name: /^Performance/ }).click();
  const accountTable = page.getByRole("table", { name: "All paper accounts", exact: true });
  await until(async () => await accountTable.getByRole("row").count() === 2,
    "Performance filter must show just its one retained account");
  assert((await accountTable.innerText()).includes("Performance only"));
  await panel().getByText("Account history and balances changed", { exact: true }).click();
  await panel().getByRole("table", { name: "Selected account history", exact: true }).waitFor();
  assert((await panel().innerText()).includes("performance diagnostic funded"));
  await record("03-normal-account-filter-and-journal");

  // A different client already created the one account: its rejected intent is
  // definitive, while the real account and original funding remain retained.
  await injectRetainedCommand("create", { request_id: "different-client-create-0001" });
  await until(() => panel().getByRole("button", { name: "Retry same create request", exact: true }).isEnabled(),
    "A retained client intent must be inspectable");
  await panel().getByRole("button", { name: "Retry same create request", exact: true }).click();
  await until(async () => (await stored()) === null, "409 must release the known-rejected intent");
  assert.equal((await probe("04-definitive-create-rejection")).diagnostic_funding_count, 1);
  assert.equal(await page.evaluate(key => JSON.parse(localStorage.getItem(key)).status, rejectedKey), 409);
  await record("04-definitive-rejection-existing-account-usable");

  await injectRetainedCommand("start", { request_id: "invalid-old-client-start-0001", seed: -1,
    max_actions: 1000, duration_seconds: 600 });
  await until(() => panel().getByRole("button", { name: "Retry same start request", exact: true }).isEnabled(),
    "Retained invalid old-client settings must reach actual validation");
  await panel().getByRole("button", { name: "Retry same start request", exact: true }).click();
  await until(async () => (await stored()) === null, "422 must release known-rejected settings");
  assert.equal((await probe("05-invalid-settings-rejected")).diagnostic_run_count, 0);
  assert.equal(await page.evaluate(key => JSON.parse(localStorage.getItem(key)).status, rejectedKey), 422);
  await record("05-invalid-settings-rejected");

  await qa("guard_closed");
  await panel().getByRole("button", { name: "Refresh performance status", exact: true }).click();
  await until(async () => !(await panel().getByRole("button", { name: "Start ten-minute performance run", exact: true }).isEnabled()),
    "Closed existing resource guard must disable Start");
  assert.equal((await probe("06-guard-closed")).diagnostics.entries_allowed, false);
  await record("06-guard-start-blocked");
  await qa("healthy");
  await panel().getByRole("button", { name: "Refresh performance status", exact: true }).click();
  await until(() => panel().getByRole("button", { name: "Start ten-minute performance run", exact: true }).isEnabled(),
    "Healthy actual state must permit the finite source-QA run");
  await qa("lost_ack_next_start");
  await panel().getByRole("button", { name: "Start ten-minute performance run", exact: true }).click();
  await until(async () => (await stored()) !== null, "Lost start acknowledgment must retain exact intent");
  await until(async () => (await probe("07-lost-start-ack")).diagnostic_run_count === 1,
    "Lost HTTP response must not roll back the real committed run");
  const savedStart = await stored();
  await page.reload();
  await panel().waitFor();
  assert.equal(await stored(), savedStart, "Lost acknowledgment reload must keep original start settings");
  await record("07-lost-ack-reload-preserves-request");
  await qa("release_ack");
  await panel().getByRole("button", { name: "Refresh performance status", exact: true }).click();
  await until(async () => (await stored()) === null, "Reopened actual run receipt must resolve acknowledgment uncertainty");
  const running = await probe("08-actual-run-reopened");
  assert.equal(running.diagnostic_run_count, 1);
  assert.equal(running.diagnostics.run.request_id, JSON.parse(JSON.parse(savedStart).body).request_id);
  assert.equal(running.diagnostics.run.max_actions, 1000);
  assert.equal(running.diagnostics.run.duration_seconds, 600);
  const successfulStarts = running.writes.filter(post => post.path.endsWith("/start") && post.status === 200);
  assert.equal(successfulStarts.length, 1, "No second run or preferred retry follows the lost acknowledgment");

  await until(async () => Object.keys((await probe("09-wait-active-position")).diagnostics.account.positions).length > 0,
    "Actual diagnostic fills must create owned inventory");
  await qa("stale");
  await panel().getByRole("button", { name: "Refresh performance status", exact: true }).click();
  await until(() => panel().getByRole("button", { name: "Stop new entries and drain", exact: true }).isEnabled(),
    "Stop must remain usable with unavailable paper freshness");
  const held = await probe("10-stale-owned-inventory");
  assert.equal(held.diagnostics.stale, true);
  assert(Object.keys(held.diagnostics.account.positions).length > 0);
  await record("10-stale-stop-still-available");
  await panel().getByRole("button", { name: "Stop new entries and drain", exact: true }).click();
  await until(async () => (await stored()) === null, "Actual stop receipt must be reopened while stale");
  const stopped = await probe("11-stale-stop-retains-inventory");
  assert.equal(stopped.diagnostics.run.status, "draining");
  assert.deepEqual(stopped.diagnostics.account.positions, held.diagnostics.account.positions,
    "Stopping without new market input cannot invent fills or erase holdings");
  await qa("healthy");
  await until(async () => (await probe("12-real-drain-completed")).diagnostics.run.status === "completed",
    "Fresh subsequent books must finish ordinary exits");
  const drained = await probe("13-final-drained");
  assert.equal(Object.keys(drained.diagnostics.account.positions).length, 0);
  assert.equal(Object.keys(drained.diagnostics.account.pending).length, 0);
  assert(drained.diagnostics.run.fills > 0 && drained.diagnostics.run.completed > 0);
  assert.equal(drained.diagnostics.account.funding, "1000000");
  assert.equal(drained.diagnostics.account.replenishments, 0);
  await panel().getByRole("button", { name: "Refresh performance status", exact: true }).click();
  await record("13-completed-real-drain");

  await page.goto(origin + "/#orders");
  await page.getByLabel("Trade account", { exact: false }).selectOption("performance-diagnostic");
  await page.getByRole("table", { name: "Paper trade history", exact: true }).waitFor();
  await until(async () => (await page.getByRole("table", { name: "Paper trade history", exact: true }).innerText()).includes("Performance only"),
    "Normal trade history must show the tagged diagnostic fills");
  await record("14-normal-trade-history-tagged");
  }
  assert.equal(errors.length, 0, "Compiled UI must have no page errors");
} catch (error) {
  failure = { name: error.name, message: error.message, stack: error.stack };
  await page.screenshot({ path: path.join(directory, "failure.png"), fullPage: true }).catch(() => {});
} finally {
  const finalProbe = await probe("browser-final-probe").catch(error => ({ error: error.message }));
  fs.writeFileSync(path.join(directory, "browser-receipt.json"), JSON.stringify({
    passed: failure === null, checks, errors, failure, posts, finalProbe,
    runtime: { browser: browser.version(), playwright: require("playwright/package.json").version },
    loaded_source_sha256: ready.loaded_source_sha256 ?? null,
    compiled_index_sha256: ready.compiled_index_sha256,
    scope: "Actual compiled dashboard and disposable source API/SQL; synthetic market/work observations; no operating/model/capacity proof",
    finite_run_stopped_early: !labelsOnly,
    workflow: labelsOnly ? "Focused shared-history labels only; no workload started" : "Bounded account/run/recovery/drain lifecycle",
  }, null, 2));
  await page.request.post(origin + "/__qa/shutdown", { headers }).catch(() => {});
  await context.close();
  await browser.close();
}
if (failure) throw new Error(failure.message);
console.log(JSON.stringify({ passed: true, checks: checks.length, receipt: path.join(directory, "browser-receipt.json") }));
