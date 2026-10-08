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
const researchObservation = process.env.QTRADES_PATTERN_COMPARISON_QA_RESEARCH_OBSERVATION === "1";
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
    research_observation_affected_groups: researchObservation,
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
    const actual = await response; assert.equal(actual.status(), 200); return researchObservation ? bounded(actual.json(), 5000, "Readonly history body deadline") : actual.json();
  };
  const reopen = async id => {
    await history();
    const response = waitApi("GET", url => url.pathname === `/api/research/pattern-scanner/comparisons/${id}`);
    await panel().getByRole("button", { name: `Reopen preparation ${id}`, exact: true }).click();
    const actual = await response; assert.equal(actual.status(), 200); const value = await (researchObservation ? bounded(actual.json(), 5000, "Readonly original body deadline") : actual.json());
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
      if (researchObservation) {
      const setup = initial.research_observation; assert(setup);
      assert.equal(initial.lab_inbox_count, 1); assert.equal(initial.retained_preparations.length, 3);
      assert.equal(initial.role_tasks, 0); assert.equal(initial.role_attempts, 0);
      phase = "saved-readonly-observation-history-exact-mode";
      await fresh(initial);
      const readonly = await reopen(setup.research_request_id); save("readonly-original.json", readonly);
      assert.equal(readonly.status, "research_only"); assert.equal(readonly.research_only, true);
      assert.equal(readonly.proposal, null); assert.equal(readonly.dispatch_available, false);
      assert.equal(readonly.evaluation.status, "supported_research_observation");
      assert.equal(readonly.evaluation.matched_inputs.count, 600);
      assert.equal(readonly.evaluation.matched_inputs.archive_verified, true);
      const command = { ...readonly.finding.selection, request_id: readonly.request_id, expected_finding_sha256: readonly.finding_sha256 };
      const sorted = Object.fromEntries(Object.entries(command).sort(([a], [b]) => a.localeCompare(b)));
      assert.equal(readonly.intent_sha256, sha(JSON.stringify({ command: sorted, research_only: true })));
      for (const control of [readonly.evaluation.controls.candidate, readonly.evaluation.controls.reference]) {
        assert.equal(control.proposal, undefined); assert(control.proposal_without_bundle_digest);
      }
      await panel().getByText("Read-only research observation", { exact: true }).waitFor();
      assert.equal(await panel().getByRole("button", { name: "Prepare fixed comparison", exact: true }).count(), 0);
      assert.equal(await panel().getByRole("button", { name: "Review a separate current observation", exact: true }).count(), 0);
      await panel().getByText("Read-only fixed comparison template", { exact: true }).click();
      assert(await panel().innerText().then(text => text.includes("Dispatch unavailable") && text.includes("600 closed minute candles")));
      assert.equal(await page.evaluate(() => localStorage.getItem("qtrades-pattern-comparison-receipt-v1")), null);
      groups.push({ name: phase, request_id: readonly.request_id, mode_bound_intent_verified: true, proposal_null: true, dispatch_available: false, displayed_current_inputs: 600, no_prepare_control: true });
      await page.evaluate(() => { document.activeElement?.blur(); const element = document.querySelector("#pattern-comparison-panel");
        const caption = document.createElement("p"); caption.className = "station-kicker"; caption.textContent = "SOURCE QA · SYNTHETIC NATIVE FINDING / 600 CURRENT MINUTES · READ-ONLY OBSERVATION · NO MODEL OR FUNDED COMPARISON"; element.prepend(caption); });
      await page.setViewportSize({ width: 1440, height: 2400 }); await panel().screenshot({ path: path.join(directory, "comparison-research-observation.png") });

      phase = "same-finding-digest-race-preserves-latest-selected-uuid";
      await page.evaluate(() => {
        const original = crypto.subtle.digest.bind(crypto.subtle);
        globalThis.__qaReadonlyDigest = { holdNext: true, entered: false, finished: false, release: null };
        crypto.subtle.digest = async (...args) => {
          const held = globalThis.__qaReadonlyDigest;
          let delayed = false;
          if (held.holdNext && new TextDecoder().decode(args[1]).includes('"research_only":true')) {
            held.holdNext = false; held.entered = true; delayed = true;
            await new Promise(resolve => { held.release = resolve; });
          }
          const result = await original(...args); if (delayed) held.finished = true; return result;
        };
      });
      await history();
      await panel().getByRole("button", { name: `Reopen preparation ${readonly.request_id}`, exact: true }).click();
      await page.waitForFunction(() => globalThis.__qaReadonlyDigest?.entered === true, null, { timeout: 5000 });
      const waitingUrl = new URL(page.url()); const waitingParams = new URLSearchParams(waitingUrl.hash.split("?")[1]);
      waitingParams.set("pattern_comparison_request", setup.waiting_request_id); waitingUrl.hash = `markets?${waitingParams}`;
      const laterOriginal = waitApi("GET", url => url.pathname === `/api/research/pattern-scanner/comparisons/${setup.waiting_request_id}`);
      await page.goto(waitingUrl.href); assert.equal((await laterOriginal).status(), 200);
      await panel().getByText("Read-only research observation waiting", { exact: true }).waitFor();
      await page.evaluate(() => globalThis.__qaReadonlyDigest.release());
      await page.waitForFunction(() => globalThis.__qaReadonlyDigest?.finished === true, null, { timeout: 5000 });
      await bounded(page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))),
        5000, "Readonly published-state render deadline");
      await page.waitForFunction(id => new URLSearchParams(location.hash.split("?")[1]).get("pattern_comparison_request") === id,
        setup.waiting_request_id, { timeout: 5000 });
      await panel().getByText("Read-only research observation waiting", { exact: true }).waitFor();
      assert.equal(await panel().getByText(`Original UUID ${readonly.request_id}`, { exact: false }).count(), 0);
      groups.push({ name: phase, original_body_get_real: true, digest_boundary_held_in_qa: true, latest_selected_uuid: setup.waiting_request_id, older_digest_did_not_publish: true });
      await reopen(readonly.request_id);

      phase = "readonly-exact-bookmark-reload-after-current-source-drift";
      await mode("source_drift");
      await page.evaluate(() => {
        const original = fetch.bind(window);
        globalThis.__qaReadonlySource = { entered: false, released: false, release: null, status: null, body: null };
        window.fetch = async (...args) => {
          const actual = await original(...args);
          if (new URL(actual.url).pathname.endsWith("/comparison-source")) {
            const held = globalThis.__qaReadonlySource;
            held.status = actual.status; held.body = await actual.clone().text(); held.entered = true;
            await new Promise(resolve => { held.release = resolve; });
            held.released = true;
          }
          return actual; // Hold the actual server refusal; do not fabricate its body or status.
        };
      });
      const sourceDetails = daily().locator("details").filter({ has: page.locator("summary").filter({ hasText: new RegExp(`original #${initial.selection.event_seq}$`) }) }).first();
      if (await sourceDetails.getAttribute("open") === null) await sourceDetails.locator(":scope > summary").click();
      await sourceDetails.getByRole("button", { name: "Review prospective comparison", exact: true }).click();
      await page.waitForFunction(() => globalThis.__qaReadonlySource?.entered === true, null, { timeout: 5000 });
      const heldRefusal = await bounded(page.evaluate(() => ({ status: globalThis.__qaReadonlySource.status, body: globalThis.__qaReadonlySource.body })),
        5000, "Actual source refusal capture deadline");
      save("late-comparison-source-refusal.json", heldRefusal);
      assert.equal(heldRefusal.status, 422); assert.equal(typeof JSON.parse(heldRefusal.body).detail, "string");
      const originalUrl = new URL(page.url()); const originalParams = new URLSearchParams(originalUrl.hash.split("?")[1]);
      originalParams.set("pattern_comparison_request", readonly.request_id); originalUrl.hash = `markets?${originalParams}`;
      const adoptedResponse = waitApi("GET", url => url.pathname === `/api/research/pattern-scanner/comparisons/${readonly.request_id}`);
      await page.goto(originalUrl.href); assert.equal((await adoptedResponse).status(), 200);
      await panel().getByText("Read-only research observation", { exact: true }).waitFor();
      await page.evaluate(() => globalThis.__qaReadonlySource.release());
      await page.waitForFunction(() => globalThis.__qaReadonlySource?.released === true, null, { timeout: 5000 });
      await bounded(page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))),
        5000, "Late source refusal render deadline");
      assert.equal(await panel().getByRole("alert").count(), 0);
      await panel().getByText(`Original UUID ${readonly.request_id}`, { exact: false }).waitFor();
      const recoveredResponse = waitApi("GET", url => url.pathname === `/api/research/pattern-scanner/comparisons/${readonly.request_id}`);
      await page.reload(); const recovered = await recoveredResponse; assert.equal(recovered.status(), 200);
      assert.deepEqual(await bounded(recovered.json(), 5000, "Readonly body deadline"), readonly);
      await panel().getByText("Read-only research observation", { exact: true }).waitFor();
      assert.equal(new URLSearchParams(new URL(page.url()).hash.split("?")[1]).get("pattern_comparison_request"), readonly.request_id);
      assert.equal((await probe()).posts.length, 0); await mode("restore_source");
      const ordinary = await reopen(setup.ordinary_request_id); assertSupported(ordinary);
      await panel().getByText("Preparation supported by the captured numerical check", { exact: true }).waitFor();
      assert.equal(ordinary.research_only, undefined);
      groups.push({ name: phase, immutable_readonly_equal: true, exact_bookmark: readonly.request_id, ordinary_receipt_validation_unchanged: true, browser_posts: 0,
        actual_source_refusal_status: heldRefusal.status, source_refusal_held_until_sealed_receipt_adopted: true, late_source_alert_not_published: true });

      phase = "readonly-wait-has-no-new-observation-write-control";
      const waiting = await reopen(setup.waiting_request_id); save("readonly-original-wait.json", waiting);
      assert.equal(waiting.research_only, true); assert.equal(waiting.status, "waiting"); assert.equal(waiting.proposal, null);
      await panel().getByText("Read-only research observation waiting", { exact: true }).waitFor();
      assert.equal(await panel().getByRole("button", { name: "Review a separate current observation", exact: true }).count(), 0);
      assert.equal(await panel().getByRole("button", { name: "Prepare fixed comparison", exact: true }).count(), 0);
      await panel().getByRole("button", { name: "Return to original daily finding", exact: true }).click();
      await daily().locator(`[data-daily-id="${initial.selection.daily_id}"]`).waitFor();
      assert.equal(new URLSearchParams(new URL(page.url()).hash.split("?")[1]).get("daily_shortlist"), initial.selection.daily_id);
      await reopen(readonly.request_id); await page.setViewportSize({ width: 390, height: 844 });
      assert.equal(await bounded(panel().evaluate(element => element.scrollWidth <= element.clientWidth), 5000, "Readonly geometry deadline"), true);
      await panel().screenshot({ path: path.join(directory, "comparison-research-mobile.png") });
      groups.push({ name: phase, original_wait_not_upgraded: waiting.request_id, no_new_observation_control: true, original_finding_navigation: true, mobile_no_horizontal_overflow: true });
      } else {
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
      }

      phase = "unchanged-financial-and-no-dispatch-final-bind";
      const final = await probe(); save("final-probe.json", final);
      assert.equal(final.financial_state_unchanged, true); assert.equal(final.auxiliary_dashboard_state_unchanged, true);
      assert.equal(final.lab_inbox_count, researchObservation ? 1 : 0); assert.equal(final.model_calls, 0); assert.equal(final.financial_database, false);
      assert.deepEqual(final.source_hashes_after, final.source_hashes); assert.deepEqual(pageErrors, []); assert.deepEqual(externalRequests, []);
      if (readOnly) {
        assert.equal(final.posts.length, 0); assert.equal(final.retained_preparations.length, 0);
        assert.equal(final.role_tasks, 0); assert.equal(final.role_attempts, 0);
        assert.deepEqual(final.comparison_owner, { same_bridge: true, scanner_matches: true,
          registry_matches: true, controller_matches: true, worker_enabled: false, transport_configured: false });
        assert(apiRequests.every(request => request.method === "GET"));
      }
      if (researchObservation) {
        assert.equal(final.posts.length, 0); assert.deepEqual(final.retained_preparations, initial.retained_preparations);
        assert.equal(final.role_tasks, 0); assert.equal(final.role_attempts, 0);
        assert(apiRequests.every(request => request.method === "GET"));
      }
      groups.push({ name: phase, retained_preparations: final.retained_preparations.length, native_source_calls: final.native_calls.length,
        financial_state_unchanged: true, lab_inbox_count: final.lab_inbox_count, model_calls: 0, source_and_compiled_unchanged: true });
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
