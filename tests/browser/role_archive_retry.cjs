// Real compiled role UI/API/registry; only acknowledgment delivery faults are synthetic.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { chromium } = require("playwright");
const origin = process.env.QTRADES_BROWSER_QA_ORIGIN || "http://127.0.0.1:58973";
const directory = process.env.QTRADES_BROWSER_QA_OUTPUT;
const token = process.env.QTRADES_BROWSER_QA_TOKEN;
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
  const groups = [], pageErrors = [], externalRequests = [], requests = [];
  const receipt = {
    scope: "Compiled browser/real API and disposable role registry/shared archive; synthetic saved tasks and post-commit acknowledgment faults",
    harness_sha256: sha(fs.readFileSync(__filename)), groups, pageErrors, externalRequests,
    requests, operating_acceptance: false, financial_database: false, model_calls: 0,
  };
  const headers = { "x-qa-token": token };
  const save = (name, value) => fs.writeFileSync(path.join(directory, name), JSON.stringify(value, null, 2));
  let browser, context, page, phase = "startup", failure;
  try {
    browser = await chromium.launch({ headless: true, executablePath: process.env.QTRADES_BROWSER_QA_EXECUTABLE || undefined });
    receipt.runtime = { playwright: require("playwright/package.json").version, browser: browser.version() };
    context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, serviceWorkers: "block" });
    await context.route("**/*", route => {
      if (new URL(route.request().url()).origin !== origin) {
        externalRequests.push(route.request().url()); return route.abort();
      }
      return route.continue(); // API bodies are never fabricated in the browser.
    });
    page = await context.newPage(); page.setDefaultTimeout(10000);
    page.on("pageerror", error => pageErrors.push(error.message));
    page.on("request", request => {
      const url = new URL(request.url());
      if (url.pathname.startsWith("/api/") && requests.length < 300) {
        requests.push({ method: request.method(), path: url.pathname });
      }
    });
    const qa = async action => {
      const response = await page.request.post(`${origin}/__qa/${action}`, { headers, timeout: 6000 });
      assert.equal(response.status(), 200, await response.text()); return response.json();
    };
    const probe = async () => {
      const response = await page.request.get(`${origin}/__qa/probe`, { headers, timeout: 6000 });
      assert.equal(response.status(), 200); return response.json();
    };
    const original = await probe(); save("initial-probe.json", original);
    const task = () => page.getByRole("article", { name: "Saved research task" });
    const select = async key => {
      await page.goto(`${origin}/#role-research?task=${original.identities[key]}`, { waitUntil: "domcontentloaded" });
      await task().getByRole("heading", { name: original.labels[key], exact: true }).waitFor();
    };
    const retryResponse = key => {
      const response = page.waitForResponse(r => r.url() === `${origin}/api/lab/roles/tasks/${original.identities[key]}/retry` && r.request().method() === "POST", { timeout: 10000 });
      void response.catch(() => {}); return response;
    };
    const archiveRetry = () => task().getByRole("button", { name: "Retry saved evidence archive", exact: true });
    const countPosts = (state, key) => state.posts.filter(post => post.task === original.identities[key]).length;

    phase = "archive-retry-distinct-from-model-transport";
    await select("success");
    assert.equal(await archiveRetry().count(), 1);
    assert.equal(await task().getByRole("button", { name: "Authorize one recorded transport retry", exact: true }).count(), 0);
    assert.equal((await probe()).posts.length, 0);
    groups.push({ name: phase, automatic_posts: 0, original_synthetic_attempts: original.attempts.length });

    phase = "one-explicit-archive-retry-and-exact-native-storage";
    let pending = retryResponse("success");
    await archiveRetry().click();
    let response = await pending;
    assert.equal(response.status(), 200);
    let value = await bounded(response.json(), 5000, "Retry body unavailable");
    assert.equal(value.id, original.identities.success);
    assert.equal(value.stage, "archive_evaluation"); assert.equal(value.status, "queued");
    await archiveRetry().waitFor({ state: "detached" });
    save("success-retry.json", value);
    const archived = await qa("archive_success"); save("exact-archive.json", archived);
    assert.equal(archived.exact_original_evaluation, true);
    assert.equal(archived.task.stage, "review");
    assert.deepEqual((await probe()).attempts, original.attempts);
    assert.equal(countPosts(await probe(), "success"), 1);
    groups.push({ name: phase, retry_posts: 1, exact_evaluation_retained: true, new_model_attempts: 0 });

    phase = "lost-ack-reopen-without-repeat";
    await qa("lost_ack"); await select("lost_ack"); pending = retryResponse("lost_ack");
    await archiveRetry().click(); response = await pending;
    assert.equal(response.status(), 503);
    await page.getByRole("alert").filter({ hasText: "Synthetic post-commit acknowledgment unavailable" }).waitFor();
    assert.equal(countPosts(await probe(), "lost_ack"), 1);
    await qa("normal");
    await page.reload({ waitUntil: "domcontentloaded", timeout: 10000 });
    await task().getByRole("heading", { name: original.labels.lost_ack, exact: true }).waitFor();
    await archiveRetry().waitFor({ state: "detached" });
    const reopened = await page.request.get(`${origin}/api/lab/roles/tasks/${original.identities.lost_ack}`, { timeout: 5000 });
    const recovered = await reopened.json(); save("lost-ack-reopened.json", recovered);
    assert.equal(recovered.id, original.identities.lost_ack); assert.equal(recovered.status, "queued");
    assert.equal(countPosts(await probe(), "lost_ack"), 1);
    groups.push({ name: phase, actual_commit: "queued", delivered_status: 503, original_task_reopened_by_get: true, retry_posts: 1 });

    phase = "delayed-response-does-not-overwrite-another-question";
    await qa("delayed"); await select("delayed"); pending = retryResponse("delayed");
    await archiveRetry().click();
    const heldResponse = await page.request.get(`${origin}/__qa/held`, { headers, timeout: 3000 });
    const held = await heldResponse.json(); save("held-response.json", held);
    assert.equal(held.task, original.identities.delayed); assert.equal(held.committed, true);
    await page.getByRole("button", { name: original.labels.other, exact: true }).click();
    await task().getByRole("heading", { name: original.labels.other, exact: true }).waitFor();
    await page.evaluate(() => {
      window.__archiveHeadings = [];
      window.__archiveObserver = new MutationObserver(() => {
        window.__archiveHeadings.push(document.querySelector('article[aria-label="Saved research task"] h3')?.textContent ?? null);
      });
      window.__archiveObserver.observe(document.body, { subtree: true, childList: true, characterData: true });
    });
    await qa("release"); response = await pending;
    assert.equal(response.status(), 200);
    value = await bounded(response.json(), 5000, "Held retry body unavailable");
    assert.equal(value.id, original.identities.delayed);
    await page.waitForFunction(() => [...document.querySelectorAll("button")].some(button => button.textContent === "Save research question" && !button.disabled));
    await task().getByRole("heading", { name: original.labels.other, exact: true }).waitFor();
    await page.waitForFunction(() => document.querySelector('article[aria-label="Saved research task"] h3')?.textContent === "Different selected synthetic question");
    const observedHeadings = await page.evaluate(() => { window.__archiveObserver.disconnect(); return window.__archiveHeadings; });
    assert(observedHeadings.every(value => value === null || value === original.labels.other), JSON.stringify(observedHeadings));
    assert(new URL(page.url()).hash.includes(original.identities.other));
    assert.equal(countPosts(await probe(), "delayed"), 1);
    save("delayed-response.json", value); save("selected-heading-observations.json", observedHeadings);
    groups.push({ name: phase, original_retry_task: value.id, selected_task: original.identities.other, retry_handler_completion_observed: true, delayed_publication_blocked: true, retry_posts: 1 });

    phase = "mismatched-ack-refused-and-original-task-reopens";
    await qa("mismatch"); await select("mismatch"); pending = retryResponse("mismatch");
    await archiveRetry().click(); response = await pending;
    assert.equal(response.status(), 200); value = await bounded(response.json(), 5000, "Mismatched retry body unavailable");
    assert.equal(value.id, original.identities.other); save("mismatched-response.json", value);
    await page.getByRole("alert").filter({ hasText: "Retry acknowledgment belongs to another task" }).waitFor();
    assert.equal(await task().getByRole("heading").first().innerText(), original.labels.mismatch);
    await qa("normal"); await page.reload({ waitUntil: "domcontentloaded", timeout: 10000 });
    await task().getByRole("heading", { name: original.labels.mismatch, exact: true }).waitFor();
    await archiveRetry().waitFor({ state: "detached" });
    const final = await probe(); save("final-probe.json", final);
    assert.equal(countPosts(final, "mismatch"), 1);
    assert.equal(final.posts.length, 4);
    assert(final.posts.every(post => post.local_operator_header === "1" && post.actual_http_status === 200));
    assert.deepEqual(final.attempts, original.attempts);
    assert.equal(final.financial_state_unchanged, true); assert.equal(final.model_calls, 0);
    assert.deepEqual(final.source_before, final.source_after);
    assert.deepEqual(pageErrors, []); assert.deepEqual(externalRequests, []);
    await page.screenshot({ path: path.join(directory, "final-synthetic-role-recovery.png"), fullPage: true });
    receipt.source_before = final.source_before; receipt.source_after = final.source_after;
    receipt.source_unchanged = true;
    groups.push({ name: phase, mismatched_id_refused: true, original_get_recovered: true, retry_posts: 1, no_new_attempt_or_financial_change: true });
    receipt.passed = true;
  } catch (error) {
    failure = { phase, name: error.name, message: error.message }; receipt.passed = false;
    if (page) {
      try { fs.writeFileSync(path.join(directory, "failure-dom.txt"), await bounded(page.locator("body").innerText({ timeout: 5000 }), 5000, "Failure DOM unavailable")); } catch (error) { receipt.failure_dom_error = error.name; }
      try { await page.screenshot({ path: path.join(directory, "failure.png"), timeout: 5000, fullPage: true }); } catch (error) { receipt.failure_screenshot_error = error.name; }
    }
  } finally {
    try { receipt.stop_status = (await fetch(`${origin}/__qa/stop`, { method: "POST", headers, signal: AbortSignal.timeout(5000) })).status; }
    catch (error) { receipt.stop_error = error.name; }
    try { if (context) { await bounded(context.close(), 5000, "Context close unconfirmed"); receipt.context_closed = true; } } catch (error) { receipt.context_close_error = error.message; }
    try { if (browser) { await bounded(browser.close(), 5000, "Browser close unconfirmed"); receipt.browser_closed = true; } } catch (error) { receipt.browser_close_error = error.message; }
    receipt.failure = failure ?? null;
    if (receipt.stop_status !== 200 || receipt.context_closed !== true || receipt.browser_closed !== true) receipt.passed = false;
    receipt.artifacts = Object.fromEntries(fs.readdirSync(directory).filter(name => name !== "receipt.json").map(name => [name, sha(fs.readFileSync(path.join(directory, name)))]));
    fs.writeFileSync(path.join(directory, "receipt.json"), JSON.stringify(receipt, null, 2));
  }
  if (!receipt.passed) { process.stderr.write(`${failure?.phase ?? "cleanup"}: ${failure?.message ?? "Cleanup unconfirmed"}\n`); process.exitCode = 1; }
  else process.stdout.write(`Passed ${groups.length} role archive recovery groups; synthetic inputs, no model or financial DB.\n`);
})();
