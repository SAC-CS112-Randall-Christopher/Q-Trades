// Real compiled dashboard; all network requests fulfilled locally with synthetic data.
// No service, database, model, financial mutation or operating acceptance is involved.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { chromium } = require("playwright");

const dist = path.resolve(process.env.QTRADES_UI_DIST || "apps/web/dist");
const directory = process.env.QTRADES_BROWSER_QA_OUTPUT;
const origin = "http://127.0.0.1:58961"; // Intercepted; no listener is opened.
const sha = bytes => crypto.createHash("sha256").update(bytes).digest("hex");
const now = 1791300000;
const account = name => ({
  label: name, version: name === "primary" ? "breakout-v1" : name,
  cash: "100", equity: "100", funding: "100", starting_capital: "100", net_pnl: "0",
  fees: "0", max_drawdown: "0", valuation_fresh: true, closed: 0, wins: 0,
  replenishments: 0, cooldown_until: 0, daily_pause: false, drawdown_pause: false,
  failure_pending: false, entries_paused: false, control_version: 0,
  positions: {}, pending: {}, last_decision: {},
  attempt: { number: 1, started_at: now, outcome: "open" },
});
const catalog = {
  version: "original-account-redesign-v1",
  strategies: Array.from({ length: 8 }, (_, i) => ({
    id: `synthetic-choice-${["one", "two", "three", "four", "five", "six", "seven", "eight"][i]}-v1`,
    label: `Synthetic choice ${i + 1}`, hypothesis: "Synthetic UI fixture only",
    feature_seconds: 300, maximum_hold_seconds: 21600, progress_seconds: 7200,
    limitations: "No strategy effectiveness or financial evidence",
  })),
};

