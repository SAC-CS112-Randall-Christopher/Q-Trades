// Compiled chart UI + real disposable scanner registry; all source inputs are synthetic.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { chromium } = require("playwright");
const origin = process.env.QTRADES_BROWSER_QA_ORIGIN || "http://127.0.0.1:58970";
const directory = process.env.QTRADES_BROWSER_QA_OUTPUT;
const token = process.env.QTRADES_BROWSER_QA_TOKEN;
const sha = bytes => crypto.createHash("sha256").update(bytes).digest("hex");
const frames = ["5m", "15m", "30m", "1h", "4h"];

(async () => {
  assert(directory && token, "Task-owned output and explicit QA token are required");
  const address = new URL(origin);
  assert.equal(address.hostname, "127.0.0.1");
  assert(!["8780", "5432", "54544", "58968", "58969"].includes(address.port));
  fs.mkdirSync(directory, { recursive: false });
  const groups = [], pageErrors = [], externalRequests = [], apiRequests = [];
  const receipt = { evidence_kind: "compiled_saved_scanner_charts_actual_registry_synthetic_native_inputs",
    operating_acceptance: false, financial_database: false, model_calls: 0,
    historical_account_or_archive_acceptance: false, full_year_all_market_capacity: false,
    profitability_or_strategy_approval: false, harness_sha256: sha(fs.readFileSync(__filename)),
    groups, pageErrors, externalRequests, apiRequests };
  const save = (name, value) => fs.writeFileSync(path.join(directory, name), JSON.stringify(value, null, 2));
  const headers = { "x-qa-token": token };
  let browser, context, page, failure = null, phase = "startup";
  const bounded = async (operation, label, timeout = 10000) => {
    let timer;
    try {
      return await Promise.race([operation, new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error(`Finite QA operation expired: ${label}`)), timeout);
      })]);
    } finally { clearTimeout(timer); }
  };
  const jsonResponse = response => bounded(response.json(), "response JSON body");
  const lifetime = setTimeout(() => {
    failure ||= { phase, name: "FiniteWorkflowDeadline", message: "The isolated workflow exceeded its five-minute work budget." };
    receipt.work_deadline_exceeded = true;
    if (browser) void browser.close().catch(error => { receipt.deadline_close_error = error.message; });
  }, 300000);
  try {
    browser = await chromium.launch({ headless: true, executablePath: process.env.QTRADES_BROWSER_QA_EXECUTABLE || undefined });
    receipt.runtime = { playwright: require("playwright/package.json").version, browser: browser.version() };
    context = await browser.newContext({ viewport: { width: 2133, height: 950 }, serviceWorkers: "block" });
    await context.route("**/*", route => {
      const requested = new URL(route.request().url());
      if (requested.origin !== origin) { externalRequests.push(requested.origin); return route.abort(); }
      return route.continue(); // Successful API bodies are never fabricated.
    });
    page = await context.newPage(); page.setDefaultTimeout(12000);
    page.on("pageerror", error => pageErrors.push(error.message));
    page.on("request", request => {
      const url = new URL(request.url());
      if (url.pathname.startsWith("/api/") && apiRequests.length < 2000)
        apiRequests.push({ method: request.method(), path: url.pathname, query: url.search });
    });
    const qa = async (action, timeout = 10000) => {
      const response = await page.request.post(`${origin}/__qa/${action}`, { headers, timeout });
      const raw = await response.text();
      save(`qa-${action}-response.json`, { status: response.status(), body: raw });
      assert.equal(response.status(), 200, `QA ${action} returned HTTP ${response.status()}: ${raw}`);
      const result = JSON.parse(raw);
      return result;
    };
    const probe = async () => jsonResponse(await page.request.get(`${origin}/__qa/probe`, { headers, timeout: 10000 }));
    const workspace = () => page.getByRole("region", { name: "Year pattern scanner" });
    const grid = () => page.getByRole("region", { name: "Saved scanner pattern charts" });
    const card = frame => grid().getByRole("article", { name: `${frame} scanner chart`, exact: true });
    const getChart = async (campaign, symbol, frame, extra = {}) => {
      const query = new URLSearchParams({ campaign_id: campaign, symbol, timeframe: frame, ...extra });
      const response = await page.request.get(`${origin}/api/research/pattern-scanner/chart?${query}`);
      const result = await jsonResponse(response); assert.equal(response.status(), 200, JSON.stringify(result));
      assert.equal(result.campaign_id, campaign); assert.equal(result.symbol, symbol); assert.equal(result.timeframe, frame);
      assert.equal(result.financial_authority, false);
      return result;
    };
    const observeResponse = predicate => {
      const response = page.waitForResponse(predicate);
      // A preceding click may fail its own stability check before this wait is
      // awaited. Retain that click failure through the main catch/finally.
      void response.catch(() => {});
      return response;
    };
    const waitChart = (symbol, frame, key = null) => observeResponse(response => {
      const url = new URL(response.url());
      return url.pathname === "/api/research/pattern-scanner/chart" && url.searchParams.get("symbol") === symbol &&
        url.searchParams.get("timeframe") === frame && (key == null || url.searchParams.has(key));
    });
    const waitPlots = async () => {
      assert.equal(await grid().getByRole("article").count(), 5);
      for (const frame of frames) await card(frame).locator("canvas").first().waitFor();
    };
    const plotProof = async frame => {
      const host = card(frame).locator(".candle-study-chart [role=img][data-pattern-ids][data-level-segments]");
      await host.waitFor();
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      return host.evaluate(element => {
      const canvases = [...element.querySelectorAll("canvas")];
      return { dataset: { ...element.dataset }, canvases: canvases.map(canvas => {
        const context = canvas.getContext("2d");
        if (!context) return { width: canvas.width, height: canvas.height, drawn: false };
        const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
        let opaque = 0, varied = 0;
        for (let i = 0; i < pixels.length; i += 4) { if (pixels[i + 3]) opaque++; if (pixels[i] !== pixels[0] || pixels[i + 1] !== pixels[1] || pixels[i + 2] !== pixels[2]) varied++; }
        return { width: canvas.width, height: canvas.height, opaque, varied, drawn: opaque > 100 && varied > 100 };
      }) };
      });
    };

    phase = "actual-owner-setup-and-read-only-opening";
    const setup = await qa("chart_setup", 55000); save("synthetic-setup.json", setup);
    assert.equal(setup.status, "prepared"); assert.equal(setup.progress.length, 10);
    assert(setup.progress.every(row => row.observed_bars >= 260)); assert.equal(setup.full_year_complete, false);
    const before = await probe(); save("before-browser.json", before);
    let densePreservation = before;
    assert.equal(before.posts.length, 0); assert.equal(before.financial_database, false);
    assert.equal(before.synthetic_lab_account_projection, true); assert.equal(before.state.enabled, false);
    await page.goto(`${origin}/#markets`); await workspace().waitFor(); await grid().waitFor(); await waitPlots();
    groups.push({ name: phase, actual_scanner_setup_controls: before.setup_controls.length, scopes: 10, full_year_complete: false, browser_api_posts: 0 });

    phase = "prominent-discovery-and-five-native-cards";
    await page.evaluate(() => scrollTo(0, 0));
    const discovery = await page.getByRole("button", { name: "Analysis & alert charts", exact: true }).boundingBox();
    assert(discovery && discovery.y >= 0 && discovery.y < 950, JSON.stringify(discovery));
    await page.getByRole("button", { name: "Analysis & alert charts", exact: true }).click();
    const heading = workspace().getByRole("heading", { name: "Year pattern scanner", exact: true });
    assert(await heading.isVisible());
    await page.waitForFunction(() => { const node = document.getElementById("pattern-scanner-title"); return node && node.getBoundingClientRect().top >= 0 && node.getBoundingClientRect().top < 250; });
    const order = await grid().getByRole("article").evaluateAll(elements => elements.map(e => e.getAttribute("aria-label")));
    assert.deepEqual(order, frames.map(frame => `${frame} scanner chart`));
    const charts = {}, plots = {};
    for (const frame of frames) {
      charts[frame] = await getChart(setup.campaign_id, "BTCUSD", frame);
      assert(charts[frame].candles.length > 0 && charts[frame].candles.length <= 100);
      assert(charts[frame].candles.every(row => row.close_ms <= charts[frame].processed_through_ms));
      plots[frame] = await plotProof(frame); assert(plots[frame].canvases.some(canvas => canvas.drawn), JSON.stringify(plots[frame]));
      const segments = JSON.parse(plots[frame].dataset.levelSegments);
      const markerIds = JSON.parse(plots[frame].dataset.patternIds);
      const indicators = JSON.parse(plots[frame].dataset.indicatorSegments);
      for (const key of ["sma10", "sma50", "sma100", "vwap"])
        assert.equal(indicators[key].reduce((n, segment) => n + segment.points, 0), charts[frame].indicators.points.filter(point => point[key] !== null).length);
      const visibleTimes = new Set(charts[frame].candles.map(row => row.open_ms));
      const events = [...charts[frame].patterns.rows, ...charts[frame].alerts.rows].filter(row => visibleTimes.has(row.bar_open_ms));
      assert.deepEqual(markerIds, events.map(row => row.id));
      assert.equal(Number(plots[frame].dataset.patternCount), events.length);
      assert.equal(Number(plots[frame].dataset.markerCount), new Set(events.map(row => row.bar_open_ms)).size);
      assert(segments.length > 0 && markerIds.length > 0, JSON.stringify(plots[frame].dataset));
      for (const segment of segments) {
        const level = charts[frame].levels.rows.find(row => segment.id.startsWith(row.id + ":"));
        assert(level && segment.from >= level.first_usable_ms && segment.to >= segment.from);
        assert(visibleTimes.has(segment.from) && visibleTimes.has(segment.to));
      }
    }
    save("latest-native-charts.json", charts); save("five-rendered-plots.json", plots);
    const geometry = await workspace().evaluate(async element => {
      const button = [...element.querySelectorAll("button")].find(item => item.textContent === "Inspect saved evidence");
      const samples = [];
      for (let sample = 0; sample < 8; sample++) {
        await new Promise(resolve => requestAnimationFrame(() => setTimeout(resolve, 100)));
        samples.push({ inspectDocumentTop: button.getBoundingClientRect().top + scrollY,
          chartHeights: [...element.querySelectorAll(".candle-chart-card .candle-study-chart [role=img]")].map(host => host.getBoundingClientRect().height) });
      }
      return samples;
    });
    save("real-chart-geometry-stability.json", geometry);
    assert.equal(geometry[0].chartHeights.length, 5);
    assert(Math.max(...geometry.map(row => row.inspectDocumentTop)) - Math.min(...geometry.map(row => row.inspectDocumentTop)) <= 1,
      "Normal Inspect click requires stable geometry below the actual rendered chart grid");
    for (let index = 0; index < 5; index++)
      assert(Math.max(...geometry.map(row => row.chartHeights[index])) - Math.min(...geometry.map(row => row.chartHeights[index])) <= 1);
    groups.push({ name: "real-five-chart-host-and-inspect-geometry-stability", samples: geometry.length,
      chart_heights: geometry[0].chartHeights, stable_inspect_document_top: geometry[0].inspectDocumentTop,
      maximum_variation_px: 1, normal_click_required_in_next_group: true });
    const caption = await grid().evaluate(element => {
      const heading = document.createElement("p");
      heading.dataset.qaSyntheticCaption = "true";
      heading.textContent = "Disposable QA · synthetic native candles · saved scanner charts · no operating/trading acceptance";
      element.prepend(heading);
      return heading.textContent;
    });
    await grid().screenshot({ path: path.join(directory, "five-frame-charts.png") });
    await grid().locator("[data-qa-synthetic-caption]").evaluate(element => element.remove());
    receipt.screenshot_caption = caption;
    groups.push({ name: phase, frames, candle_counts: Object.fromEntries(frames.map(frame => [frame, charts[frame].candles.length])), rendered_canvas_frames: 5 });

    phase = "original-saved-pattern-and-causal-overlay";
    const frame = "5m";
    await workspace().getByLabel("Scanner evidence interval", { exact: true }).selectOption(frame);
    await workspace().getByLabel("Scanner evidence type", { exact: true }).selectOption("patterns");
    const patternRead = observeResponse(r => new URL(r.url()).pathname === "/api/research/pattern-scanner/patterns");
    await workspace().getByRole("button", { name: "Inspect saved evidence", exact: true }).click();
    let originalPage = await jsonResponse(await patternRead); assert(originalPage.rows.length > 0); save("original-pattern-page.json", originalPage);
    assert(originalPage.next_before !== null && originalPage.total > originalPage.rows.length);
    const olderPatterns = observeResponse(r => new URL(r.url()).pathname === "/api/research/pattern-scanner/patterns" && new URL(r.url()).searchParams.has("before"));
    await workspace().getByRole("button", { name: "Next evidence page", exact: true }).click();
    originalPage = await jsonResponse(await olderPatterns); assert(originalPage.rows.length > 0); save("older-original-pattern-page.json", originalPage);
    const original = originalPage.rows[0].body ?? originalPage.rows[0];
    assert(typeof original.reason === "string" && original.reason.length);
    await workspace().locator(".scanner-evidence-list article").first().getByText(original.reason, { exact: true }).waitFor();
    const focused = waitChart("BTCUSD", frame, "at_ms");
    await workspace().locator(".scanner-evidence-list article").first().getByRole("button", { name: "Show this pattern on chart", exact: true }).click();
    const focusedResponse = await focused; const historical = await jsonResponse(focusedResponse);
    assert.equal(focusedResponse.status(), 200); assert.equal(historical.mode, "historical");
    assert.equal(new URL(focusedResponse.url()).searchParams.get("at_ms"), String(original.bar_open_ms));
    assert(historical.candles.some(candle => candle.open_ms === original.bar_open_ms));
    assert.equal(historical.source.archive_verified, true); assert(historical.source.references.length >= 1);
    assert.equal(historical.selection.kind, "patterns");
    assert.equal(historical.selection.record.id, original.id);
    assert.equal(historical.selection.record.seq, originalPage.rows[0].seq);
    assert.equal(historical.selection.candle_available, true);
    assert.equal(historical.selection.known_by_window_end, true);
    assert(!historical.patterns.rows.some(row => row.id === original.id), "Fixture selects an original event beyond the first overlay page");
    await card(frame).locator("canvas").first().waitFor();
    await card(frame).getByRole("region", { name: `${frame} original recognition explanation` }).getByText(original.reason, { exact: true }).waitFor();
    await page.waitForFunction(({ frame, id }) => {
      const host = document.querySelector(`article[data-timeframe="${frame}"] .candle-study-chart [role=img]`);
      return host && JSON.parse(host.dataset.patternIds || "[]").includes(id);
    }, { frame, id: original.id });
    const focusedProof = await plotProof(frame);
    assert(JSON.parse(focusedProof.dataset.patternIds).includes(original.id));
    save("focused-original-pattern-chart.json", historical); save("focused-overlay-plot.json", focusedProof);
    groups.push({ name: phase, original_pattern_id: original.id, exact_original_open_ms: original.bar_open_ms, archived_native_candles: historical.candles.length, archive_verified: true });

    phase = "historical-bookmark-reload-retains-original-campaign-and-inputs";
    const bookmark = await page.evaluate(() => location.hash);
    const bookmarkFields = new URLSearchParams(bookmark.split("?")[1]);
    assert.equal(bookmarkFields.get("scanner_campaign"), setup.campaign_id);
    assert.equal(bookmarkFields.get("scanner_chart_frame"), frame);
    assert.equal(bookmarkFields.get("scanner_chart_at_ms"), String(original.bar_open_ms));
    assert.equal(bookmarkFields.get("scanner_chart_progress_sha256"), historical.source.progress_sha256);
    const beforeHistoricalReload = await probe();
    const restoredRead = waitChart("BTCUSD", frame, "at_ms");
    await page.reload(); const restoredResponse = await restoredRead; const restored = await jsonResponse(restoredResponse);
    assert.equal(restoredResponse.status(), 200); assert.equal(restored.campaign_id, setup.campaign_id); assert.equal(restored.mode, "historical");
    assert.equal(restored.source.rows_sha256, historical.source.rows_sha256);
    assert.deepEqual(restored.source.references, historical.source.references);
    assert.equal(restored.selection.record.id, original.id);
    assert(restored.candles.some(row => row.open_ms === original.bar_open_ms));
    const afterHistoricalReload = await probe();
    assert.equal(afterHistoricalReload.posts.length, beforeHistoricalReload.posts.length);
    assert.equal(afterHistoricalReload.native_requests.length, beforeHistoricalReload.native_requests.length);
    await card(frame).getByRole("button", { name: "Older levels", exact: true }).waitFor();
    save("historical-bookmark-reopen.json", restored);
    groups.push({ name: phase, campaign: setup.campaign_id, frame, original_open_ms: original.bar_open_ms, saved_rows_sha256: restored.source.rows_sha256, extra_posts: 0, extra_native_requests: 0 });

    phase = "every-overlay-page-retains-exact-progress-identity";
    assert(historical.levels.next_before !== null && historical.levels.total > historical.levels.rows.length);
    const nextLevels = waitChart("BTCUSD", frame, "levels_before");
    await card(frame).getByRole("button", { name: "Older levels", exact: true }).click();
    const nextLevelsResponse = await nextLevels; const nextLevelsBody = await jsonResponse(nextLevelsResponse);
    assert.equal(nextLevelsResponse.status(), 200);
    assert.equal(new URL(nextLevelsResponse.url()).searchParams.get("expected_progress_sha256"), historical.source.progress_sha256);
    assert.equal(nextLevelsBody.source.progress_sha256, historical.source.progress_sha256);
    assert.equal(nextLevelsBody.levels.total, historical.levels.total);
    const seenLevels = new Set(historical.levels.rows.map(row => row.seq));
    assert(nextLevelsBody.levels.rows.every(row => !seenLevels.has(row.seq)));
    save("next-original-level-page.json", nextLevelsBody);
    groups.push({ name: phase, total_saved_levels: historical.levels.total, pages: [historical.levels.rows.length, nextLevelsBody.levels.rows.length], progress_sha256: historical.source.progress_sha256 });

    phase = "event-to-level-focus-clears-obsolete-original-event";
    await workspace().getByLabel("Scanner evidence type", { exact: true }).selectOption("levels");
    const levelPageRead = observeResponse(r => new URL(r.url()).pathname === "/api/research/pattern-scanner/levels");
    await workspace().getByRole("button", { name: "Inspect saved evidence", exact: true }).click();
    const levelPage = await jsonResponse(await levelPageRead); assert(levelPage.rows.length > 0);
    const level = levelPage.rows[0].body ?? levelPage.rows[0];
    const levelRead = waitChart("BTCUSD", frame, "selected_seq");
    await workspace().locator(".scanner-evidence-list article").first().getByRole("button", { name: "Show this level on chart", exact: true }).click();
    const levelView = await jsonResponse(await levelRead); assert.equal(levelView.selection.kind, "levels");
    assert.equal(levelView.selection.record.id, level.id);
    await card(frame).getByRole("region", { name: `${frame} original recognition explanation` }).getByText("Choose an original move", { exact: true }).waitFor();
    const levelProof = await plotProof(frame);
    assert(!JSON.parse(levelProof.dataset.patternIds).includes(original.id), "No cached beyond-page event marker may survive a level selection");
    assert(!(await card(frame).getByRole("region", { name: `${frame} original recognition explanation` }).innerText()).includes(original.reason));
    save("event-to-level-exact-selection.json", levelView); save("event-to-level-plot.json", levelProof);
    groups.push({ name: phase, selected_level_id: level.id, obsolete_event_id: original.id, old_extra_reason_and_marker_cleared: true });

    phase = "historical-window-exclusive-paging";
    const last = waitChart("BTCUSD", frame);
    await card(frame).getByRole("button", { name: "Latest saved candles", exact: true }).click(); await last;
    const older = waitChart("BTCUSD", frame, "before_ms");
    await card(frame).getByRole("button", { name: "Older saved candles", exact: true }).click();
    const olderResponse = await older; const olderBody = await jsonResponse(olderResponse); assert.equal(olderResponse.status(), 200);
    assert.equal(olderBody.mode, "historical"); assert(olderBody.candles.length > 100 && olderBody.candles.length <= 1000);
    assert.equal(olderBody.source.archive_verified, true);
    save("older-retained-window.json", olderBody);
    groups.push({ name: phase, requested_before_ms: Number(new URL(olderResponse.url()).searchParams.get("before_ms")), candles: olderBody.candles.length, actual_archived_chunks: olderBody.source.references.length });

    phase = "failed-new-window-cannot-page-old-overlays-with-new-query";
    const latestAgain = waitChart("BTCUSD", frame);
    await card(frame).getByRole("button", { name: "Latest saved candles", exact: true }).click(); await latestAgain;
    await qa("chart_window_fail");
    const failedWindow = waitChart("BTCUSD", frame, "before_ms");
    await card(frame).getByRole("button", { name: "Older saved candles", exact: true }).click();
    const failedWindowResponse = await failedWindow; assert.equal(failedWindowResponse.status(), 503);
    await card(frame).getByRole("alert").waitFor();
    const olderLevelsButton = card(frame).getByRole("button", { name: "Older levels", exact: true });
    assert.equal(await olderLevelsButton.isDisabled(), true);
    const blockedPaging = (await probe()).reads.length;
    await page.waitForTimeout(150);
    assert(!(await probe()).reads.slice(blockedPaging).some(read => new URLSearchParams(read.query).has("levels_before")));
    await qa("normal"); const recovery = waitChart("BTCUSD", frame);
    await card(frame).getByRole("button", { name: "Latest saved candles", exact: true }).click();
    assert.equal((await recovery).status(), 200);
    groups.push({ name: phase, failed_read_status: 503, old_overlay_cursor_dispatches: 0, recovery: "explicit latest GET" });

    phase = "slow-old-market-response-cannot-overwrite-current-market";
    await qa("chart_slow_btc");
    const btcPending = page.waitForRequest(r => new URL(r.url()).pathname === "/api/research/pattern-scanner/chart" && new URL(r.url()).searchParams.get("symbol") === "BTCUSD");
    await card("15m").getByRole("button", { name: "Latest saved candles", exact: true }).click(); await btcPending;
    const ethRead = waitChart("ETHUSD", "4h");
    await workspace().getByLabel("Scanner evidence market", { exact: true }).selectOption("ETHUSD"); await ethRead; await waitPlots();
    await page.waitForTimeout(1200); // Outlives the fixture's exact one-second old response.
    assert.equal(await workspace().getByLabel("Scanner evidence market", { exact: true }).inputValue(), "ETHUSD");
    assert(await grid().innerText().then(text => text.includes("ETH / USD pattern charts") && !text.includes("BTCUSD")));
    await qa("normal");
    groups.push({ name: phase, old_response_delay_ms: 1000, selected_market: "ETHUSD", old_market_hidden: true });

    phase = "reload-preserves-read-only-saved-scope";
    const beforeReload = await probe(); await page.reload(); await grid().waitFor(); await waitPlots();
    const afterReload = await probe(); assert.equal(afterReload.posts.length, beforeReload.posts.length);
    assert.equal(afterReload.native_requests.length, beforeReload.native_requests.length);
    assert.equal(await page.evaluate(() => localStorage.getItem("qtrades-year-pattern-scanner-pending-v1")), null);
    groups.push({ name: phase, extra_api_posts: 0, extra_native_source_requests: 0 });

    phase = "old-historical-bookmark-refuses-expanded-progress";
    const denseAfterReads = await probe();
    assert.equal(denseAfterReads.native_requests.length, before.native_requests.length);
    assert.equal(denseAfterReads.saved_recognition_sha256[setup.campaign_id], before.saved_recognition_sha256[setup.campaign_id]);
    save("dense-read-only-preservation.json", denseAfterReads);
    const advanced = await qa("chart_advance_saved_scope", 35000); save("explicit-synthetic-source-advance.json", advanced);
    assert.equal(advanced.status, "advanced"); assert(advanced.after.observed_bars > advanced.before.observed_bars);
    densePreservation = await probe();
    const refusedRead = waitChart("BTCUSD", frame, "at_ms");
    await page.evaluate(url => history.replaceState(null, "", url), `${origin}/${bookmark}`);
    await page.reload({ waitUntil: "domcontentloaded", timeout: 12000 });
    const refusedResponse = await refusedRead;
    assert.equal(refusedResponse.status(), 422);
    await card(frame).getByRole("alert").waitFor(); assert.equal(await card(frame).locator("canvas").count(), 0);
    save("changed-progress-refusal.json", { status: refusedResponse.status(), request_url: refusedResponse.url(),
      displayed_error: await card(frame).getByRole("alert").innerText(), response_body_consumed: false,
      original_progress_sha256: historical.source.progress_sha256 });
    const matchingRefusal = await page.request.get(refusedResponse.url(), { timeout: 10000 });
    assert.equal(matchingRefusal.status(), 422);
    save("matching-changed-progress-api-body.json", { status: matchingRefusal.status(),
      request_url: refusedResponse.url(), body: await jsonResponse(matchingRefusal),
      browser_error_response_body_verified: false, distinct_bounded_same_query_get: true });
    assert.equal(await page.evaluate(() => new URLSearchParams(location.hash.split("?")[1]).get("scanner_chart_progress_sha256")), historical.source.progress_sha256);
    const updatedRead = waitChart("BTCUSD", frame);
    await card(frame).getByRole("button", { name: "Latest saved candles", exact: true }).click();
    const updated = await jsonResponse(await updatedRead); assert.equal(updated.mode, "latest");
    assert.notEqual(updated.source.progress_sha256, historical.source.progress_sha256);
    await card(frame).locator("canvas").first().waitFor();
    groups.push({ name: phase, explicit_fixture_steps: advanced.steps, refusal_status: 422, original_progress_sha256: historical.source.progress_sha256, deliberate_latest_progress_sha256: updated.source.progress_sha256, implicit_window_expansion: false });

    phase = "actual-sparse-year-and-prospective-alert-fixture";
    const alertSetup = await qa("chart_alert_setup", 60000); save("prospective-synthetic-setup.json", alertSetup);
    assert.equal(alertSetup.status, "alert_prepared");
    const fourHour = alertSetup.four_hour_history.find(row => row.timeframe === "4h");
    assert.equal(fourHour.observed_bars, 2190); assert.equal(fourHour.missing_bars, 0);
    assert(alertSetup.four_hour_history.filter(row => row.timeframe !== "4h").every(row => row.observed_bars === 0 && row.missing_bars === row.expected_bars));
    await page.goto(`${origin}/#markets?symbol=BTCUSD`); await grid().waitFor();
    await card("4h").locator("canvas").first().waitFor();
    const alertChart = await getChart(alertSetup.alert_campaign_id, "BTCUSD", "4h");
    assert(alertChart.alerts.rows.length > 0); const alert = alertChart.alerts.rows[0];
    assert.equal(alert.historical, false); assert(alert.evaluation && typeof alert.evaluation.status === "string");
    assert(alertChart.candles.some(row => row.open_ms === alert.bar_open_ms));
    for (const missing of frames.filter(frame => frame !== "4h")) {
      assert.equal((await getChart(alertSetup.alert_campaign_id, "BTCUSD", missing)).candles.length, 0);
      assert.equal(await card(missing).locator("canvas").count(), 0);
    }
    save("original-prospective-alert-chart.json", alertChart); save("prospective-rendered-plot.json", await plotProof("4h"));
    groups.push({ name: phase, complete_synthetic_four_hour_candles: 2190, other_intervals_missing: 4, alert_id: alert.id, original_evaluation: alert.evaluation, financial_authority: false });

    phase = "unavailable-frame-stays-unknown-and-recovers-by-get";
    await qa("chart_frame_fail"); await page.reload(); await grid().waitFor();
    await card("30m").getByRole("alert").waitFor();
    assert.equal(await card("30m").locator("canvas").count(), 0);
    await card("4h").locator("canvas").first().waitFor();
    await qa("normal");
    const emptyRecovery = waitChart("BTCUSD", "30m");
    await card("30m").getByRole("button", { name: "Latest saved candles", exact: true }).click();
    const emptyResponse = await emptyRecovery; assert.equal(emptyResponse.status(), 200);
    assert.equal((await jsonResponse(emptyResponse)).candles.length, 0);
    await card("30m").getByText("No saved candles available here. Missing or unprepared history is not an empty successful analysis.", { exact: true }).waitFor();
    assert.equal(await card("30m").locator("canvas").count(), 0);
    groups.push({ name: phase, failed_frame: "30m", recovery: "GET only; original empty coverage remains empty" });

    phase = "current-account-classification-and-retained-history-link";
    await page.goto(`${origin}/#accounts`);
    await page.getByRole("button", { name: "Research 2", exact: true }).waitFor();
    await page.getByRole("button", { name: "Research 2", exact: true }).click();
    const table = page.getByRole("table", { name: "Current paper accounts", exact: true });
    await table.getByText("QA lab candidate", { exact: true }).waitFor(); await table.getByText("QA lab reference", { exact: true }).waitFor();
    assert.equal(await table.locator("tbody tr").count(), 2);
    assert.equal(await page.getByRole("link", { name: "Retained trial history", exact: true }).getAttribute("href"), "#research");
    assert(await page.getByText(/retire after becoming flat/).isVisible());
    groups.push({ name: phase, synthetic_autonomous_lab_projection_count: 2, archived_financial_payload_acceptance: false, existing_navigation: "#research" });

    phase = "bounded-mobile-and-zero-browser-writes";
    await page.setViewportSize({ width: 390, height: 844 }); await page.goto(`${origin}/#markets`); await grid().waitFor();
    await page.screenshot({ path: path.join(directory, "saved-charts-mobile.png"), fullPage: true });
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    const final = await probe(); save("final-probe.json", final);
    assert.equal(final.posts.length, 0); assert.equal(final.model_calls, 0); assert.equal(final.financial_database, false);
    assert.equal(final.financial_state_preserved_except_fixture_tick, true);
    assert.equal(final.saved_recognition_sha256[setup.campaign_id], densePreservation.saved_recognition_sha256[setup.campaign_id]);
    assert(apiRequests.every(request => request.method === "GET"));
    assert.equal(externalRequests.length, 0); assert.equal(pageErrors.length, 0, JSON.stringify(pageErrors));
    receipt.source_hashes = final.source_hashes;
    receipt.setup_controls = final.setup_controls;
    receipt.native_source_requests = final.native_requests.length;
    groups.push({ name: phase, browser_api_posts: 0, operating_api_or_venue_requests: 0, fixture_setup_controls: final.setup_controls.length, financial_state_preserved_except_fixture_tick: true });
  } catch (error) {
    failure ||= { phase, name: error.name, message: error.message, stack: error.stack };
    if (page) {
      await page.screenshot({ path: path.join(directory, "failure.png"), fullPage: true, timeout: 3000 }).catch(() => {});
      fs.writeFileSync(path.join(directory, "failure.html"), await bounded(page.content(), "failure DOM", 3000).catch(() => "Unavailable"));
    }
  } finally {
    try {
      const response = await fetch(`${origin}/__qa/stop`, { method: "POST", headers, signal: AbortSignal.timeout(10000) });
      receipt.shutdown = { status: response.status, body: await jsonResponse(response) };
    } catch (error) { receipt.shutdown = { status: "unconfirmed", error: error.message }; }
    receipt.resource_cleanup = {};
    for (const [name, owned] of [["context", context], ["browser", browser]]) {
      if (!owned) { receipt.resource_cleanup[name] = { status: "no_owned_handle", confirmed: false }; continue; }
      try { await bounded(owned.close(), `${name} close`); receipt.resource_cleanup[name] = { status: "closed", confirmed: true }; }
      catch (error) { receipt.resource_cleanup[name] = { status: "unknown", confirmed: false, error: error.message }; }
    }
    if (!failure && (receipt.shutdown.status !== 200 || !receipt.resource_cleanup.context.confirmed || !receipt.resource_cleanup.browser.confirmed))
      failure = { phase: "owned-resource-cleanup", name: "UnconfirmedCleanup", message: "Workflow assertions finished, but one owned cleanup acknowledgment remains unconfirmed." };
    receipt.status = failure ? "failed" : "passed"; receipt.failure = failure;
    receipt.browser_closed = receipt.resource_cleanup.browser.confirmed === true;
    receipt.artifacts = Object.fromEntries(fs.readdirSync(directory).filter(name => name !== "receipt.json")
      .map(name => [name, sha(fs.readFileSync(path.join(directory, name)))]));
    receipt.finished_at = new Date().toISOString(); save("receipt.json", receipt);
    clearTimeout(lifetime);
    console.log(JSON.stringify({ status: receipt.status, groups: groups.length, directory, failure }));
    if (failure) process.exitCode = 1;
  }
})().catch(error => { console.error(error.stack); process.exitCode = 1; });
