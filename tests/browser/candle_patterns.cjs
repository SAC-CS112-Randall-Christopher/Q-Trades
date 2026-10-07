// Compiled dashboard + actual isolated API/journal/archive; synthetic native candles only.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { chromium } = require("playwright");

const origin = process.env.QTRADES_BROWSER_QA_ORIGIN || "http://127.0.0.1:58968";
const directory = process.env.QTRADES_BROWSER_QA_OUTPUT;
const token = process.env.QTRADES_BROWSER_QA_TOKEN;
const remainingOnly = process.env.QTRADES_BROWSER_QA_REMAINING_ONLY === "1";
const scopeOnly = process.env.QTRADES_BROWSER_QA_SCOPE_ONLY === "1";
const plotsOnly = process.env.QTRADES_BROWSER_QA_PLOTS_ONLY === "1";
const sha = bytes => crypto.createHash("sha256").update(bytes).digest("hex");

(async () => {
  assert(directory && token, "Explicit task-owned output and QA token required");
  const url = new URL(origin);
  assert.equal(url.hostname, "127.0.0.1");
  assert(!["8780", "5432", "54544"].includes(url.port), "An isolated QA port is required");
  fs.mkdirSync(directory, { recursive: false });
  const groups = [], pageErrors = [], externalRequests = [], apiRequests = [];
  const receipt = { evidence_kind: "compiled_ui_actual_disposable_api_synthetic_native_candles",
    operating_acceptance: false, financial_database: false, model_calls: 0,
    trading_edge_proof: false, groups, pageErrors, externalRequests, apiRequests,
    harness_sha256: sha(fs.readFileSync(__filename)), remaining_only: remainingOnly, scope_only: scopeOnly, plots_only: plotsOnly };
  let browser, context, page, failure = null;
  const headers = { "x-qa-token": token };
  let finalProbe;
  let phase = "startup";
  try {
    browser = await chromium.launch({ headless: true,
      executablePath: process.env.QTRADES_BROWSER_QA_EXECUTABLE || undefined });
    receipt.runtime = { playwright: require("playwright/package.json").version, browser: browser.version() };
    context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, serviceWorkers: "block" });
    await context.route("**/*", route => {
      const requested = new URL(route.request().url());
      if (requested.origin !== origin) {
        externalRequests.push({ method: route.request().method(), origin: requested.origin });
        return route.abort();
      }
      return route.continue(); // No API response is fabricated or intercepted.
    });
    page = await context.newPage(); page.setDefaultTimeout(12000);
    page.on("pageerror", error => pageErrors.push(error.message));
    page.on("request", request => { const address = new URL(request.url());
      if (address.pathname.startsWith("/api/") && apiRequests.length < 1000) {
        apiRequests.push({ method: request.method(), path: address.pathname, query: address.search });
      }
    });
    const workspace = () => page.getByRole("region", { name: "Candle & volume workspace" });
    const probe = async () => (await page.request.get(`${origin}/__qa/probe`, { headers })).json();
    const mode = async name => assert.equal((await page.request.post(`${origin}/__qa/${name}`, { headers })).status(), 200);
    const save = (name, value) => fs.writeFileSync(path.join(directory, name), JSON.stringify(value, null, 2));
    const waitStudy = async () => {
      await workspace().getByText(/actual closed candles/, { exact: false }).waitFor();
      assert.equal(await workspace().locator("canvas").count() > 0, true);
      assert.equal(await workspace().getByRole("alert").count(), 0);
    };
    const load = async (frame, window = "recent") => {
      await workspace().getByRole("button", { name: frame, exact: true }).click();
      await workspace().getByLabel("Candle history window").selectOption(window);
      const response = page.waitForResponse(r => r.request().method() === "POST" && r.url() === `${origin}/api/research/candle-patterns`);
      await workspace().getByRole("button", { name: `Load ${frame} study`, exact: true }).click();
      const actual = await response; const value = await actual.json();
      assert.equal(actual.status(), 200, JSON.stringify(value));
      await waitStudy();
      save(`study-${groups.length}-${frame}-${window}.json`, value);
      return value;
    };
    const checkPlots = async () => {
      const chart = () => workspace().getByRole("img", { name: /closed .* candles with volume/ });
      const bounds = async () => JSON.parse(await chart().getAttribute("data-indicator-segments"));
      const viewportIncludes = async time => {
        await page.waitForFunction(at => {
          const element = document.querySelector(".candle-study-chart [role=img]");
          return Number(element?.dataset.visibleStartMs) <= at && Number(element?.dataset.visibleEndMs) >= at;
        }, time, { timeout: 5000 });
      };
      phase = "continuous-indicator-plots";
      await mode("normal"); const continuous = await load("5m");
      const normalBounds = await bounds();
      for (const [key, period] of Object.entries({ sma10: 10, sma50: 50, sma100: 100, vwap: 50 })) {
        assert.equal(normalBounds[key].length, 1);
        assert.equal(normalBounds[key][0].points, 241 - period);
      }
      await viewportIncludes(continuous.candle_analysis.candles.at(-1).open_ms);
      groups.push({ name: phase, run: continuous.id, segments: normalBounds });

      phase = "warmed-gap-disconnected-plots-and-timeline";
      await mode("gap_warm"); const gapped = await load("5m");
      const analysis = gapped.candle_analysis;
      assert.equal(analysis.candles.length, 239);
      assert.equal(analysis.coverage.missing_bars, 1);
      const step = analysis.seconds * 1000;
      const gapTime = analysis.candles[0].open_ms + 120 * step;
      const gapBounds = await bounds();
      for (const [key, period] of Object.entries({ sma10: 10, sma50: 50, sma100: 100, vwap: 50 })) {
        assert.equal(gapBounds[key].length, 2, `${key} must use two independent line series`);
        assert.deepEqual(gapBounds[key].map(segment => segment.points), [121 - period, 120 - period]);
        assert.equal(gapBounds[key][0].to, gapTime - step);
        assert.equal(gapBounds[key][1].from, gapTime + period * step);
      }
      await viewportIncludes(analysis.candles.at(-1).open_ms);
      await workspace().getByRole("button", { name: "First interval", exact: true }).click();
      for (let i = 0; i < 120; i++) await workspace().getByRole("button", { name: "Next interval", exact: true }).click();
      assert(await workspace().locator(".candle-inspector").innerText().then(text => text.includes("no recorded candle available") && !text.includes("Open")));
      await viewportIncludes(gapTime);
      await workspace().getByRole("button", { name: "Next interval", exact: true }).click();
      assert(await workspace().locator(".candle-inspector").innerText().then(text => /SMA 100\s+Unavailable/.test(text)));
      await workspace().getByRole("button", { name: "First interval", exact: true }).click();
      const selectedTime = analysis.patterns.at(-1).bar_open_ms;
      assert(selectedTime > gapTime + 100 * step, "The actual analyzer must classify a warmed post-gap candle");
      await workspace().locator(".candle-pattern-list button").first().click();
      await viewportIncludes(selectedTime);
      const selectedViewport = { from: Number(await chart().getAttribute("data-visible-start-ms")), to: Number(await chart().getAttribute("data-visible-end-ms")) };
      assert.equal(selectedViewport.from, selectedTime - 25 * step,
        "After navigation the current viewport must use the whitespace-inclusive timeline");
      await workspace().getByRole("button", { name: "Latest interval", exact: true }).click();
      await viewportIncludes(analysis.candles.at(-1).open_ms);
      await workspace().getByRole("button", { name: "Fit saved history", exact: true }).click();
      await page.setViewportSize({ width: 1440, height: 3200 });
      await workspace().locator("header").click();
      await page.evaluate(() => {
        document.activeElement?.blur();
        const marker = document.createElement("p"); marker.textContent = "SOURCE QA · SYNTHETIC NATIVE CANDLES · NO FINANCIAL OR MODEL PROOF";
        marker.style.cssText = "background:#f2d589;color:#10211d;padding:10px;font-size:12px";
        document.querySelector(".candle-workspace").prepend(marker);
      });
      await workspace().screenshot({ path: path.join(directory, "warmed-gap-study.png") });
      await page.setViewportSize({ width: 1440, height: 1100 });
      groups.push({ name: phase, run: gapped.id, candles: 239, gap_time: gapTime,
        contiguous_candles: [120, 119], segments: gapBounds, selected_time: selectedTime, selected_viewport: selectedViewport });
    };

    await page.goto(`${origin}/#markets`);
    await workspace().waitFor();
    assert.equal((await probe()).posts.length, 0, "Opening the workspace must not dispatch a study");
    if (plotsOnly) {
      await checkPlots();
    } else {
    if (remainingOnly || scopeOnly) {
      const prepared = await load("5m");
      receipt.preparation = { actual_saved_run: prepared.id, candles: 240, qualification: false };
    } else {
    for (const frame of ["5m", "15m", "30m", "1h", "4h"]) {
      phase = `native-${frame}`;
      const value = await load(frame);
      assert.equal(value.candle_analysis.timeframe, frame);
      assert.equal(value.candle_analysis.candles.length, 240);
      assert.deepEqual(value.candle_analysis.parameters.sma_periods, [10, 50, 100]);
      const study = workspace().locator(".candle-study-result");
      for (const name of ["SMA 10", "SMA 50", "SMA 100", "VWAP · 50 candles"]) {
        assert.equal(await study.getByRole("button", { name, exact: true }).getAttribute("aria-pressed"), "true");
      }
      assert(await study.innerText().then(t => t.includes(`closed ${frame} candle`)));
      assert(await study.innerText().then(t => t.includes("50 candles") && t.includes("candle counts") === false));
      groups.push({ name: phase, run: value.id, candles: 240, source_sha256: value.candle_analysis.source_sha256 });
    }

    phase = "pattern-candle-and-volume";
    const patterns = workspace().locator(".candle-pattern-list button");
    assert(await patterns.count() > 0, "Real analyzer must detect a pattern in the declared synthetic source");
    await patterns.first().click();
    const patternText = await workspace().getByRole("region", { name: "Pattern details" }).innerText();
    assert(patternText.includes("prior median") && patternText.includes("level"));
    assert.equal(await patterns.first().getAttribute("aria-pressed"), "true");
    groups.push({ name: phase, pattern: patternText });

    phase = "year-truncation-and-full-archive-reopen";
    const year = await load("5m", "year");
    assert.equal(year.candle_analysis.candles.length, 5000);
    assert.equal(year.candle_analysis.coverage.truncated, true);
    assert.equal(year.result.result.candles.length, 1, "Immutable compact receipt remains compact");
    assert(await workspace().innerText().then(t => t.includes("history was truncated")));
    await page.reload(); await waitStudy();
    assert(await workspace().innerText().then(t => t.includes(`Saved study #${year.id}`)));
    assert.equal(await workspace().getByLabel("Candle history window").inputValue(), "year");
    groups.push({ name: phase, run: year.id, reopened_candles: 5000 });

    phase = "gap-and-warmup-unknown";
    await mode("gap"); const gap = await load("15m");
    assert(gap.candle_analysis.coverage.missing_bars > 0);
    await workspace().getByRole("button", { name: "First interval", exact: true }).click();
    await workspace().getByRole("button", { name: "Next interval", exact: true }).click();
    const gapInspector = await workspace().getByRole("region", { name: "Selected candle and volume" }).innerText();
    assert(gapInspector.includes("no recorded candle available"));
    assert(!gapInspector.includes("Open"), "A missing interval must not adopt the latest OHLC values");
    assert(/SMA 100\s+Unavailable/.test(gapInspector));
    await mode("short"); const short = await load("1h");
    assert.equal(short.candle_analysis.indicators.points.at(-1).sma100, null);
    assert(await workspace().locator(".candle-inspector").innerText().then(t => /SMA 100\s+Unavailable/.test(t)));
    groups.push({ name: phase, gap_run: gap.id, short_run: short.id,
      missing: gap.candle_analysis.coverage.missing_bars, short_candles: short.candle_analysis.candles.length });

    phase = "lost-ack-reload-exact-get-no-repeat";
    await mode("lost_ack");
    await workspace().getByRole("button", { name: "30m", exact: true }).click();
    await workspace().getByRole("button", { name: "Load 30m study", exact: true }).click();
    await workspace().getByRole("alert").filter({ hasText: "original request is saved" }).waitFor();
    const before = await probe(); const pending = before.posts.at(-1);
    assert.equal(pending.saved_status, "completed");
    const second = await context.newPage();
    await second.goto(`${origin}/#markets`);
    const secondWorkspace = second.getByRole("region", { name: "Candle & volume workspace" });
    await secondWorkspace.getByRole("button", { name: "Find original saved result" }).waitFor();
    assert.equal(await secondWorkspace.getByRole("button", { name: /Load .* study/ }).isDisabled(), true);
    assert.equal((await probe()).posts.length, before.posts.length, "Another window cannot overwrite the pending UUID");
    await second.close();
    await page.reload(); await workspace().getByRole("button", { name: "Find original saved result" }).waitFor();
    await mode("normal");
    await workspace().getByRole("button", { name: "Find original saved result" }).click();
    await waitStudy();
    const after = await probe();
    assert.equal(after.posts.length, before.posts.length);
    assert.equal(after.runs.total, before.runs.total);
    assert(await workspace().innerText().then(t => t.includes(`Saved study #${pending.run_id}`)));
    save("lost-ack-before.json", before); save("lost-ack-after.json", after);
    groups.push({ name: phase, request_id: pending.body.request_id, run: pending.run_id, extra_posts: 0 });

    phase = "late-response-scope-change";
    await mode("late");
    const posted = page.waitForRequest(request => request.method() === "POST" && request.url() === `${origin}/api/research/candle-patterns`);
    await workspace().getByRole("button", { name: "Load 30m study", exact: true }).click(); await posted;
    await workspace().getByRole("button", { name: "4h", exact: true }).click();
    await page.waitForTimeout(2400);
    assert.equal(await workspace().locator(".candle-study-result").count(), 0, "Old30m response cannot appear under4h selection");
    assert.equal(await workspace().getByRole("button", { name: "4h", exact: true }).getAttribute("aria-pressed"), "true");
    await mode("normal"); await workspace().getByRole("button", { name: "Find original saved result" }).click(); await waitStudy();
    assert.equal(await workspace().getByRole("button", { name: "30m", exact: true }).getAttribute("aria-pressed"), "true");
    groups.push({ name: phase, stale_result_hidden: true, recovered_original_frame: "30m" });

    phase = "failed-source-and-definitive-refusal";
    await mode("fail");
    await workspace().getByRole("button", { name: "Load 30m study", exact: true }).click();
    await workspace().getByText("The original unsuccessful outcome is retained.", { exact: true }).waitFor();
    assert.equal(await workspace().locator(".candle-study-result").count(), 0);
    assert.equal(await workspace().getByRole("button", { name: "Find original saved result" }).count(), 0);
    await mode("refuse"); await workspace().getByRole("button", { name: "Load 30m study", exact: true }).click();
    await workspace().getByText(/original request was refused \(429\)/).waitFor();
    assert.equal(await workspace().getByRole("button", { name: "Find original saved result" }).count(), 0);
    assert.equal(await workspace().getByRole("button", { name: "Load 30m study", exact: true }).isEnabled(), true);
    groups.push({ name: phase, unsuccessful_outcome_visible: true, precommit_refusal_retained: true });
    }

    if (!scopeOnly) {
    phase = "saved-receipt-outage";
    await workspace().locator(".candle-saved summary").click();
    await mode("outage");
    await workspace().getByRole("button", { name: /#1 · BTCUSD/ }).click();
    await workspace().getByRole("alert").filter({ hasText: "saved candle study is unavailable" }).waitFor();
    assert.equal(await workspace().locator(".candle-study-result").count(), 0);
    await mode("normal"); await workspace().getByRole("button", { name: /#1 · BTCUSD/ }).click(); await waitStudy();
    groups.push({ name: phase, no_empty_success_chart: true, original_reopen: 1 });

    phase = "deferred-lock-scope-change-no-unsent-recovery";
    const beforeDeferred = await probe();
    await page.evaluate(() => {
      const original = navigator.locks.request.bind(navigator.locks);
      navigator.locks.request = (...args) => new Promise((resolve, reject) => {
        window.__releaseCandleLock = () => original(...args).then(resolve, reject);
      });
      window.__restoreCandleLock = () => { navigator.locks.request = original; };
    });
    await workspace().getByRole("button", { name: "Load 5m study", exact: true }).click();
    await workspace().getByRole("button", { name: "4h", exact: true }).click();
    await page.evaluate(async () => { await window.__releaseCandleLock(); window.__restoreCandleLock(); });
    assert.equal(await page.evaluate(() => localStorage.getItem("qtrades-candle-pattern-pending-v1")), null);
    assert.equal((await probe()).posts.length, beforeDeferred.posts.length);
    groups.push({ name: phase, posts: 0, pending_orphan: false });
    }

    phase = "restored-other-market-preserves-current-account";
    await page.getByLabel("Evidence account", { exact: true }).selectOption("responsive-v1");
    await page.locator(".watchlist-rows button").filter({ hasText: "ETH" }).click();
    const eth = await load("5m");
    await page.locator(".watchlist-rows button").filter({ hasText: "BTC" }).click();
    const beforeSameId = apiRequests.filter(request => request.path === `/api/research/tools/runs/${eth.id}`).length;
    await page.evaluate(id => { location.hash = `markets?symbol=BTCUSD&account=responsive-v1&candle_run=${id}`; }, eth.id);
    await waitStudy();
    assert.equal(await page.getByLabel("Evidence account", { exact: true }).inputValue(), "responsive-v1");
    assert(apiRequests.filter(request => request.path === `/api/research/tools/runs/${eth.id}`).length > beforeSameId,
      "Returning to the same saved ID after changing its scope must actually reopen it");
    await page.locator(".watchlist-rows button").filter({ hasText: "BTC" }).click();
    await page.reload(); await workspace().waitFor();
    assert.equal(await page.getByLabel("Evidence account", { exact: true }).inputValue(), "responsive-v1");
    assert.equal(await workspace().locator(".candle-study-result").count(), 0, "Explicit different market must win over remembered study");
    assert(await workspace().locator("header").innerText().then(t => t.includes("BTC / USD")));
    await page.evaluate(id => { location.hash = `markets?symbol=BTCUSD&account=responsive-v1&candle_run=${id}`; }, eth.id);
    await waitStudy();
    assert.equal(await page.getByLabel("Evidence account", { exact: true }).inputValue(), "responsive-v1");
    assert(await workspace().locator(".candle-study-heading").innerText().then(t => t.includes("ETH / USD")));
    groups.push({ name: phase, saved_market: "ETHUSD", current_account: "responsive-v1" });

    phase = "mobile-and-screenshot";
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForFunction(() => { const element = document.querySelector(".candle-workspace");
      return element.scrollWidth <= element.clientWidth; }, null, { timeout: 5000 });
    assert.equal(await workspace().evaluate(element => element.scrollWidth <= element.clientWidth), true);
    await page.evaluate(() => {
      const marker = document.createElement("p"); marker.textContent = "SOURCE QA · SYNTHETIC NATIVE CANDLE RESPONSES · NO FINANCIAL OR MODEL PROOF";
      marker.style.cssText = "background:#f2d589;color:#10211d;padding:10px;font-size:12px";
      document.querySelector(".candle-workspace").prepend(marker);
    });
    await workspace().screenshot({ path: path.join(directory, "mobile-candle-study.png") });
    await page.setViewportSize({ width: 1440, height: 1100 });
    await workspace().screenshot({ path: path.join(directory, "candle-study.png") });
    groups.push({ name: phase, width: 390, horizontal_overflow: false });
    if (!remainingOnly && !scopeOnly) await checkPlots();
    }
    finalProbe = await probe(); save("final-probe.json", finalProbe);
    assert.equal(finalProbe.financial_state_unchanged, true);
    assert.deepEqual(pageErrors, []); assert.deepEqual(externalRequests, []);
    receipt.passed = true;
  } catch (error) {
    failure = { phase, name: error.name, message: error.message }; receipt.passed = false;
    if (page) {
      try { fs.writeFileSync(path.join(directory, "failure-dom.txt"), await page.locator("body").innerText()); } catch {}
      try { await page.screenshot({ path: path.join(directory, "failure.png"), fullPage: true }); } catch {}
    }
  } finally {
    // Cleanup also runs if the browser fails before a Page exists.
    try { receipt.stop_status = (await fetch(`${origin}/__qa/stop`, {
      method: "POST", headers, signal: AbortSignal.timeout(5000) })).status; }
    catch (error) { receipt.stop_error = error.name; }
    await context?.close(); await browser?.close(); receipt.browser_closed = true;
    receipt.failure = failure;
    receipt.artifacts = Object.fromEntries(fs.readdirSync(directory).filter(name => name !== "receipt.json")
      .map(name => [name, sha(fs.readFileSync(path.join(directory, name)))]));
    fs.writeFileSync(path.join(directory, "receipt.json"), JSON.stringify(receipt, null, 2));
  }
  if (failure) { process.stderr.write(`${failure.phase}: ${failure.message}\n`); process.exitCode = 1; }
  else process.stdout.write(`Passed ${groups.length} compiled-dashboard groups; synthetic native source only.\n`);
})();