(async () => {
  assert(directory, "An explicit task-owned output directory is required");
  fs.mkdirSync(directory, { recursive: false });
  const assets = {};
  const requests = [];
  const stages = [];
  const errors = [];
  let statusCount = 0;
  let browser;
  let page;
  let failure = null;
  let browserClosed = false;
  let phase = "startup";
  let timer;
  const index = fs.readFileSync(path.join(dist, "index.html"));
  const receipt = {
    evidence_kind: "compiled_dashboard_synthetic_api_regression",
    financial_proof: false, operating_calls: 0, model_calls: 0,
    index_sha256: sha(index), harness_sha256: sha(fs.readFileSync(__filename)),
  };
  try {
    browser = await chromium.launch({ headless: true,
      executablePath: process.env.QTRADES_BROWSER_QA_EXECUTABLE || undefined });
    receipt.runtime = { playwright: require("playwright/package.json").version,
      browser: browser.version() };
    const context = await browser.newContext({ viewport: { width: 1440, height: 1100 },
      serviceWorkers: "block" });
    page = await context.newPage();
    page.setDefaultTimeout(7000);
    page.on("pageerror", error => errors.push(error.message));
    await page.route("**/*", async route => {
      const request = route.request();
      const url = new URL(request.url());
      requests.push({ method: request.method(), path: url.pathname, query: url.search });
      if (url.origin !== origin || request.method() !== "GET") {
        return route.fulfill({ status: 403, body: "Synthetic fixture forbids this request" });
      }
      const json = body => route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify(body) });
      if (url.pathname === "/api/status") {
        statusCount += 1;
        const accounts = Object.fromEntries(["primary", "responsive-v1"].map(name => {
          const value = account(name);
          value.last_decision.BTCUSD = { symbol: "BTCUSD", at: now + statusCount,
            reason: `${name}: synthetic status ${statusCount}`, version: value.version };
          return [name, value];
        }));
        return json({ mode: "paper", runtime_state: "running", paused: false,
          generated_at: new Date((now + statusCount) * 1000).toISOString(),
          storage_error: null, retry_in_seconds: 0,
          capture: { retained: 0, total: 0, evicted: 0, capacity: 100 }, events: [], events_total: 0,
          paper: { enabled: true, running: true, error: null, stale: false, paused: false,
            evidence_kind: "synthetic_qa_continuous", feed_errors: {}, started_at: now,
            next_review: now + 14400, review_count: 0, reviews: [], promotions: 0,
            bars_studied: 0, gaps: 0, accounts, campaigns: [], events: [], features: {},
            repeatability: { won: 0, failed: 0, open: 2, conclusion: "Synthetic UI fixture" },
            journal: { balanced: true, available: true, status: "balanced", checked_at: now,
              revision: statusCount, audit_age_seconds: 0, error: null },
            cost_model: "Synthetic UI fixture", sampling: "Synthetic UI fixture" } });
      }
      if (url.pathname === "/api/paper/strategies") return json(catalog);
      if (url.pathname === "/api/paper/diagnostics") return json({ enabled: true,
        created: false, account_name: "performance-diagnostic", account: null, run: null,
        purpose: "performance_diagnostic", fake_capital: "1000000", entries_allowed: true });
      if (url.pathname === "/api/paper/journal") {
        const name = url.searchParams.get("account");
        const after = url.searchParams.get("after");
        assert(["primary", "responsive-v1"].includes(name), "Exact selected account is required");
        assert.equal(url.searchParams.get("limit"), "100");
        assert(["0", "2"].includes(after), "Only the issued fixed cursor may be used");
        const ids = after === "0" ? [1, 2] : [3];
        return json({ records: ids.map(id => ({ id, at: now + id, kind: "synthetic_history",
          body: { reason: `${name} retained event ${id}` },
          journal: [{ asset: "USD", bucket: "cash", amount: "0" }] })),
          has_more: after === "0", next_after: ids.at(-1) });
      }
      if (url.pathname.startsWith("/api/")) {
        return route.fulfill({ status: 404, contentType: "application/json",
          body: JSON.stringify({ detail: "No synthetic response for this route" }) });
      }
      const file = path.resolve(dist, `.${decodeURIComponent(url.pathname)}`,
        url.pathname === "/" ? "index.html" : "");
      if (!file.startsWith(dist + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
        return route.fulfill({ status: 404, body: "No compiled asset" });
      }
      const bytes = fs.readFileSync(file);
      assets[path.relative(dist, file)] = sha(bytes);
      const contentType = file.endsWith(".js") ? "text/javascript"
        : file.endsWith(".css") ? "text/css" : "text/html";
      return route.fulfill({ status: 200, contentType, body: bytes });
    });

    async function flow() {
      phase = "initial-account";
      await page.goto(`${origin}/#accounts`);
      await page.getByRole("button", { name: "Inspect primary", exact: true }).click();
      const inspector = page.getByRole("region", { name: "Selected account details", exact: true });
      const history = () => inspector.locator("details.campaign-journal");
      const chooser = () => inspector.locator("details.economics-settings");
      async function single() {
        const counts = { history: await history().count(), chooser: await chooser().count(), statusCount };
        stages.push({ phase, ...counts });
        assert.equal(counts.history, 1, "Rendered status updates must retain exactly one account Journal");
        assert.equal(counts.chooser, 1, "Rendered status updates must retain exactly one strategy chooser");
      }
      await single();
      await history().locator("summary").first().click();
      await inspector.getByText("primary retained event 1").waitFor();
      await chooser().locator("summary").first().click();
      await chooser().getByRole("combobox", { name: "Next strategy" }).waitFor();
      assert.equal(await chooser().getByRole("option").count(), 9);
      for (let i = 0; i < 3; i++) {
        phase = `rendered-status-${i + 1}`;
        const next = statusCount + 1;
        await page.getByText(`primary: synthetic status ${next}`, { exact: true }).waitFor();
        await single();
        assert(await history().getByText("primary retained event 1").isVisible());
      }
      await inspector.screenshot({ path: path.join(directory, "status-refresh.png") });
      phase = "next-history-page";
      await history().getByRole("button", { name: "Next history page", exact: true }).click();
      await history().getByText("primary retained event 3").waitFor();
      assert.equal(await history().getByText("primary retained event 1").count(), 0);
      phase = "first-history-page";
      await history().getByRole("button", { name: "First history page", exact: true }).click();
      await history().getByText("primary retained event 1").waitFor();
      assert.equal(await history().getByText("primary retained event 3").count(), 0);
      phase = "switch-account-reset";
      await page.getByRole("button", { name: "Inspect responsive-v1", exact: true }).click();
      await inspector.getByRole("heading", { name: "responsive-v1", exact: true }).waitFor();
      await single();
      assert.equal(await history().getAttribute("open"), null, "New account must reset Journal disclosure");
      assert.equal(await history().getByRole("table").count(), 0, "No prior account history may carry over");
      await history().locator("summary").first().click();
      await history().getByText("responsive-v1 retained event 1").waitFor();
      assert.equal(await history().getByText("primary retained event 1").count(), 0);
      await inspector.screenshot({ path: path.join(directory, "switched-account.png") });
      assert(requests.some(row => row.path === "/api/paper/journal" &&
        row.query === "?account=primary&after=2&limit=100"));
      assert(requests.some(row => row.path === "/api/paper/journal" &&
        row.query === "?account=responsive-v1&after=0&limit=100"));
      assert(requests.every(row => row.method === "GET"), "Regression must not submit financial controls");
      assert.equal(errors.length, 0, "No dashboard JavaScript errors");
      stages.push({ phase: "passed", statusCount });
    }
    await Promise.race([flow(), new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(`45-second finite regression deadline at ${phase}`)), 45000);
    })]);
  } catch (error) {
    failure = { phase, message: error.message, stack: error.stack };
    if (page) await page.screenshot({ path: path.join(directory, "failure.png") }).catch(() => {});
  } finally {
    clearTimeout(timer);
    if (browser) {
      try { await browser.close(); browserClosed = true; }
      catch (error) { failure = failure || { phase: "browser-cleanup", message: error.message }; }
    }
    fs.writeFileSync(path.join(directory, "receipt.json"), JSON.stringify({ ...receipt,
      passed: failure === null, failure, phases: stages, page_errors: errors,
      requests, assets_sha256: assets, browser_started: !!browser,
      browser_closed: browserClosed }, null, 2));
  }
  if (failure) { console.error(JSON.stringify(failure)); process.exitCode = 1; }
  else console.log("Compiled account history/status regression passed (synthetic API only)");
})().catch(error => { console.error(error); process.exitCode = 1; });
