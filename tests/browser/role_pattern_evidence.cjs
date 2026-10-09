// Compiled normal task/Markets navigation; real owners, synthetic source inputs, no model dispatch.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { chromium } = require("playwright");
const { completedJsonGet } = require("./completed_get.cjs");
const origin = process.env.QTRADES_BROWSER_QA_ORIGIN || "http://127.0.0.1:58975";
const directory = process.env.QTRADES_BROWSER_QA_OUTPUT;
const token = process.env.QTRADES_BROWSER_QA_TOKEN;
const profileOnly = process.env.QTRADES_ROLE_PATTERN_QA_PROFILE_ONLY === "1";
const sha = bytes => crypto.createHash("sha256").update(bytes).digest("hex");
const bounded = async (promise, milliseconds, label) => {
  let timer;
  try {
    return await Promise.race([promise, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(label)), milliseconds);
    })]);
  } finally { clearTimeout(timer); }
};

(async () => {
  assert(directory && token);
  const address = new URL(origin);
  assert.equal(address.hostname, "127.0.0.1");
  assert(!["8780", "5432", "54544"].includes(address.port));
  fs.mkdirSync(directory, { recursive: false });
  const groups = [], pageErrors = [], requests = [], externalRequests = [];
  const receipt = {
    scope: "Compiled UI/actual API and saved native selector task; synthetic native/current inputs",
    harness_sha256: sha(fs.readFileSync(__filename)), groups, pageErrors, requests, externalRequests,
    navigation_capture_sha256: sha(fs.readFileSync(require.resolve("./completed_get.cjs"))),
    operating_acceptance: false, financial_database: false, model_calls: 0,
    mode: profileOnly ? "affected-current-profile" : "full-seven-group",
  };
  const headers = { "x-qa-token": token };
  const save = (name, value) => fs.writeFileSync(path.join(directory, name), JSON.stringify(value, null, 2));
  let browser, context, page, phase = "startup", failure;
  const started = Date.now();
  const remaining = milliseconds => Math.max(1, Math.min(milliseconds, 90000 - (Date.now() - started)));
  const within = (promise, milliseconds, label) => bounded(promise, remaining(milliseconds), label);
  const deadline = setTimeout(() => {
    receipt.workflow_deadline_reached = true;
    if (context) void context.close().catch(error => { receipt.watchdog_close_error = error.message; });
  }, 90000);
  try {
    browser = await chromium.launch({ headless: true, timeout: remaining(10000), executablePath: process.env.QTRADES_BROWSER_QA_EXECUTABLE || undefined });
    receipt.runtime = { playwright: require("playwright/package.json").version, browser: browser.version() };
    context = await within(browser.newContext({ viewport: { width: 1440, height: 1100 }, serviceWorkers: "block" }), 10000, "Context setup exceeded workflow bound");
    await context.route("**/*", route => {
      if (new URL(route.request().url()).origin !== origin) {
        externalRequests.push(route.request().url()); return route.abort();
      }
      return route.continue();
    });
    page = await within(context.newPage(), 10000, "Page setup exceeded workflow bound"); page.setDefaultTimeout(10000);
    page.on("pageerror", error => pageErrors.push(error.message));
    page.on("request", request => {
      const url = new URL(request.url());
      if (url.pathname.startsWith("/api/") && requests.length < 400) requests.push({ method: request.method(), path: url.pathname, query: url.search });
    });
    const probe = async () => {
      const response = await page.request.get(`${origin}/__qa/probe`, { headers, timeout: remaining(6000) });
      assert.equal(response.status(), 200); return within(response.json(), 5000, "Probe body exceeded workflow bound");
    };
    const completedGet = apiPath => completedJsonGet(page, origin, apiPath, {
      timeout: remaining(10000), bodyTimeout: remaining(5000), observations: receipt.navigation_reads ??= [],
    });
    const original = await probe(); save("initial-probe.json", original);
    assert.equal(original.current_contract, "reviewed-rule-role-v8");
    const pattern = original.task.context.pattern_comparison;
    const taskUrl = `${origin}/#role-research?task=${original.task_id}`;
    const task = () => page.getByRole("article", { name: "Saved research task" });
    const evidence = () => page.getByRole("region", { name: "Saved pattern research evidence" });
    const openTask = async () => {
      page.setDefaultTimeout(remaining(10000));
      await page.goto(taskUrl, { waitUntil: "domcontentloaded", timeout: remaining(10000) });
      await task().getByRole("heading", { name: original.question, exact: true }).waitFor();
      await evidence().getByRole("heading", { name: "Original native finding and fixed comparison", exact: true }).waitFor();
    };

    if (!profileOnly) {
    phase = "actual-selector-task-original-and-current-evidence";
    await openTask();
    await page.getByRole("region", { name: "Pattern research questions", exact: true }).waitFor();
    assert.equal(await page.getByRole("button", { name: "Save research question", exact: true }).count(), 0);
    const text = await evidence().innerText();
    assert(text.includes(pattern.original_event.reason));
    assert(text.includes("not current admission or an economic outcome"));
    assert(text.includes("Native scanner candles were not substituted"));
    assert(text.includes("breakout-retest-v1") && text.includes("cost-breakout-v1"));
    for (const row of pattern.coverage) assert(text.includes(`${row.timeframe}: ${row.status}`));
    assert.equal(original.attempts.length, 0); assert.equal(original.inbox_count, 0); assert.equal(original.stub_inference_callbacks, 0);
    if (original.audit_recovery) {
      assert.equal(original.original_preparation.status, "waiting");
      assert(text.includes("Original preparation wait retained"));
      assert(text.includes(original.original_preparation.evaluation.reason));
      assert((await page.getByRole("region", { name: "Evidence-driven question selection" }).innerText()).includes("no further strategy refinement is implemented"));
    }
    groups.push({ name: phase, task: original.task_id, original_finding: pattern.finding_sha256, coverage_rows: pattern.coverage.length });

    phase = "exact-fixed-controls-and-distinct-input-proof";
    await evidence().getByText("Fixed candidate and reference controls with task input identity", { exact: true }).click();
    const fixedText = await evidence().locator("details").last().innerText();
    assert(fixedText.includes(original.task.context.fixed_comparison.p0.current_inputs.sha256));
    assert(fixedText.includes("inapplicable_compatibility_fields"));
    assert.equal(await task().getByText(/with 20 bars, compared/).count(), 0);
    await evidence().getByText("Fixed candidate and reference controls with task input identity", { exact: true }).click();
    await task().getByText("Execution evidence summary and permitted capabilities", { exact: true }).click();
    const safeInputs = await task().locator("details").filter({ has: page.getByText("Execution evidence summary and permitted capabilities", { exact: true }) }).innerText();
    assert(!safeInputs.includes('"references"'));
    await task().getByText("Execution evidence summary and permitted capabilities", { exact: true }).click();
    groups.push({ name: phase, current_input_sha256: original.task.context.fixed_comparison.p0.current_inputs.sha256, private_archive_paths_displayed: false });

    phase = "original-preparation-link-get-only-recovery";
    const preparationLink = evidence().getByRole("link", { name: "Reopen original preparation", exact: true });
    const preparationHref = await preparationLink.getAttribute("href");
    assert.equal(new URLSearchParams(preparationHref.split("?")[1]).get("pattern_comparison_request"), pattern.preparation_request_id);
    const expectedGet = completedGet(`/api/research/pattern-scanner/comparisons/${pattern.preparation_request_id}`);
    await preparationLink.click();
    const preparation = await expectedGet;
    assert.equal(preparation.request_id, pattern.preparation_request_id);
    assert.equal(preparation.finding_sha256, pattern.finding_sha256);
    assert.deepEqual(preparation, original.original_preparation);
    save("original-preparation-reopen.json", preparation);
    const preparationPanel = page.getByRole("region", { name: "Review prospective comparison", exact: true });
    if (original.audit_recovery) {
      await preparationPanel.getByText(original.original_preparation.evaluation.reason, { exact: false }).first().waitFor();
    } else {
      await preparationPanel.getByText("Preparation supported by the captured numerical check", { exact: true }).waitFor();
    }
    await preparationPanel.getByText(`Original UUID ${pattern.preparation_request_id}`, { exact: false }).waitFor();
    groups.push({ name: phase, request_id: preparation.request_id, exact_original_receipt: true });

    phase = "original-daily-and-progress-pinned-finding-link";
    await openTask();
    const findingLink = evidence().getByRole("link", { name: "Reopen original daily finding", exact: true });
    const findingHref = await findingLink.getAttribute("href");
    const bookmark = new URLSearchParams(findingHref.split("?")[1]);
    assert.equal(bookmark.get("scanner_campaign"), pattern.campaign_id);
    assert.equal(bookmark.get("daily_shortlist"), pattern.selection.daily_id);
    assert.equal(bookmark.get("scanner_chart_seq"), String(pattern.selection.event_seq));
    assert.equal(bookmark.get("scanner_chart_progress_sha256"), pattern.coverage.find(row => row.timeframe === "5m").progress_sha256);
    const dailyGet = completedGet(`/api/research/pattern-scanner/daily/shortlists/${pattern.selection.daily_id}`);
    await findingLink.click();
    const daily = await dailyGet; assert.equal(daily.id, pattern.selection.daily_id);
    await page.locator(`[data-daily-id="${pattern.selection.daily_id}"]`).waitFor();
    save("original-daily-reopen.json", daily);
    groups.push({ name: phase, exact_saved_daily: true, original_progress_sha256: bookmark.get("scanner_chart_progress_sha256"), historical_chart_success_claimed: false });

    phase = "normal-task-reload-and-mobile-evidence";
    await openTask(); await page.reload({ waitUntil: "domcontentloaded", timeout: remaining(10000) });
    await evidence().getByText(pattern.original_event.reason, { exact: true }).waitFor();
    fs.writeFileSync(path.join(directory, "task-evidence-dom.txt"), await task().innerText());
    await within(evidence().evaluate(element => {
      const caption = document.createElement("p");
      caption.textContent = "Source-only disposable QA: synthetic native and minute candles; no model dispatch, account funding or trading result.";
      element.prepend(caption);
    }), 5000, "Synthetic screenshot caption exceeded workflow bound");
    await page.setViewportSize({ width: 1440, height: 2400 });
    await evidence().scrollIntoViewIfNeeded();
    await evidence().screenshot({ path: path.join(directory, "role-pattern-evidence.png"), timeout: 5000 });
    await page.setViewportSize({ width: 390, height: 844 });
    await evidence().scrollIntoViewIfNeeded();
    const geometry = await within(evidence().evaluate(element => ({ width: element.getBoundingClientRect().width, viewport: innerWidth, document: document.documentElement.scrollWidth })), 5000, "Mobile geometry exceeded workflow bound");
    assert(geometry.width <= geometry.viewport && geometry.document <= geometry.viewport + 1, JSON.stringify(geometry));
    await page.screenshot({ path: path.join(directory, "role-pattern-mobile.png"), timeout: 5000 });
    groups.push({ name: phase, exact_task_reload: true, mobile_geometry: geometry });
    if (original.audit_recovery) {
      phase = "fixed-rule-original-qualification-source-link";
      await page.setViewportSize({ width: 1440, height: 1100 });
      await page.goto(`${origin}/#forward-learning`, { waitUntil: "domcontentloaded", timeout: remaining(10000) });
      const handoff = page.getByRole("article", { name: "Original rule result for qualification" });
      await handoff.waitFor();
      assert((await handoff.innerText()).includes("Its exploratory return is not qualification"));
      assert(await handoff.getByRole("link", { name: "Review this frozen rule and prospective funding" }).isVisible());
      assert.equal(await handoff.getByRole("button").count(), 0);
      await handoff.screenshot({ path: path.join(directory, "original-rule-qualification-source.png"), timeout: 5000 });
      groups.push({ name: phase, synthetic_scored_rule: true, no_qualification_authority: true });
    }
    }

    phase = "current-profile-controls-manual-form-not-historical-task";
    let statusResponse = await page.request.post(`${origin}/__qa/role_status/unavailable`, { headers, timeout: remaining(6000) });
    assert.equal(statusResponse.status(), 200);
    await page.goto(taskUrl, { waitUntil: "domcontentloaded", timeout: remaining(10000) });
    await page.reload({ waitUntil: "domcontentloaded", timeout: remaining(10000) });
    const manualSave = page.getByRole("button", { name: "Save research question", exact: true });
    await page.getByRole("alert").filter({ hasText: "Role status disconnected" }).waitFor();
    await manualSave.waitFor(); assert.equal(await manualSave.isEnabled(), false);
    statusResponse = await page.request.post(`${origin}/__qa/role_status/restore`, { headers, timeout: remaining(6000) });
    assert.equal(statusResponse.status(), 200);
    await page.getByRole("button", { name: "Retry status", exact: true }).click();
    await openTask();
    await page.getByRole("region", { name: "Pattern research questions", exact: true }).waitFor();
    assert.equal(await page.getByRole("button", { name: "Save research question", exact: true }).count(), 0);
    let profileResponse = await page.request.post(`${origin}/__qa/profile/legacy`, { headers, timeout: remaining(6000) });
    assert.equal(profileResponse.status(), 200);
    let profile = await within(profileResponse.json(), 5000, "Legacy fixture profile body unavailable");
    assert.equal(profile.current_contract, "reviewed-rule-role-v7");
    await page.reload({ waitUntil: "domcontentloaded", timeout: remaining(10000) });
    await openTask();
    await manualSave.waitFor(); assert.equal(await manualSave.isEnabled(), true);
    assert.equal(await evidence().count(), 1);
    assert.equal(await page.getByRole("region", { name: "Pattern research questions", exact: true }).count(), 0);
    statusResponse = await page.request.post(`${origin}/__qa/role_status/unavailable`, { headers, timeout: remaining(6000) });
    assert.equal(statusResponse.status(), 200);
    await page.getByRole("button", { name: original.question, exact: true }).last().click();
    await page.getByRole("alert").filter({ hasText: "Role status disconnected" }).waitFor();
    assert.equal(await manualSave.isEnabled(), false);
    statusResponse = await page.request.post(`${origin}/__qa/role_status/restore`, { headers, timeout: remaining(6000) });
    assert.equal(statusResponse.status(), 200);
    await page.getByRole("button", { name: "Retry status", exact: true }).click();
    await manualSave.waitFor({ state: "visible" });
    await page.waitForFunction(() => {
      const button = [...document.querySelectorAll("button")].find(value => value.textContent === "Save research question");
      return button && !button.disabled;
    }, undefined, { timeout: remaining(10000) });
    profileResponse = await page.request.post(`${origin}/__qa/profile/pattern`, { headers, timeout: remaining(6000) });
    assert.equal(profileResponse.status(), 200);
    profile = await within(profileResponse.json(), 5000, "Pattern fixture profile body unavailable");
    assert.equal(profile.current_contract, "reviewed-rule-role-v8");
    await page.reload({ waitUntil: "domcontentloaded", timeout: remaining(10000) });
    await openTask(); await page.getByRole("region", { name: "Pattern research questions", exact: true }).waitFor();
    assert.equal(await manualSave.count(), 0);
    statusResponse = await page.request.post(`${origin}/__qa/role_status/unavailable`, { headers, timeout: remaining(6000) });
    assert.equal(statusResponse.status(), 200);
    await page.getByRole("button", { name: original.question, exact: true }).last().click();
    await page.getByRole("heading", { name: "Last observed question mode: saved patterns", exact: true }).waitFor();
    assert.equal(await manualSave.count(), 0);
    statusResponse = await page.request.post(`${origin}/__qa/role_status/restore`, { headers, timeout: remaining(6000) });
    assert.equal(statusResponse.status(), 200);
    await page.getByRole("button", { name: "Retry status", exact: true }).click();
    await page.getByRole("heading", { name: "Questions selected from saved patterns", exact: true }).waitFor();
    groups.push({ name: phase, legacy_form_preserved: true, historical_task_does_not_select_mode: true, pattern_form_hidden: true, initial_status_unavailable_disables_manual: true, legacy_outage_disables_manual: true, known_pattern_outage_keeps_manual_hidden: true, fixture_profile_controls: 2, fixture_outage_controls: 6 });

    phase = "unchanged-saved-state-and-no-write-dispatch";
    const final = await probe(); save("final-probe.json", final);
    assert.deepEqual(final.source_hashes, final.source_hashes_after);
    assert.deepEqual(final.task, original.task); assert.deepEqual(final.attempts, original.attempts);
    assert.equal(final.financial_state_unchanged, true); assert.equal(final.dashboard_state_unchanged, true);
    assert.equal(final.native_calls_unchanged, true); assert.equal(final.inbox_count, 0); assert.equal(final.stub_inference_callbacks, 0);
    assert.equal(final.posts.length, 0); assert.equal(requests.filter(row => row.method !== "GET").length, 0);
    assert.deepEqual(pageErrors, []); assert.deepEqual(externalRequests, []);
    groups.push({ name: phase, automatic_api_writes: 0, model_calls: 0, task_attempts: 0, inbox_count: 0, source_unchanged: true });
    assert(Date.now() - started < 90000 && !receipt.workflow_deadline_reached, "Workflow deadline exceeded");
    receipt.passed = true;
  } catch (error) {
    failure = { phase, name: error.name, message: error.message, stack: error.stack };
    receipt.passed = false;
    if (page) {
      try { fs.writeFileSync(path.join(directory, "failure-dom.txt"), await bounded(page.locator("body").innerText({ timeout: 5000 }), 5000, "Failure DOM unavailable")); } catch (cause) { receipt.failure_dom_error = cause.name; }
      try { await page.screenshot({ path: path.join(directory, "failure.png"), timeout: 5000, fullPage: false }); } catch (cause) { receipt.failure_screenshot_error = cause.name; }
    }
  } finally {
    clearTimeout(deadline);
    try { receipt.stop_status = (await fetch(`${origin}/__qa/stop`, { method: "POST", headers, signal: AbortSignal.timeout(5000) })).status; } catch (error) { receipt.stop_error = error.name; }
    try { if (context) { await bounded(context.close(), 5000, "Context close unconfirmed"); receipt.context_closed = true; } } catch (error) { receipt.context_close_error = error.message; }
    try { if (browser) { await bounded(browser.close(), 5000, "Browser close unconfirmed"); receipt.browser_closed = true; } } catch (error) { receipt.browser_close_error = error.message; }
    if (receipt.stop_status !== 200 || receipt.context_closed !== true || receipt.browser_closed !== true) receipt.passed = false;
    receipt.failure = failure ?? null; receipt.wall_seconds = (Date.now() - started) / 1000;
    receipt.artifacts = Object.fromEntries(fs.readdirSync(directory).filter(name => name !== "receipt.json").map(name => [name, sha(fs.readFileSync(path.join(directory, name)))]));
    fs.writeFileSync(path.join(directory, "receipt.json"), JSON.stringify(receipt, null, 2));
  }
  if (!receipt.passed) { process.stderr.write(`${failure?.phase ?? "cleanup"}: ${failure?.message ?? "Cleanup unconfirmed"}\n`); process.exitCode = 1; }
  else process.stdout.write(`Passed ${groups.length} saved pattern task navigation groups; synthetic inputs, GET-only UI.\n`);
})();
