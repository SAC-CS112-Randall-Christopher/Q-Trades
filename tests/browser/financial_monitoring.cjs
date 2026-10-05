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
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
  const errors = [];
  const receipts = [];
  page.on("pageerror", error => errors.push(error.message));
  try {
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
        headers: { "x-qa-token": token },
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
      evidence_kind: "synthetic_browser_fixture", receipts, errors,
    }, null, 2));
    console.log("PASS: seven API/UI states and transitions; narrow viewport; no browser exceptions");
  } finally {
    await page.request.post(`${origin}/__qa/monitoring/stop`, { headers: { "x-qa-token": token } });
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
