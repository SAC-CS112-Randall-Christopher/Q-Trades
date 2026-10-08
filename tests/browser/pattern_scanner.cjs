// Actual compiled UI/registry/worker, with explicitly synthetic native source and admission.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { chromium } = require("playwright");
const origin = process.env.QTRADES_BROWSER_QA_ORIGIN || "http://127.0.0.1:58969";
const directory = process.env.QTRADES_BROWSER_QA_OUTPUT;
const token = process.env.QTRADES_BROWSER_QA_TOKEN;
const sha = bytes => crypto.createHash("sha256").update(bytes).digest("hex");
const bounded = async (work, milliseconds, label) => {
  let timer;
  try {
    return await Promise.race([work, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(label)), milliseconds);
    })]);
  } finally { clearTimeout(timer); }
};

(async () => {
  assert(directory && token, "Task-owned output and explicit QA token are required");
  const url = new URL(origin);
  assert.equal(url.hostname, "127.0.0.1");
  assert(!["8780", "5432", "54544", "58968"].includes(url.port));
  fs.mkdirSync(directory, { recursive: false });
  const groups = [], pageErrors = [], externalRequests = [], apiRequests = [];
  const receipt = { evidence_kind: "compiled_ui_actual_scanner_api_registry_synthetic_source_and_admission",
    operating_acceptance: false, financial_database: false, model_calls: 0,
    full_year_scale_or_market_capacity: false, profitability_or_strategy_approval: false,
    harness_sha256: sha(fs.readFileSync(__filename)), groups, pageErrors, externalRequests, apiRequests };
  let browser, context, page, other, failure = null, phase = "startup";
  const headers = { "x-qa-token": token };
  const save = (name, value) => fs.writeFileSync(path.join(directory, name), JSON.stringify(value, null, 2));
  try {
    browser = await chromium.launch({ headless: true, executablePath: process.env.QTRADES_BROWSER_QA_EXECUTABLE || undefined });
    receipt.runtime = { playwright: require("playwright/package.json").version, browser: browser.version() };
    context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, serviceWorkers: "block" });
    await context.route("**/*", route => {
      const requested = new URL(route.request().url());
      if (requested.origin !== origin) { externalRequests.push(requested.origin); return route.abort(); }
      return route.continue(); // No fabricated UI API response.
    });
    page = await context.newPage(); page.setDefaultTimeout(10000);
    page.on("pageerror", error => pageErrors.push(error.message));
    page.on("request", request => { const address = new URL(request.url());
      if (address.pathname.startsWith("/api/") && apiRequests.length < 1500) apiRequests.push({ method: request.method(), path: address.pathname, query: address.search });
    });
    const workspace = () => page.getByRole("region", { name: "Year pattern scanner" });
    const probe = async () => (await page.request.get(`${origin}/__qa/probe`, { headers })).json();
    const mode = async action => assert.equal((await page.request.post(`${origin}/__qa/${action}`, { headers })).status(), 200);
    const refresh = async () => workspace().getByRole("button", { name: "Refresh status", exact: true }).click();
    const control = async (button, expectedAction, expectedStatus = 200) => {
      const response = page.waitForResponse(r => r.url() === `${origin}/api/research/pattern-scanner/control` && r.request().method() === "POST");
      void response.catch(() => {}); // Await below still throws; keep cleanup reachable if the click stalls.
      await workspace().getByRole("button", { name: button, exact: true }).click();
      const actual = await response; const value = await actual.json();
      assert.equal(actual.status(), expectedStatus, JSON.stringify(value));
      if (expectedStatus === 200) { assert.equal(value.action, expectedAction); assert.equal(value.applied, true); }
      save(`control-${groups.length}-${expectedAction}.json`, value);
      return value;
    };
    const waitPage = kind => {
      const response = page.waitForResponse(r => r.url().startsWith(`${origin}/api/research/pattern-scanner/${kind}?`) && r.request().method() === "GET");
      void response.catch(() => {}); // Observe rejection immediately, then retain it through the normal await.
      return response;
    };

    phase = "eligible-roster-and-no-automatic-control";
    await page.goto(`${origin}/#markets`); await workspace().waitFor();
    await workspace().getByText(/26 eligible \/ 27 observed/).waitFor();
    assert.equal((await probe()).posts.length, 0);
    await workspace().getByRole("button", { name: "Select all eligible markets", exact: true }).click();
    assert(await workspace().locator(".scanner-roster").innerText().then(text => text.includes("26 markets selected from this observed eligible roster")));
    await workspace().getByRole("button", { name: "More markets", exact: true }).click();
    const thin = workspace().locator(".scanner-roster-grid label").filter({ hasText: "THIN" });
    assert.equal(await thin.getByRole("checkbox").isDisabled(), true);
    groups.push({ name: phase, observed: 27, eligible: 26, automatically_dispatched: 0 });

    phase = "prepare-all-five-frames-year-not-complete";
    const prepared = await control("Prepare selected markets", "prepare");
    assert.equal(prepared.current_status.progress_total, 130);
    assert.equal(prepared.current_status.enabled, false);
    assert.equal(prepared.current_status.campaign.requested_days, 365);
    assert.deepEqual([...prepared.current_status.campaign.timeframes].sort(), ["15m", "1h", "30m", "4h", "5m"].sort());
    assert(prepared.current_status.progress.every(row => row.observed_bars === 0 && row.status === "queued"));
    await workspace().getByText(/campaign's original screen, not a fresh eligibility claim/).waitFor();
    assert(await workspace().innerText().then(text => !text.includes("fully prepared")));
    groups.push({ name: phase, campaign: prepared.campaign_id, scopes: 130, completed: 0 });

    phase = "complete-progress-pagination";
    let read = waitPage("progress"); await workspace().getByRole("button", { name: "First / refresh progress", exact: true }).click();
    const firstProgress = await (await read).json(); assert.equal(firstProgress.rows.length, 100);
    read = waitPage("progress"); await workspace().getByRole("button", { name: "Next progress page", exact: true }).click();
    const nextProgress = await (await read).json(); assert.equal(nextProgress.rows.length, 30);
    assert.equal(new Set([...firstProgress.rows, ...nextProgress.rows].map(row => `${row.symbol}:${row.timeframe}`)).size, 130);
    save("progress-first.json", firstProgress); save("progress-next.json", nextProgress);
    groups.push({ name: phase, unique_scope_rows: 130, pages: [100, 30] });

    phase = "real-cooperative-processing-incomplete-year";
    await mode("gap"); await control("Start / resume scanner", "start");
    const advanceResponse = await page.request.post(`${origin}/__qa/advance`, { headers, timeout: 30000 });
    const advance = await advanceResponse.json(); assert.equal(advanceResponse.status(), 200, JSON.stringify(advance));
    assert(advance.maximum_levels > 105, JSON.stringify(advance));
    const processed = await probe();
    const scope = processed.levels.find(row => row.total > 105);
    assert(scope);
    assert(processed.state.progress_counts.queued > 0, "A few source pages must not claim the full year finished");
    save("processed-probe.json", processed); groups.push({ name: phase, ...advance, scope, full_year_complete: false, downloaded_page_may_still_be_processing: true });

    phase = "every-level-paged-reload-and-original-evidence";
    await workspace().getByLabel("Scanner evidence market").selectOption(scope.symbol);
    await workspace().getByLabel("Scanner evidence interval").selectOption(scope.timeframe);
    read = waitPage("levels"); await workspace().getByRole("button", { name: "Inspect saved evidence", exact: true }).click();
    const firstLevels = await (await read).json(); assert.equal(firstLevels.rows.length, 100);
    assert.equal(firstLevels.total, scope.total);
    read = waitPage("levels"); await workspace().getByRole("button", { name: "Next evidence page", exact: true }).click();
    const nextLevels = await (await read).json(); assert(nextLevels.rows.length > 0);
    assert.equal(new Set([...firstLevels.rows, ...nextLevels.rows].map(row => row.seq)).size, firstLevels.rows.length + nextLevels.rows.length);
    assert(firstLevels.rows.every(row => row.source_sha256 && row.first_usable_ms > row.confirmed_at_ms && row.financial_authority === false));
    save("levels-first.json", firstLevels); save("levels-next.json", nextLevels);
    await page.reload(); await workspace().getByRole("button", { name: "Pause scanner", exact: true }).waitFor();
    await workspace().getByText(new RegExp(`^Current campaign ${prepared.campaign_id} · revision`)).waitFor();
    await workspace().getByLabel("Scanner evidence market").selectOption(scope.symbol);
    await workspace().getByLabel("Scanner evidence interval").selectOption(scope.timeframe);
    read = waitPage("levels"); await workspace().getByRole("button", { name: "Inspect saved evidence", exact: true }).click();
    const reopenedLevels = await (await read).json(); assert.deepEqual(reopenedLevels, firstLevels);
    groups.push({ name: phase, retained_total: firstLevels.total, displayed_pages: [100, nextLevels.rows.length], original_reopened: true });

    phase = "historical-patterns-not-current-profitability";
    await workspace().getByLabel("Scanner evidence type").selectOption("patterns");
    read = waitPage("patterns"); await workspace().getByRole("button", { name: "Inspect saved evidence", exact: true }).click();
    const patterns = await (await read).json(); assert(patterns.total > 0);
    assert(patterns.rows.every(row => row.historical === true && row.financial_authority === false));
    assert(await workspace().innerText().then(text => text.includes("do not establish validated profitability")));
    save("historical-patterns.json", patterns); groups.push({ name: phase, observed_patterns: patterns.total, financial_authority: false });

    phase = "protected-wait-and-pause";
    await mode("block"); const beforeBlocked = await probe();
    assert.equal((await page.request.post(`${origin}/__qa/advance`, { headers, timeout: 30000 })).status(), 200);
    const afterBlocked = await probe(); assert.equal(afterBlocked.native_requests.length, beforeBlocked.native_requests.length);
    await refresh(); await workspace().getByText(/yielding to protected research\/storage inputs/).waitFor();
    await control("Pause scanner", "pause");
    assert.equal((await probe()).state.enabled, false);
    await mode("unblock"); await mode("normal");
    groups.push({ name: phase, native_requests_while_blocked: 0, paused: true });

    phase = "lost-control-ack-reload-exact-get-no-repeat";
    await mode("lost_ack"); await control("Start / resume scanner", "start", 503);
    await workspace().getByRole("button", { name: "Find saved start result", exact: true }).waitFor();
    const lost = await probe(); const original = lost.posts.at(-1); assert(original.saved_receipt.applied);
    await page.reload(); await workspace().getByRole("button", { name: "Find saved start result", exact: true }).waitFor();
    const second = await context.newPage(); await second.goto(`${origin}/#markets`);
    const secondPanel = second.getByRole("region", { name: "Year pattern scanner" });
    await secondPanel.getByRole("button", { name: "Find saved start result", exact: true }).waitFor();
    assert.equal(await secondPanel.getByRole("button", { name: "Start / resume scanner", exact: true }).isDisabled(), true);
    assert.equal((await probe()).posts.length, lost.posts.length);
    await second.close();
    await mode("receipt_outage"); await workspace().getByRole("button", { name: "Find saved start result", exact: true }).click();
    await workspace().getByRole("alert").filter({ hasText: "exact saved control" }).waitFor();
    assert.equal(await workspace().getByRole("button", { name: "Start / resume scanner", exact: true }).isDisabled(), true);
    await mode("normal"); await workspace().getByRole("button", { name: "Find saved start result", exact: true }).click();
    await workspace().getByRole("button", { name: "Find saved start result", exact: true }).waitFor({ state: "detached" });
    assert.equal((await probe()).posts.length, lost.posts.length);
    save("lost-ack-probe.json", lost); groups.push({ name: phase, request_id: original.body.request_id, extra_posts: 0 });

    phase = "status-outage-pause-remains-available";
    await mode("status_outage"); await refresh();
    await workspace().getByRole("alert").filter({ hasText: "status is unavailable" }).waitFor();
    assert.equal(await workspace().getByRole("button", { name: "Pause scanner", exact: true }).isEnabled(), true);
    await control("Pause scanner", "pause");
    assert.equal((await probe()).state.enabled, false);
    await mode("normal"); await refresh(); groups.push({ name: phase, paused_with_last_known_identity: true });

    phase = "delayed-start-cannot-overtake-acknowledged-pause";
    other = await context.newPage(); await other.goto(`${origin}/#markets`);
    const otherPanel = other.getByRole("region", { name: "Year pattern scanner" });
    await otherPanel.getByText(new RegExp(`^Current campaign ${prepared.campaign_id} \\u00b7 revision`)).waitFor();
    await otherPanel.getByRole("button", { name: "Pause scanner", exact: true }).waitFor();
    await mode("delay_start");
    const startResponse = page.waitForResponse(r => r.url() === `${origin}/api/research/pattern-scanner/control` && r.request().postDataJSON().action === "start");
    void startResponse.catch(() => {});
    await workspace().getByRole("button", { name: "Start / resume scanner", exact: true }).click();
    await workspace().getByRole("button", { name: "Find saved start result", exact: true }).waitFor();
    const heldResponse = await page.request.get(`${origin}/__qa/held_start`, { headers, timeout: 3000 });
    assert.equal(heldResponse.status(), 200, await heldResponse.text());
    const held = await heldResponse.json(); assert.equal(held.synthetic_fixture_only, true);
    assert.equal(held.held_start.status, "held");
    const pendingStart = await page.evaluate(() => JSON.parse(localStorage.getItem("qtrades-year-pattern-scanner-pending-v1")).find(command => command.action === "start"));
    assert.equal(held.held_start.request_id, pendingStart.request_id);
    assert.equal(held.held_start.expected_revision, pendingStart.expected_revision);
    save("delayed-start-held-before-pause.json", held);
    const pauseDeadline = Date.now() + 30000;
    const remainingPauseTime = () => {
      const remaining = pauseDeadline - Date.now();
      assert(remaining > 0, "Pause acknowledgment and exact recovery must finish within the original 30-second bound");
      return remaining;
    };
    const withinPauseTime = work => {
      const remaining = remainingPauseTime();
      return bounded(work(), remaining, "Pause acknowledgment or exact recovery exceeded the original 30-second bound");
    };
    let pauseRouteFailure = null;
    const controlUrl = `${origin}/api/research/pattern-scanner/control`;
    await withinPauseTime(() => other.route(controlUrl, async route => {
      if (route.request().postDataJSON().action !== "pause") return route.continue();
      try {
        // Hold the real shared browser lock after Pause was persisted, before
        // sending its unchanged request to the real backend. Both terminal
        // responses therefore contend with a known owner rather than a sleep.
        await withinPauseTime(() => other.evaluate(async () => {
          let entered, rejected;
          const acquired = new Promise((resolve, reject) => { entered = resolve; rejected = reject; });
          const held = new Promise(resolve => { window.__qaScannerTerminalRelease = resolve; });
          window.__qaScannerTerminalLockDone = navigator.locks.request(
            "qtrades-year-pattern-scanner-pending-v1", async () => { entered(); await held; });
          void window.__qaScannerTerminalLockDone.catch(rejected);
          await acquired;
          return true;
        }));
        await route.continue(); // No response or command is fabricated.
      } catch (error) { pauseRouteFailure = error.message; await route.abort(); }
    }));
    const pauseResponse = other.waitForResponse(r => r.url() === `${origin}/api/research/pattern-scanner/control` &&
      r.request().method() === "POST" && r.request().postDataJSON().action === "pause", { timeout: remainingPauseTime() });
    void pauseResponse.catch(() => {});
    await otherPanel.getByRole("button", { name: "Pause scanner", exact: true }).click({ timeout: remainingPauseTime() });
    const pauseActual = await withinPauseTime(() => pauseResponse);
    const pauseCommand = pauseActual.request().postDataJSON();
    save("delayed-start-pause-command.json", { http_status: pauseActual.status(), command: pauseCommand });
    const pauseReceipt = await withinPauseTime(() => pauseActual.json());
    save("delayed-start-pause-response.json", { http_status: pauseActual.status(), command: pauseCommand, receipt: pauseReceipt });
    assert.equal(pauseRouteFailure, null);
    assert.equal(pauseActual.status(), 200, JSON.stringify(pauseReceipt));
    assert.equal(pauseCommand.action, "pause"); assert.equal(pauseCommand.campaign_id, prepared.campaign_id);
    assert.equal(pauseReceipt.request_id, pauseCommand.request_id);
    assert.equal(pauseReceipt.action, "pause"); assert.equal(pauseReceipt.applied, true);
    assert.equal(pauseReceipt.campaign_id, prepared.campaign_id);
    assert.equal(pauseReceipt.revision, held.held_start.expected_revision + 1);
    assert.equal(pauseReceipt.current_status.enabled, false);
    assert.equal(pauseReceipt.current_status.revision, pauseReceipt.revision);
    const savedPause = { ...pauseReceipt }; delete savedPause.current_status;
    const refusedStart = await withinPauseTime(() => startResponse), startRefusal = await withinPauseTime(() => refusedStart.json());
    save("delayed-start-refusal-response.json", { http_status: refusedStart.status(), command: refusedStart.request().postDataJSON(), receipt: startRefusal });
    assert.equal(refusedStart.status(), 409, JSON.stringify(startRefusal));
    assert.equal(refusedStart.request().postDataJSON().request_id, held.held_start.request_id);
    assert.equal(startRefusal.detail, "Preparation changed; reopen its current revision before Start");
    await withinPauseTime(() => page.waitForFunction(async () => {
      const locks = await navigator.locks.query();
      return locks.held.some(lock => lock.name === "qtrades-year-pattern-scanner-pending-v1") &&
        locks.pending.some(lock => lock.name === "qtrades-year-pattern-scanner-pending-v1");
    }, null, { timeout: remainingPauseTime() }));
    const queuedRefusal = await withinPauseTime(() => page.evaluate(async () => ({
      pending: JSON.parse(localStorage.getItem("qtrades-year-pattern-scanner-pending-v1") || "[]"),
      refusal: JSON.parse(localStorage.getItem("qtrades-year-pattern-scanner-refusal-v1") || "null"),
      locks: await navigator.locks.query()
    })));
    assert.deepEqual(queuedRefusal.pending, [pendingStart, pauseCommand]);
    assert(!queuedRefusal.refusal || queuedRefusal.refusal.command.request_id !== pendingStart.request_id);
    save("delayed-start-refusal-queued-under-held-lock.json", queuedRefusal);
    await withinPauseTime(() => other.evaluate(async () => {
      window.__qaScannerTerminalRelease();
      await window.__qaScannerTerminalLockDone;
      delete window.__qaScannerTerminalRelease;
      delete window.__qaScannerTerminalLockDone;
    }));
    await withinPauseTime(() => other.unroute(controlUrl));
    // Wait for the original refusal cleanup before a second tab performs GET-only recovery.
    await workspace().getByRole("alert").filter({ hasText: startRefusal.detail }).waitFor({ timeout: remainingPauseTime() });
    await workspace().getByRole("button", { name: "Find saved start result", exact: true }).waitFor({ state: "detached", timeout: remainingPauseTime() });
    const recordedRefusal = await withinPauseTime(() => page.evaluate(() => JSON.parse(
      localStorage.getItem("qtrades-year-pattern-scanner-refusal-v1") || "null")));
    assert.deepEqual(recordedRefusal.command, pendingStart);
    assert.equal(recordedRefusal.status, 409); assert.equal(recordedRefusal.detail, startRefusal.detail);
    save("delayed-start-known-refusal-cleanup.json", recordedRefusal);
    await other.waitForFunction(() => {
      const region = document.querySelector(".scanner-workspace");
      return region && (region.textContent.includes("pause was acknowledged") ||
        [...region.querySelectorAll("button")].some(button => button.textContent === "Find saved pause result" && !button.disabled));
    }, null, { timeout: remainingPauseTime() });
    const pendingPause = await withinPauseTime(() => other.evaluate(() => JSON.parse(localStorage.getItem("qtrades-year-pattern-scanner-pending-v1") || "[]")));
    let recoveredPause = false;
    if (pendingPause.length) {
      assert.deepEqual(pendingPause, [pauseCommand], "Only the original acknowledged Pause may remain for recovery");
      const exactPause = other.waitForResponse(r => r.url() === `${origin}/api/research/pattern-scanner/requests/${pauseCommand.request_id}` &&
        r.request().method() === "GET", { timeout: remainingPauseTime() });
      void exactPause.catch(() => {});
      await otherPanel.getByRole("button", { name: "Find saved pause result", exact: true }).click({ timeout: remainingPauseTime() });
      const reopenedPause = await withinPauseTime(() => exactPause), reopenedReceipt = await withinPauseTime(() => reopenedPause.json());
      save("delayed-start-pause-reopened.json", { http_status: reopenedPause.status(), request_id: pauseCommand.request_id, receipt: reopenedReceipt });
      const reopenedSaved = { ...reopenedReceipt }; delete reopenedSaved.current_status;
      assert.equal(reopenedPause.status(), 200); assert.deepEqual(reopenedSaved, savedPause);
      assert.equal(reopenedReceipt.current_status.enabled, false);
      assert.equal(reopenedReceipt.current_status.revision, pauseReceipt.revision);
      recoveredPause = true;
    }
    await otherPanel.getByText(/pause was acknowledged/).waitFor({ timeout: remainingPauseTime() });
    const afterHeldPause = await probe(); assert.equal(afterHeldPause.state.enabled, false);
    assert.equal(afterHeldPause.held_start.status, "released_after_acknowledged_pause");
    assert.equal(afterHeldPause.held_start.request_id, held.held_start.request_id);
    assert(afterHeldPause.held_start.pause_revision > held.held_start.expected_revision);
    const heldPosts = afterHeldPause.posts.filter(row => row.body.request_id === held.held_start.request_id);
    assert.equal(heldPosts.length, 1); assert.equal(heldPosts[0].http_status, 409);
    const releasingPause = afterHeldPause.posts.find(row => row.body.request_id === afterHeldPause.held_start.pause_request_id);
    assert.equal(releasingPause.http_status, 200); assert.equal(releasingPause.saved_receipt.applied, true);
    assert.equal(releasingPause.body.request_id, pauseCommand.request_id);
    assert.deepEqual(releasingPause.body, pauseCommand); assert.deepEqual(releasingPause.saved_receipt, savedPause);
    assert.equal(afterHeldPause.posts.filter(row => row.body.request_id === pauseCommand.request_id).length, 1);
    save("delayed-start-released-after-pause.json", afterHeldPause);
    assert.equal(await page.evaluate(() => localStorage.getItem("qtrades-year-pattern-scanner-pending-v1")), null);
    await other.close(); await mode("normal");
    groups.push({ name: phase, stale_start: 409, pause_preserved: true, exact_pause_get_recovery: recoveredPause,
      original_pause_posts: 1, terminal_refusal_lock_queued: true, known_refusal_cleared: true });

    phase = "owner-reopen-preserves-history-and-stays-disabled";
    const beforeRestart = await probe();
    assert.equal((await page.request.post(`${origin}/__qa/restart_owner`, { headers })).status(), 200);
    const afterRestart = await probe(); assert.equal(afterRestart.state.enabled, false);
    assert.deepEqual(afterRestart.levels, beforeRestart.levels); assert.deepEqual(afterRestart.events, beforeRestart.events);
    await page.reload(); await workspace().waitFor();
    groups.push({ name: phase, saved_levels_preserved: true, explicit_start_required: true });

    phase = "actual-prospective-alert-and-honest-missing-other-frames";
    await mode("sparse_4h");
    const clearSelection = workspace().getByRole("button", { name: "Clear selection", exact: true });
    if (await clearSelection.isEnabled()) await clearSelection.click();
    await workspace().locator(".scanner-roster-grid label").filter({ hasText: "BTC / USD" }).getByRole("checkbox").check();
    const prospectiveCampaign = await control("Prepare selected markets", "prepare");
    assert.equal(prospectiveCampaign.current_status.progress_total, 5);
    await control("Start / resume scanner", "start");
    // Normal controls above are exercised through the UI. Stop its polling
    // while constructing the finite historical and prospective input fixture.
    await page.goto("about:blank");
    let advanced = await page.request.post(`${origin}/__qa/advance`, { headers, timeout: 30000 });
    assert.equal(advanced.status(), 200, await advanced.text());
    const historicalComplete = await probe();
    assert(historicalComplete.state.progress.every(row => row.cursor_ms === row.cutoff_ms));
    const fourHour = historicalComplete.state.progress.find(row => row.timeframe === "4h");
    assert.equal(fourHour.observed_bars, 2190);
    assert.equal(fourHour.status, "monitoring");
    assert(historicalComplete.state.progress.filter(row => row.timeframe !== "4h").every(row => row.missing_bars === row.expected_bars && row.observed_bars === 0));
    await mode("future_4h");
    advanced = await page.request.post(`${origin}/__qa/advance`, { headers, timeout: 30000 });
    assert.equal(advanced.status(), 200, await advanced.text());
    const prospectiveComplete = await probe();
    assert.equal(prospectiveComplete.synthetic_now_seconds - historicalComplete.synthetic_now_seconds, 14400);
    await page.goto(`${origin}/#markets`); await workspace().waitFor();
    await refresh();
    await workspace().getByLabel("Scanner evidence market").selectOption("BTCUSD");
    await workspace().getByLabel("Scanner evidence interval").selectOption("4h");
    await workspace().getByLabel("Scanner evidence type").selectOption("alerts");
    read = waitPage("alerts"); await workspace().getByRole("button", { name: "Inspect saved evidence", exact: true }).click();
    const alerts = await (await read).json();
    assert(alerts.rows.some(row => row.kind === "resistance_breakout" && row.historical === false && row.evaluation && row.financial_authority === false));
    assert(alerts.rows.every(row => ["unknown", "candidate", "does_not_meet_criteria"].includes(row.evaluation.status) && row.evaluation.criteria && typeof row.evaluation.checks === "object"));
    await workspace().getByText(/Current evaluation:/).first().waitFor();
    save("prospective-alerts.json", alerts); save("prospective-history.json", historicalComplete);
    groups.push({ name: phase, actual_4h_history: 2190, missing_other_frames_retained: true, synthetic_clock: "+4h", actual_alerts: alerts.total, financial_authority: false });
    await control("Pause scanner", "pause");

    phase = "earlier-campaign-reopen-after-new-preparation";
    await workspace().getByRole("button", { name: "Read saved campaigns", exact: true }).click();
    await workspace().getByLabel("Saved scanner campaign").selectOption(prepared.campaign_id);
    await workspace().getByRole("button", { name: "Reopen saved campaign", exact: true }).click();
    await workspace().getByText(`Inspecting saved campaign ${prepared.campaign_id}.`, { exact: false }).waitFor();
    await workspace().getByLabel("Scanner evidence market").selectOption(scope.symbol);
    await workspace().getByLabel("Scanner evidence interval").selectOption(scope.timeframe);
    await workspace().getByLabel("Scanner evidence type").selectOption("levels");
    read = waitPage("levels"); await workspace().getByRole("button", { name: "Inspect saved evidence", exact: true }).click();
    const oldReopen = await (await read).json(); assert.deepEqual(oldReopen, firstLevels);
    save("old-campaign-reopen.json", oldReopen);
    groups.push({ name: phase, immutable_previous_campaign: prepared.campaign_id, current_campaign: prospectiveCampaign.campaign_id, old_original_page_preserved: true });

    phase = "mobile-screenshot-and-bounded-chart-link";
    const beforeChart = await probe();
    await workspace().getByRole("button", { name: "Open bounded candle chart", exact: true }).click();
    assert.equal((await probe()).native_requests.length, beforeChart.native_requests.length, "Opening the chart must not auto-fetch a heavy study");
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForFunction(() => { const element = document.querySelector(".scanner-workspace"); return element.scrollWidth <= element.clientWidth; }, null, { timeout: 5000 });
    await page.evaluate(() => {
      document.activeElement?.blur();
      const marker = document.createElement("p"); marker.textContent = "SOURCE QA · SYNTHETIC SOURCE / ADMISSION · NO YEAR CAPACITY OR PROFITABILITY PROOF";
      marker.style.cssText = "padding:10px;background:#f2d589;color:#10211d;font-size:12px";
      document.querySelector(".scanner-workspace").prepend(marker);
    });
    await workspace().screenshot({ path: path.join(directory, "scanner-mobile.png") });
    await page.setViewportSize({ width: 1440, height: 3200 });
    await workspace().locator(":scope > header").click(); await workspace().screenshot({ path: path.join(directory, "scanner-workspace.png") });
    groups.push({ name: phase, mobile_width: 390, horizontal_overflow: false, automatic_chart_fetches: 0 });
    const final = await probe(); save("final-probe.json", final);
    assert.equal(final.financial_state_preserved_except_fixture_tick, true);
    assert.equal(final.financial_database, false); assert.equal(final.model_calls, 0);
    assert.deepEqual(pageErrors, []); assert.deepEqual(externalRequests, []);
    receipt.passed = true;
  } catch (error) {
    failure = { phase, name: error.name, message: error.message }; receipt.passed = false;
    if (page) {
      try { fs.writeFileSync(path.join(directory, "failure-dom.txt"), await page.locator("body").innerText({ timeout: 5000 })); } catch {}
      try { await page.screenshot({ path: path.join(directory, "failure.png"), fullPage: true, timeout: 5000 }); } catch {}
      try { save("failure-probe.json", await bounded((async () => (await page.request.get(`${origin}/__qa/probe`, { headers, timeout: 5000 })).json())(), 5000, "Failure probe unavailable")); } catch {}
      try { save("failure-pending.json", await bounded(page.evaluate(() => ({
        pending: localStorage.getItem("qtrades-year-pattern-scanner-pending-v1"),
        refusal: localStorage.getItem("qtrades-year-pattern-scanner-refusal-v1")
      })), 5000, "Failure pending identity unavailable")); } catch {}
    }
    if (other && !other.isClosed()) {
      try { fs.writeFileSync(path.join(directory, "failure-other-dom.txt"), await other.locator("body").innerText({ timeout: 5000 })); } catch {}
      try { await other.screenshot({ path: path.join(directory, "failure-other.png"), fullPage: true, timeout: 5000 }); } catch {}
    }
  } finally {
    try { receipt.stop_status = (await fetch(`${origin}/__qa/stop`, { method: "POST", headers, signal: AbortSignal.timeout(5000) })).status; }
    catch (error) { receipt.stop_error = error.name; }
    await context?.close(); await browser?.close(); receipt.browser_closed = true; receipt.failure = failure;
    receipt.artifacts = Object.fromEntries(fs.readdirSync(directory).filter(name => name !== "receipt.json").map(name => [name, sha(fs.readFileSync(path.join(directory, name)))]));
    fs.writeFileSync(path.join(directory, "receipt.json"), JSON.stringify(receipt, null, 2));
  }
  if (failure) { process.stderr.write(`${failure.phase}: ${failure.message}\n`); process.exitCode = 1; }
  else process.stdout.write(`Passed ${groups.length} scanner UI groups; synthetic source/admission only.\n`);
})();
