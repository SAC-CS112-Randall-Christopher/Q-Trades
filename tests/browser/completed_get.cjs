// Observe the actual completed UI GET; never issue a replacement request.
const assert = require("node:assert/strict");

function completedJsonGet(page, origin, apiPath, { timeout = 10000, bodyTimeout = 5000, observations }) {
  const issued = new Set();
  const proof = { path: apiPath, issued: 0, failed_requests: [] };
  observations.push(proof);
  const observe = request => {
    const url = new URL(request.url());
    if (url.origin === origin && url.pathname === apiPath && request.method() === "GET") {
      issued.add(request); proof.issued++;
    }
  };
  const failed = request => { if (issued.has(request)) proof.failed_requests.push(request.failure()); };
  page.on("request", observe); page.on("requestfailed", failed);
  // Headers can belong to a cancelled restoration read. Completion binds the
  // body to a newly issued request; HTTP refusals still complete and fail below.
  const read = page.waitForEvent("requestfinished", {
    predicate: request => issued.has(request), timeout,
  }).then(async request => {
    const response = await request.response();
    assert(response, "The completed original UI GET has no response");
    proof.completed_url = request.url(); proof.status = response.status();
    assert.equal(response.status(), 200);
    let timer;
    try {
      return await Promise.race([response.json(), new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error("Completed original UI body deadline reached")), bodyTimeout);
      })]);
    } finally { clearTimeout(timer); }
  }).finally(() => { page.off("request", observe); page.off("requestfailed", failed); });
  void read.catch(() => {}); return read;
}

module.exports = { completedJsonGet };
