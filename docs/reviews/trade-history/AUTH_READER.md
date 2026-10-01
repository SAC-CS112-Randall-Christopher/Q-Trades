# Authenticated history-reader correction

The authorized PR25 installed update succeeded at `9936c76` and all seven
before/after preservation checks passed. The normal installed Trade history GET
then returned 503. Bounded read-only diagnosis confirmed that Psycopg's
`connection.info.dsn` omits the password: reconnecting with that redacted string
failed, while reconstructing the connection using the existing in-memory password
successfully read one retained closed trade with actual fill prices. The paper
worker remained fresh and its journal balanced. Private failed API/UI receipts and
the original update log are retained; initial installation is not usable-history
acceptance.

The earlier QA PostgreSQL used trust authentication, which masked this dependency.
Two new always-runnable API regressions fail on the original code (503 instead of
200, 2.46 seconds). They require the configured credential, preserve connection
options including schema selection, cover quote/backslash/space escaping, require
a separate read-only transaction and verify closure and no credential in the reply.
These are driver-contract simulations, separate from actual PostgreSQL proof.

The source fix reconstructs the reader DSN with Psycopg's encoder and the current
writer connection's existing in-memory credential. It changes neither credentials
nor authentication settings, financial processing, event history or UI economics.

Predeclared verification: rerun both regressions, then the affected engine/store/API
suite and full suite with the separate QA PostgreSQL on loopback port 55633. Run a
bounded actual SCRAM authentication fixture using one generated QA role/schema;
verify that a redacted reconnect fails and the real API reads without changing
financial state. Its user-specific HBA rule applies only to the verified disposable
cluster and must be restored exactly; drop only its generated schema/role. Run Ruff,
strict Windows-targeted mypy and the dashboard build. Require exact-head and
merged-main hosted checks, then the authorized existing updater and fresh private
installed preservation/API/browser receipts. No installed configuration change,
lab activation, paid call, live order or model download is included.

Observed local correction checks: both new regressions pass in 2.22 seconds;
50 affected checks pass in 11.49 seconds. The actual SCRAM fixture rejects a
redacted login and returns API 200 with unchanged synthetic state/events, a
balanced journal and no credential in the response. Its original QA HBA bytes are
restored and its generated role/schema removed. Ruff, strict mypy for 73 source
files and the 1,920-module dashboard build pass. The initial import-order lint
failure was corrected without reformatting unrelated code. The full-suite and
hosted/merged/installed stages are subsequent receipts reported in the PR.
