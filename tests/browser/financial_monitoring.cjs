// Actual compiled Accounts interface + actual disposable API; no response interception.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");
const origin = process.env.QTRADES_BROWSER_QA_ORIGIN || "http://127.0.0.1:58960";
const directory = process.env.QTRADES_BROWSER_QA_OUTPUT;
const token = process.env.QTRADES_BROWSER_QA_TOKEN;

(async () => {
  assert(directory && token, "Explicit isolated QA output and token are required");
  fs.mkdirSync(directory, { recursive: true });
  const browser = await chromium.launch({ headless: true,
    executablePath: process.env.QTRADES_BROWSER_QA_EXECUTABLE || undefined });
  const browserRuntime = { playwright: require("playwright/package.json").version,
    browser: browser.version(), executable: process.env.QTRADES_BROWSER_QA_EXECUTABLE
      ? "Explicit existing QA executable" : "Pinned bundled Chromium" };
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
  const errors = [];
  const receipts = [];
  const transitions = [];
  let failure = null;
  const headers = { "x-qa-token": token };
  const saveTransitions = () => fs.writeFileSync(path.join(directory, "r63-1-browser.json"),
    JSON.stringify({ evidence_kind: "synthetic_optional_query_controls_actual_owners",
      runtime: browserRuntime, transitions, errors }, null, 2));
  page.on("pageerror", error => errors.push(error.message));
  try {
    async function transition(mode, expected, noticeState) {
      const response = await page.request.post(`${origin}/__qa/r63-1/${mode}`, { headers });
      assert.equal(response.status(), 200, `Actual-owner transition ${mode}`);
      const owner = await response.json();
      const statusResponse = page.waitForResponse(response =>
        response.url() === `${origin}/api/status` && response.status() === 200);
      await page.goto(`${origin}/#accounts`);
      await statusResponse;
      const summary = page.getByText("Original Tier 3 trial and review history", { exact: true });
      if (await summary.locator("..").getAttribute("open") === null) await summary.click();
      const label = page.getByTestId("journal-monitoring");
      await label.waitFor();
      const text = await label.innerText();
      const probeBefore = await (await page.request.get(`${origin}/__qa/r63-1/probe`,
        { headers })).json();
      const status = await (await page.request.get(`${origin}/api/status`)).json();
      const health = await (await page.request.get(`${origin}/api/health`)).json();
      const notices = await (await page.request.get(`${origin}/api/research/notices`)).json();
      const notice = notices.operational.find(row => row.key === "financial_monitoring");
      const detail = notice ? await (await page.request.get(
        `${origin}/api/research/notices/financial_monitoring`)).json() : null;
      const color = await label.evaluate(element => getComputedStyle(element).color);
      await label.screenshot({ path: path.join(directory,
        `r63-1-${transitions.length}-${mode}.png`) });
      const probeAfter = await (await page.request.get(`${origin}/__qa/r63-1/probe`,
        { headers })).json();
      // Preserve the original observed counterexample before any acceptance
      // assertion; a red run is still inspectable evidence of its exact source.
      const receipt = { mode, owner, text, color, status, health, notices, detail,
        probeBefore, probeAfter };
      transitions.push(receipt);
      saveTransitions();
      if (["routine-hold", "hold-recent", "hold-storage_usage", "timeout-hold"].includes(mode)) {
        const name = mode === "hold-storage_usage" ? "storage_usage" : "recent";
        assert.equal(probeAfter.fixture.reader_alive, true,
          "All held UI/API observations must precede owned-reader termination");
        assert.equal(probeAfter.fixture.operation_error, null,
          "The held recovery interval must precede the unchanged operation deadline");
        assert.equal(probeAfter.fixture.queries[name].held, true);
        assert.equal(probeAfter.fixture.completed_at, owner.fixture.completed_at,
          "No completed refresh may replace the held attempt during UI/API observation");
      }
      assert.equal(probeBefore.registry_changes, probeAfter.registry_changes,
        "Normal API/health/notice reads must not write registry state");
      assert.equal(owner.history_retained, true);
      assert(owner.history_count > 0, "Retention proof requires real persisted history");
      assert.equal(probeAfter.history_retained, true);
      assert.equal(owner.experiments, 0, "Monitoring must not enqueue research");
      assert.equal(probeAfter.experiments, 0);
      assert.equal(owner.research_ready, expected === "balanced");
      assert.equal(probeAfter.research_ready, expected === "balanced");
      for (const journal of [owner.journal, status.paper.journal, health.journal_monitoring]) {
        assert.equal(journal.status, expected, `Current availability during ${mode}`);
        assert.equal(journal.available, expected === "balanced");
        assert.equal(journal.balanced, true);
        assert.equal(journal.revision, owner.journal.revision);
        assert.equal(journal.checked_at, owner.journal.checked_at);
      }
      assert.equal(status.paper.performance.financial_readback.available, expected === "balanced");
      assert.equal(status.paper.research_constrained, expected !== "balanced");
      assert.equal(status.paper.performance.resource_guard.blocking_conditions.includes(
        "financial_readback_unavailable"), expected !== "balanced");
      assert.equal(health.journal_balanced, expected === "balanced" ? true : null);
      assert.equal(health.journal_last_balanced, true);
      assert(text.includes(expected === "balanced" ? "Current journal audit balanced"
        : "Current journal monitoring unavailable"));
      assert(text.includes("Last completed audit balanced at"));
      assert(text.includes(`Revision ${owner.journal.revision}`));
      assert.equal(owner.producer.length, 7, "Observe the complete producer batch");
      const producer = owner.producer.find(row => row.key === "financial_monitoring");
      assert.equal(producer.facts.status, expected);
      assert.equal(producer.condition, expected === "balanced" ? "clear" : "unknown");
      assert.equal(notices.detector_error, null);
      if (noticeState) {
        assert(notice, "The persisted financial notice must remain readable");
        assert.equal(notice.state, noticeState);
        assert.equal(notice.condition_evidence.facts.status, expected);
        assert.equal(notice.condition_evidence.facts.checked_at, owner.journal.checked_at);
      }
      if (expected === "unavailable") {
        assert.equal(notice.current_condition, "unknown");
        assert.equal(status.paper.error, null, "Optional query failure is not a financial stop");
        assert.equal(status.paper.running, true);
      }
      return receipt;
    }

    const first = await transition("start", "balanced");
    const routine = await transition("routine-hold", "balanced");
    assert.equal(routine.owner.fixture.queries.recent.held, true);
    assert.equal(routine.owner.fixture.completed_at, first.owner.fixture.completed_at);
    await transition("routine-release", "balanced");
    for (const name of ["recent", "storage_usage"]) {
      const failure = await transition(`fail-${name}`, "unavailable", "unknown");
      assert(name in failure.owner.sample.refresh_errors);
      const held = await transition(`hold-${name}`, "unavailable", "unknown");
      assert.equal(held.owner.fixture.queries[name].held, true);
      assert(held.owner.journal.checked_at > failure.owner.journal.checked_at,
        "The retry must publish a newer actual completed audit");
      assert.equal(held.owner.fixture.completed_at, failure.owner.fixture.completed_at,
        "The optional refresh remains outstanding after audit publication");
      await transition(`repeat-${name}`, "unavailable", "unknown");
      await transition(`recover-${name}`, "balanced", "unknown");
      await transition("confirm", "balanced", "recovered");
    }
    const both = await transition("fail-both", "unavailable", "unknown");
    assert.deepEqual(Object.keys(both.owner.sample.refresh_errors).sort(),
      ["recent", "storage_usage"]);
    const partial = await transition("recover-recent", "unavailable", "unknown");
    assert.deepEqual(Object.keys(partial.owner.sample.refresh_errors), ["storage_usage"],
      "History recovery cannot clear an independently outstanding storage failure");
    const partialHeld = await transition("hold-storage_usage", "unavailable", "unknown");
    assert.equal(partialHeld.owner.fixture.queries.storage_usage.held, true);
    await transition("recover-both", "balanced", "unknown");
    await transition("confirm", "balanced", "recovered");
    await transition("fail-recent", "unavailable", "unknown");
    const timeoutHeld = await transition("timeout-hold", "unavailable", "unknown");
    assert.equal(timeoutHeld.owner.fixture.queries.recent.held, true);
    const deadline = await transition("timeout-complete", "unavailable", "unknown");
    assert.equal(deadline.owner.journal.error, "Financial readback operation deadline exceeded");
    assert.equal(deadline.owner.fixture.reader_alive, false);
    assert.equal(deadline.owner.fixture.shutdown.status, "terminated_owned_reader");
    assert.equal(deadline.owner.fixture.completed_at, timeoutHeld.owner.fixture.completed_at);
    await transition("recover-recent", "balanced", "unknown");
    const final = await transition("confirm", "balanced", "recovered");
    assert(final.detail.transitions.some(row => row.body.state === "unknown"));
    assert(final.detail.transitions.some(row => row.body.state === "recovered"));
    const stop = await page.request.post(`${origin}/__qa/r63-1/stop`, { headers });
    assert.equal(stop.status(), 200);
    assert.equal((await stop.json()).shutdown.status, "drained");

    // Preserve the original seven presentation compatibility states separately
    // from the actual-owner optional-query recovery proof above.
    for (const [mode, phrase] of [
      ["pending", "Journal audit pending"],
      ["balanced", "Current journal audit balanced"],
      ["failure", "Current journal monitoring unavailable"],
      ["balanced", "Current journal audit balanced"],
      ["expired", "Current journal monitoring expired"],
      ["balanced", "Current journal audit balanced"],
      ["imbalanced", "Journal imbalance confirmed"],
    ]) {
      const response = await page.request.post(`${origin}/__qa/monitoring/${mode}`, {
        headers,
      });
      assert.equal(response.status(), 200);
      const journal = await response.json();
      await page.goto(`${origin}/#accounts`);
      const summary = page.getByText("Original Tier 3 trial and review history", { exact: true });
      if (await summary.locator("..").getAttribute("open") === null) await summary.click();
      const label = page.getByTestId("journal-monitoring");
      await label.filter({ hasText: phrase }).waitFor();
      const text = await label.innerText();
      const status = await (await page.request.get(`${origin}/api/status`)).json();
      const health = await (await page.request.get(`${origin}/api/health`)).json();
      assert.equal(status.paper.journal.status, journal.status);
      assert.equal(status.paper.journal.available, journal.available);
      assert.equal(status.paper.performance.financial_readback.available, journal.available);
      assert.equal(health.journal_monitoring.status, journal.status);
      if (["failure", "expired"].includes(mode)) {
        assert(text.includes("Last completed audit balanced at"));
        assert(text.includes(`Revision ${journal.revision}`));
        assert.equal(health.journal_balanced, null);
        assert.equal(health.journal_last_balanced, true);
      }
      await label.screenshot({ path: path.join(directory, `${receipts.length}-${mode}.png`) });
      const color = await label.evaluate(element => getComputedStyle(element).color);
      receipts.push({ mode, journal, text, color });
    }
    await page.setViewportSize({ width: 390, height: 900 });
    const label = page.getByTestId("journal-monitoring");
    assert(await label.isVisible());
    const box = await label.boundingBox();
    assert(box.x >= 0 && box.x + box.width <= 390, "Journal notice must fit narrow viewport");
    await label.screenshot({ path: path.join(directory, "journal-narrow.png") });
    assert.deepEqual(errors, []);
    const balancedColor = receipts.find(row => row.mode === "balanced").color;
    for (const mode of ["pending", "failure", "expired", "imbalanced"]) {
      assert.notEqual(receipts.find(row => row.mode === mode).color, balancedColor,
        "Unavailable or negative monitoring cannot carry the current-balanced color");
    }
    fs.writeFileSync(path.join(directory, "browser.json"), JSON.stringify({
      evidence_kind: "synthetic_browser_fixture", runtime: browserRuntime, receipts, errors,
    }, null, 2));
    console.log("PASS: actual-owner R63-1 recovery/timeout/guard/notices; seven API/UI states; " +
      "narrow viewport; no browser exceptions");
  } catch (error) {
    failure = error;
    throw error;
  } finally {
    try {
      await page.request.post(`${origin}/__qa/monitoring/stop`, {
        headers: { "x-qa-token": token }, timeout: 5000,
      });
    } catch (error) {
      if (!failure) throw error;
      console.error("Owned QA server shutdown request also failed:", error.message);
    } finally {
      await browser.close();
    }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
