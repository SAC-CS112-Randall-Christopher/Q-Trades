// Real compiled dashboard/API/native archives; all market/current inputs are synthetic.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { chromium } = require("playwright");
const origin = process.env.QTRADES_BROWSER_QA_ORIGIN || "http://127.0.0.1:58974";
const directory = process.env.QTRADES_BROWSER_QA_OUTPUT;
const token = process.env.QTRADES_BROWSER_QA_TOKEN;
const readOnly = process.env.QTRADES_PATTERN_COMPARISON_QA_READ_ONLY === "1";
const sha = bytes => crypto.createHash("sha256").update(bytes).digest("hex");
const bounded = async (work, ms, label) => {
  let timer;
  try { return await Promise.race([work, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(label)), ms); })]); }
  finally { clearTimeout(timer); }
};

(async () => {
  assert(directory && token, "Explicit disposable output/token required");
  const address = new URL(origin); assert.equal(address.hostname, "127.0.0.1");
  assert(!["8780", "5432", "54544"].includes(address.port));
  fs.mkdirSync(directory, { recursive: false });
  const groups = [], pageErrors = [], apiRequests = [], externalRequests = [];
  const cleanupFailures = [];
  const receipt = { evidence_kind: "compiled_actual_preparation_api_real_native_proof_synthetic_market_inputs",
    operating_acceptance: false, model_calls: 0, financial_database: false,
    trading_edge_or_full_year_coverage: false, submission_or_funding: false,
    read_only_affected_group: readOnly,
    harness_sha256: sha(fs.readFileSync(__filename)), groups, pageErrors, apiRequests, externalRequests, cleanupFailures };
  const headers = { "x-qa-token": token };
  const save = (name, value) => fs.writeFileSync(path.join(directory, name), JSON.stringify(value, null, 2));
  let browser, context, page, phase = "startup", failure = null;
  const probe = async () => {
    const response = await fetch(`${origin}/__qa/probe`, { headers, signal: AbortSignal.timeout(5000) });
    assert.equal(response.status, 200); return response.json();
  };
  const mode = async action => {
    const response = await fetch(`${origin}/__qa/${action}`, { method: "POST", headers, signal: AbortSignal.timeout(5000) });
    assert.equal(response.status, 200); return response.json();
  };
  const panel = () => page.getByRole("region", { name: "Review prospective comparison", exact: true });
  const daily = () => page.getByRole("region", { name: "Daily crypto analyzer", exact: true });
  const waitApi = (method, predicate) => {
    const waiting = page.waitForResponse(response => response.request().method() === method && predicate(new URL(response.url())));
    void waiting.catch(() => {}); return waiting;
  };
  const fresh = async setup => {
    await context?.close();
    context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, serviceWorkers: "block" });
    await context.route("**/*", route => {
      const requested = new URL(route.request().url());
      if (requested.origin !== origin) { externalRequests.push(requested.origin); return route.abort(); }
      return route.continue(); // No client-side fabricated API response.
    });
    page = await context.newPage(); page.setDefaultTimeout(10000);
    page.on("pageerror", error => pageErrors.push(error.message));
    page.on("request", request => { const requested = new URL(request.url());
      if (requested.pathname.startsWith("/api/") && apiRequests.length < 1200) apiRequests.push({ method: request.method(), path: requested.pathname, query: requested.search });
    });
    await page.goto(`${origin}/#markets?symbol=BTCUSD&account=primary&daily_shortlist=${setup.selection.daily_id}&scanner_campaign=${setup.campaign_id}`);
    await daily().locator(`[data-daily-id="${setup.selection.daily_id}"]`).waitFor();
  };
  const review = async selection => {
    const detail = daily().locator("details").filter({ has: page.locator("summary").filter({ hasText: new RegExp(`original #${selection.event_seq}$`) }) }).first();
    if (await detail.getAttribute("open") === null) await detail.locator(":scope > summary").click();
    const response = waitApi("GET", url => url.pathname.endsWith("/comparison-source") && url.searchParams.get("event_seq") === String(selection.event_seq));
    await detail.getByRole("button", { name: "Review prospective comparison", exact: true }).click();
    const actual = await response;
    save("last-comparison-source-status.json", { status: actual.status(), url: actual.url() });
    assert.equal(actual.status(), 200);
    const body = await bounded(actual.json(), 5000, "Comparison source body deadline reached");
    save("last-comparison-source-response.json", { status: actual.status(), body });
    assert.deepEqual(body.finding.selection, selection); assert.equal(body.financial_authority, false);
    await panel().getByRole("button", { name: "Prepare fixed comparison", exact: true }).waitFor();
    return body;
  };
  const prepare = async expectedStatus => {
    const response = waitApi("POST", url => url.pathname === "/api/research/pattern-scanner/comparisons");
    await panel().getByRole("button", { name: "Prepare fixed comparison", exact: true }).click();
    const actual = await response; assert.equal(actual.status(), expectedStatus);
    const command = actual.request().postDataJSON(); const value = await actual.json();
    assert.match(command.request_id, /^[a-f0-9-]{36}$/); return { command, value };
  };
  const history = async () => {
    const details = panel().locator("details").filter({ has: page.locator("summary").filter({ hasText: /^Saved immutable preparations$/ }) });
    if (await details.getAttribute("open") === null) await details.locator(":scope > summary").click();
    const response = waitApi("GET", url => url.pathname === "/api/research/pattern-scanner/comparisons");
    await details.getByRole("button", { name: "Read saved preparations", exact: true }).click();
    const actual = await response; assert.equal(actual.status(), 200); return actual.json();
  };
  const reopen = async id => {
    await history();
    const response = waitApi("GET", url => url.pathname === `/api/research/pattern-scanner/comparisons/${id}`);
    await panel().getByRole("button", { name: `Reopen preparation ${id}`, exact: true }).click();
    const actual = await response; assert.equal(actual.status(), 200); const value = await actual.json();
    await panel().getByText(`Original UUID ${id}`, { exact: false }).waitFor();
    return value;
  };
  const assertSupported = value => {
    assert.equal(value.status, "supported"); assert.equal(value.submitted, false); assert.equal(value.financial_authority, false);
    assert.equal(value.evaluation.matched_inputs.count, 600); assert.equal(value.evaluation.matched_inputs.archive_verified, true);
    assert.equal(value.finding.native_proof.recognition_rows, 21); assert.equal(value.finding.native_proof.pivot_rows, 5);
    assert.equal(value.finding.native_proof.archive_verified, true);
    assert.equal(value.proposal.strategy.family, "breakout-retest-v1"); assert.equal(value.proposal.reference.family, "cost-breakout-v1");
  };
  try {
    browser = await chromium.launch({ headless: true, executablePath: process.env.QTRADES_BROWSER_QA_EXECUTABLE || undefined });
    receipt.runtime = { playwright: require("playwright/package.json").version, browser: browser.version() };
    await bounded((async () => {
      const initial = await probe(); save("initial-probe.json", initial);
      phase = "recognized-card-read-only-review";
      await fresh(initial); const described = await review(initial.selection); save("described-source.json", described);
      assert.equal((await probe()).posts.length, 0);
      assert(await panel().innerText().then(text => text.includes("different mechanisms") && text.includes("six hours") && text.includes("24-hour")));
      groups.push({ name: phase, automatic_posts: 0, recognition_rows: 21, original_native_candles: 32 });

      if (!readOnly) {
      phase = "one-explicit-supported-preparation-no-inbox-effect";
      const supported = await prepare(200); assertSupported(supported.value); save("supported-preparation.json", supported.value);
      await panel().getByText("Preparation supported by the captured numerical check", { exact: true }).waitFor();
      assert.equal((await probe()).posts.length, 1); assert.equal((await probe()).lab_inbox_count, 0);
      groups.push({ name: phase, request_id: supported.command.request_id, post_count: 1, execution_minutes: 600, inbox_count: 0 });
      await page.evaluate(() => { document.activeElement?.blur(); const element = document.querySelector("#pattern-comparison-panel");
        const caption = document.createElement("p"); caption.className = "station-kicker"; caption.textContent = "SOURCE QA · SYNTHETIC 32 NATIVE CANDLES / 600 CURRENT MINUTES · NO EXPERIMENT OR PROFITABILITY PROOF"; element.prepend(caption); });
      await page.setViewportSize({ width: 1440, height: 2300 }); await panel().screenshot({ path: path.join(directory, "comparison-supported.png") });

      phase = "lost-ack-reload-history-get-exact-original-uuid";
      await mode("lost_ack"); await fresh(initial); await review(initial.selection);
      const lost = await prepare(503); await panel().getByRole("button", { name: "Find original preparation result", exact: true }).waitFor();
      const rawPending = await page.evaluate(() => localStorage.getItem("qtrades-pattern-comparison-pending-v1"));
      assert.deepEqual(JSON.parse(rawPending), lost.command); save("lost-ack-original-command.json", lost.command);
      await page.reload(); await panel().getByRole("button", { name: "Find original preparation result", exact: true }).waitFor();
      const recovered = await reopen(lost.command.request_id); assertSupported(recovered); save("lost-ack-original-recovered.json", recovered);
      assert.equal(await page.evaluate(() => localStorage.getItem("qtrades-pattern-comparison-pending-v1")), null);
      assert.equal((await probe()).posts.length, 2);
      await page.reload(); await panel().getByText(`Original UUID ${lost.command.request_id}`, { exact: false }).waitFor();
      assert.equal((await probe()).posts.length, 2);
      groups.push({ name: phase, request_id: lost.command.request_id, total_posts: 2, pending_cleared_by_canonical_original_get: true, bookmark_reload_get_only: true });

      phase = "reopen-original-after-current-source-unavailable";
      await mode("source_drift"); const drifted = await reopen(lost.command.request_id); assert.deepEqual(drifted, recovered);
      assert.equal((await probe()).posts.length, 2); save("source-drift-original-reopen.json", drifted); await mode("restore_source");
      groups.push({ name: phase, immutable_original_equal: true, new_posts: 0 });

      phase = "corrupt-ack-retained-and-exact-get-recovery";
      await mode("corrupt_ack"); await fresh(initial); await review(initial.selection); const corrupt = await prepare(200);
      await panel().getByText(/acknowledgment does not match/).waitFor();
      assert.equal(JSON.parse(await page.evaluate(() => localStorage.getItem("qtrades-pattern-comparison-pending-v1"))).request_id, corrupt.command.request_id);
      const exact = await reopen(corrupt.command.request_id); assertSupported(exact); save("corrupt-ack-exact-recovery.json", exact);
      assert.equal((await probe()).posts.length, 3); groups.push({ name: phase, original_id: corrupt.command.request_id, mismatched_ack_not_adopted: true, get_recovered: true });

      phase = "late-ack-does-not-replace-another-selected-daily-card";
      await mode("delay_ack"); await fresh(initial); await review(initial.selection);
      const lateResponse = waitApi("POST", url => url.pathname === "/api/research/pattern-scanner/comparisons");
      await panel().getByRole("button", { name: "Prepare fixed comparison", exact: true }).click();
      let held; for (let tries = 0; tries < 20; tries++) { held = await probe(); if (held.delayed?.committed) break; await new Promise(resolve => setTimeout(resolve, 100)); }
      assert.equal(held.delayed.committed, true);
      const earlier = held.daily_snapshots.rows.find(row => row.id !== initial.selection.daily_id); assert(earlier);
      const savedDays = daily().locator("details").filter({ has: page.locator("summary").filter({ hasText: /^Earlier immutable daily shortlists$/ }) });
      await savedDays.locator(":scope > summary").click(); await savedDays.getByRole("button", { name: "Read saved daily shortlists", exact: true }).click();
      await savedDays.getByLabel("Saved daily shortlist").selectOption(earlier.id);
      await savedDays.getByRole("button", { name: "Reopen exact daily shortlist", exact: true }).click();
      await daily().locator(`[data-daily-id="${earlier.id}"]`).waitFor(); await mode("release_ack");
      assert.equal((await lateResponse).status(), 200);
      await panel().getByText(/other original preparation was acknowledged/).waitFor();
      assert.equal(await daily().locator(`[data-daily-id="${earlier.id}"]`).count(), 1);
      assert.equal(await panel().getByText("Preparation supported by the captured numerical check", { exact: true }).count(), 0);
      groups.push({ name: phase, original_id: held.delayed.request_id, selected_daily_unchanged: earlier.id, acknowledged_receipt_did_not_publish_over_new_card: true });

      phase = "original-daily-navigation-and-mobile";
      await reopen(held.delayed.request_id); await panel().getByRole("button", { name: "Return to original daily finding", exact: true }).click();
      await daily().locator(`[data-daily-id="${initial.selection.daily_id}"]`).waitFor();
      const restored = new URLSearchParams(new URL(page.url()).hash.split("?")[1]);
      assert.equal(restored.get("daily_shortlist"), initial.selection.daily_id); assert.equal(restored.get("scanner_chart_seq"), String(initial.selection.event_seq));
      assert.equal(restored.get("scanner_chart_kind"), initial.selection.event_kind); assert.equal(restored.get("scanner_chart_frame"), "5m");
      await page.setViewportSize({ width: 390, height: 844 });
      save("mobile-geometry.json", await panel().evaluate(element => ({ width: element.clientWidth, scrollWidth: element.scrollWidth,
        children: [...element.querySelectorAll("p,span,button")].map(child => ({ text: child.textContent.slice(0, 100), width: child.clientWidth, scrollWidth: child.scrollWidth })).filter(child => child.scrollWidth > child.width) })));
      await page.waitForFunction(() => { const element = document.querySelector("#pattern-comparison-panel"); return element.scrollWidth <= element.clientWidth; }, null, { timeout: 5000 });
      await panel().screenshot({ path: path.join(directory, "comparison-mobile.png") });
      groups.push({ name: phase, original_daily_reopened: true, historical_chart_identity_preserved: true, mobile_width: 390, horizontal_overflow: false });

      phase = "immutable-waits-and-explicit-separate-current-observations";
      await mode("normal"); await mode("waiting_inputs"); await fresh(initial); await review(initial.selection);
      const waitOne = await prepare(200); assert.equal(waitOne.value.status, "waiting"); save("original-wait-1.json", waitOne.value);
      await panel().getByText("Preparation waiting", { exact: true }).waitFor();
      await panel().getByRole("button", { name: "Review a separate current observation", exact: true }).click();
      await panel().getByText(/Reviewing a separate current observation/).waitFor();
      const waitTwo = await prepare(200); assert.equal(waitTwo.value.status, "waiting"); assert.notEqual(waitOne.command.request_id, waitTwo.command.request_id); save("original-wait-2.json", waitTwo.value);
      await panel().getByText("Preparation waiting", { exact: true }).waitFor(); await mode("restore_source");
      await panel().getByRole("button", { name: "Review a separate current observation", exact: true }).click();
      const ready = await prepare(200); assertSupported(ready.value); save("separate-current-supported.json", ready.value);
      assert.notEqual(ready.command.request_id, waitOne.command.request_id); assert.notEqual(ready.command.request_id, waitTwo.command.request_id);
      const originalOne = await reopen(waitOne.command.request_id); assert.deepEqual(originalOne, waitOne.value);
      const originalTwo = await reopen(waitTwo.command.request_id); assert.deepEqual(originalTwo, waitTwo.value);
      groups.push({ name: phase, original_wait_ids: [waitOne.command.request_id, waitTwo.command.request_id], separate_explicit_supported_id: ready.command.request_id, original_waits_unchanged: true, no_automatic_upgrade_or_post: true });

      phase = "unknown-post-and-404-get-remain-unresolved-without-retry";
      await mode("unknown"); await fresh(initial); await review(initial.selection); const unknown = await prepare(503);
      const unknownGet = waitApi("GET", url => url.pathname === `/api/research/pattern-scanner/comparisons/${unknown.command.request_id}`);
      await panel().getByRole("button", { name: "Find original preparation result", exact: true }).click(); assert.equal((await unknownGet).status(), 404);
      await panel().getByText(/absence does not establish/).waitFor();
      assert.deepEqual(JSON.parse(await page.evaluate(() => localStorage.getItem("qtrades-pattern-comparison-pending-v1"))), unknown.command);
      assert.equal((await probe()).posts.length, 8); groups.push({ name: phase, retained_uuid: unknown.command.request_id, get_status: 404, total_posts: 8, original_unknown_not_repeated: true });
      }

      phase = "unchanged-financial-and-no-dispatch-final-bind";
      const final = await probe(); save("final-probe.json", final);
      assert.equal(final.financial_state_unchanged, true); assert.equal(final.auxiliary_dashboard_state_unchanged, true);
      assert.equal(final.lab_inbox_count, 0); assert.equal(final.model_calls, 0); assert.equal(final.financial_database, false);
      assert.deepEqual(final.source_hashes_after, final.source_hashes); assert.deepEqual(pageErrors, []); assert.deepEqual(externalRequests, []);
      if (readOnly) {
        assert.equal(final.posts.length, 0); assert.equal(final.retained_preparations.length, 0);
        assert.equal(final.role_tasks, 0); assert.equal(final.role_attempts, 0);
        assert.deepEqual(final.comparison_owner, { same_bridge: true, scanner_matches: true,
          registry_matches: true, controller_matches: true, worker_enabled: false, transport_configured: false });
        assert(apiRequests.every(request => request.method === "GET"));
      }
      groups.push({ name: phase, retained_preparations: final.retained_preparations.length, native_source_calls: final.native_calls.length,
        financial_state_unchanged: true, lab_inbox_count: 0, model_calls: 0, source_and_compiled_unchanged: true });
      receipt.passed = true;
    })(), 150000, "Finite preparation browser QA deadline reached");
  } catch (error) {
    failure = { phase, name: error.name, message: error.message }; receipt.passed = false;
    if (page) {
      try { fs.writeFileSync(path.join(directory, "failure-dom.txt"), await page.locator("body").innerText({ timeout: 5000 })); } catch {}
      try { await page.screenshot({ path: path.join(directory, "failure.png"), fullPage: true, timeout: 5000 }); } catch {}
      try { await panel().screenshot({ path: path.join(directory, "failure-panel.png"), timeout: 5000 }); } catch {}
    }
    try { save("failure-probe.json", await probe()); } catch {}
  } finally {
    try { receipt.stop_status = (await fetch(`${origin}/__qa/stop`, { method: "POST", headers, signal: AbortSignal.timeout(5000) })).status; }
    catch (error) { receipt.stop_error = error.name; }
    if (receipt.stop_status !== 200) cleanupFailures.push("Disposable server stop was not acknowledged with HTTP200");
    if (context) {
      try { await bounded(context.close(), 10000, "Context close unconfirmed"); receipt.context_closed = true; }
      catch (error) { receipt.context_close_error = error.name; cleanupFailures.push("Browser context close unconfirmed"); }
    } else receipt.context_not_created = true;
    if (browser) {
      try { await bounded(browser.close(), 10000, "Browser close unconfirmed"); receipt.browser_closed = true; }
      catch (error) { receipt.browser_close_error = error.name; cleanupFailures.push("Browser close unconfirmed"); }
    } else receipt.browser_not_created = true;
    if (cleanupFailures.length) receipt.passed = false;
    receipt.failure = failure;
    receipt.artifacts = Object.fromEntries(fs.readdirSync(directory).filter(name => name !== "receipt.json").map(name => [name, sha(fs.readFileSync(path.join(directory, name)))]));
    save("receipt.json", receipt);
  }
  if (failure || cleanupFailures.length) { process.stderr.write(`${failure ? `${failure.phase}: ${failure.message}` : "Cleanup gate failed"}\n${cleanupFailures.join("\n")}\n`); process.exitCode = 1; }
  else process.stdout.write(`Passed ${groups.length} preparation UI groups; synthetic native/current inputs only.\n`);
})();
