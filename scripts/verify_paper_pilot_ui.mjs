// Compiled dashboard + actual disposable API/SQL/registry; synthetic model only.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
const { chromium } = createRequire(import.meta.url)("playwright");
const directory = process.env.QTRADES_BROWSER_QA_OUTPUT;
assert(directory, "Explicit task-owned QA output required");
const ready = JSON.parse(fs.readFileSync(path.join(directory, "server-ready.json"), "utf8"));
const token = fs.readFileSync(path.join(directory, "access-token.txt"), "utf8").trim();
const origin = `http://127.0.0.1:${ready.port}`;
const queueOnly = process.argv.includes("--queue-only");
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 1080 } });
const page = await context.newPage();
page.setDefaultTimeout(15000);
const checks = [];
const errors = [];
let failure = null;
let taskId = null;
page.on("pageerror", error => errors.push(error.message));
const panel = () => page.getByRole("region", { name: "Local model research", exact: true });
const pilot = () => page.getByRole("region", { name: "Experimental paper research pilot", exact: true });
async function qa(mode) {
  const response = await page.request.post(origin + "/__qa/mode", { headers: { "x-qa-token": token }, data: { mode } });
  assert.equal(response.status(), 200);
}
async function probe(name) {
  const response = await page.request.get(origin + "/__qa/probe", { headers: { "x-qa-token": token } });
  assert.equal(response.status(), 200);
  const value = await response.json();
  fs.writeFileSync(path.join(directory, name + ".json"), JSON.stringify(value, null, 2));
  assert.equal(value.model_calls, 0);
  assert.equal(value.balance.balanced, true);
  assert.equal(value.financial_accounts_preserved, true);
  assert.equal(value.shared_research_admission, false);
  return value;
}
async function until(predicate, description) {
  const deadline = Date.now() + 15000;
  while (Date.now() < deadline) {
    if (await predicate()) return;
    await new Promise(resolve => setTimeout(resolve, 150));
  }
  throw new Error(description);
}
async function record(name) {
  await page.screenshot({ path: path.join(directory, name + ".png"), fullPage: true });
  checks.push(name);
}
async function reload() {
  await page.reload();
  await pilot().waitFor();
}
try {
  await page.goto(origin + "/#role-research");
  await pilot().waitFor();
  await until(() => pilot().getByRole("button", { name: "Pause paper research", exact: true }).isEnabled(), "Pilot status should become current");
  assert((await pilot().innerText()).includes("experimental and unqualified"));
  assert((await panel().innerText()).includes("Synthetic pilot UI fixture (no model execution)"));
  assert((await panel().innerText()).includes("qualified-role comparison coverage"));
  await record("01-approved-experimental-status");

  const question = "Can another closed bar support a falsifiable comparison of reviewed paper methods?";
  await panel().getByRole("textbox", { name: /^Research question/ }).fill(question);
  await panel().getByRole("button", { name: "Save research question", exact: true }).click();
  await until(async () => (await probe("question-saved")).roles.history.retained === 1, "Real API must save the question");
  const saved = await probe("02-real-queue");
  taskId = saved.roles.tasks[0].id;
  const originalDetail = await page.request.get(origin + "/api/lab/roles/tasks/" + taskId);
  assert.equal(originalDetail.status(), 200);
  const retained = await originalDetail.json();
  assert.equal(retained.context.pilot_grant_id, "synthetic-ui-grant");
  fs.writeFileSync(path.join(directory, "retained-original-task.json"), JSON.stringify(retained, null, 2));
  assert.equal(saved.roles.tasks[0].question, question);
  assert.equal(saved.attempts.length, 0);
  const questionPost = saved.writes.find(write => write.path.endsWith("/questions"));
  assert(questionPost.body.request_id && questionPost.status === 200);
  assert.equal(await page.evaluate(() => localStorage.getItem("qtrades-role-question-retry")), null);
  await reload();
  await until(async () => (await panel().innerText()).includes(question), "Saved question must reopen after reload");
  assert(page.url().includes(taskId));
  await record("02-real-question-reopened");

  await qa("dispatch");
  await until(async () => (await probe("current-running")).synthetic_callback_entered, "Real worker should reserve a synthetic callback");
  await reload();
  await until(async () => (await pilot().innerText()).includes("Current task"), "Current owned registry task must be visible");
  const running = await probe("03-current-owned-task");
  assert.equal(running.roles.current_task.id, taskId);
  assert.equal(running.attempts.length, 1);
  await record("03-current-owned-task");
  await qa("release");
  await reload();
  await until(async () => (await panel().innerText()).includes("Await required data"), "Actual synthetic request_data result must retain its wait");
  await panel().getByText("Model attempts, final answers and resource receipts", { exact: true }).click();
  assert((await panel().innerText()).includes("new_closed_bars"));
  assert((await panel().innerText()).includes("request_data"));
  assert.equal(await panel().getByRole("button", { name: "Authorize one recorded transport retry", exact: true }).count(), 0);
  await record("04-retained-answer-and-dependency");

  if (!queueOnly) {
  await pilot().getByRole("button", { name: "Pause paper research", exact: true }).click();
  await until(() => pilot().getByRole("button", { name: "Resume approved paper pilot", exact: true }).isEnabled(), "Pause must appear immediately from validated policy");
  await reload();
  assert((await panel().innerText()).includes("pilot paused"));
  const paused = await probe("05-paused-retained");
  assert.equal(paused.roles.enabled, false);
  assert.equal(paused.roles.history.retained, 1);
  assert.equal(paused.attempts.length, 1);
  await record("05-paused-history-reopened");

  await qa("protected");
  await pilot().getByRole("button", { name: "Resume approved paper pilot", exact: true }).click();
  await until(async () => (await pilot().innerText()).includes("protected financial admission refused"), "Protected refusal must be shown");
  assert.equal(await page.evaluate(() => localStorage.getItem("qtrades-paper-pilot-control")), null);
  await record("06-protected-resume-refusal");
  await qa("healthy");
  await pilot().getByRole("button", { name: "Resume approved paper pilot", exact: true }).click();
  await until(() => pilot().getByRole("button", { name: "Pause paper research", exact: true }).isEnabled(), "Original approved pilot can resume");

  await qa("lost_ack");
  await pilot().getByRole("button", { name: "Pause paper research", exact: true }).click();
  await reload();
  await until(async () => (await page.evaluate(() => localStorage.getItem("qtrades-paper-pilot-control"))) === null, "Fresh status must reconcile committed lost acknowledgment without replay");
  const ack = await probe("07-lost-ack-reconciled");
  assert.equal(ack.writes.filter(write => write.path.endsWith("/control") && write.body.action === "pause").length, 2);
  assert.equal(ack.roles.enabled, false);
  await record("07-lost-ack-status-reconciliation");

  await qa("revoked");
  await reload();
  assert((await panel().innerText()).includes("grant revoked"));
  await pilot().getByRole("button", { name: "Resume approved paper pilot", exact: true }).click();
  await until(async () => (await pilot().innerText()).includes("grant revoked"), "Revocation must remain explicit");
  const final = await probe("08-revoked-history-retained");
  assert.equal(final.roles.enabled, false);
  assert.equal(final.roles.history.retained, 1);
  assert.equal(final.synthetic_callbacks, 1);
  assert.equal(final.attempts.length, 1);
  assert.equal(final.writes.at(-1).status, 409);
  await record("08-revoked-retained-history");
  }
  const end = await probe("final-current-workflow");
  assert.equal(end.synthetic_callbacks, 1);
  assert.equal(end.attempts.length, 1);
  assert.deepEqual(errors, []);
} catch (error) {
  failure = { message: error.message, stack: error.stack };
  await page.screenshot({ path: path.join(directory, "failure.png"), fullPage: true }).catch(() => {});
} finally {
  fs.writeFileSync(path.join(directory, "browser-receipt.json"), JSON.stringify({
    scope: "Compiled normal UI + actual disposable API/SQL/registry; synthetic model callback only",
    status: failure ? "failed" : "passed", checks, task: taskId, failure, page_errors: errors,
    queue_only: queueOnly,
    model_calls: 0, operating_acceptance: false, trained_model_capacity_or_value: false,
  }, null, 2));
  await page.request.post(origin + "/__qa/shutdown", { headers: { "x-qa-token": token } }).catch(() => {});
  await context.close();
  await browser.close();
}
if (failure) throw new Error(failure.message);
process.stdout.write(JSON.stringify({ status: "passed", checks, task: taskId }) + "\n");
