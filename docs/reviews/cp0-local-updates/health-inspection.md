# CP0 health inspection correction

## Observed operating state

Chris's direct read-only Python probe reported the paper worker running and fresh,
with no reported engine error, a balanced journal at revision **204325**, and zero
imbalanced events. Health also reported the monitor and historical options worker
running. This is the operator's supplied observation, not a new remote request,
proof of uninterrupted operation or evidence of strategy performance.
See `operator-windows-health.json` for exact selected fields and provenance.

At the earlier code head `943c574`, Chris also reported **21 Windows tests passed**
and successful build-only .NET Framework launcher compilation (10,752 bytes).
`DesktopExecutable: null` confirms no desktop copy from that build. These native
results are distinct from later Linux results and are not fresh Windows tests of
this correction.

## Reproduced defect and correction

The old inspector read nested properties without validating the response shape or
Boolean types. A healthy JSON body returned as **text** yielded exactly the earlier
false/true/false/false flags with no health-read error. Missing fields and malformed
objects could do the same. `inspector-same-input-reproduction.json` runs the old and
corrected actual PowerShell inspectors on the same synthetic healthy JSON text,
with mocked operating-system/HTTP inputs and no real account access.

The original problematic Windows response body/type was not retained. The later
Python check does not prove which transport/parser condition occurred earlier.
The reproduced inspection bug is nevertheless real and independently fixed.

The corrected inspector parses bounded JSON text explicitly, accepts an actual
paper object, and preserves true/false only for genuine Boolean values. Absent,
null or wrongly typed fields remain **null/unknown**, not unhealthy or healthy.
`complete` and `unknown_fields` make incomplete results visible; genuine stopped,
stale, unreconciled and error reports remain negative. The error indicator is only
derived from the API's null/string error contract; raw error text is not exported.
An unreadable/unparseable object reports unknown health with a fixed diagnostic.
`-UseBasicParsing` is explicit for Windows PowerShell. Identity must still verify
before the one read-only status request. No account, task or process mutation exists.

## Verification executed on the correction

- **26 inspector tests passed** under the existing PowerShell 7.6.6 Linux runtime.
  The 12 newly added parsing/unknown-state cases failed before the correction.
  Additional assertions preserve genuinely unhealthy values and redact raw text.
- Full suite: **282 passed, six native-Windows skips**, one existing Starlette
  TestClient deprecation warning. Disposable project PostgreSQL only.
- Ruff, strict mypy (36 source modules) and compilation checks passed.
- No API, dashboard, trading, accounting, fee, funding or risk code changed.
  The prior browser/build receipts remain historical; not rerun for this script fix.

References reviewed: Microsoft Learn, Invoke-RestMethod and ConvertFrom-Json for
Windows PowerShell 5.1. Parsing behavior is covered by the reproduction above, not
inferred from a promise that the cmdlet always returns the expected object.

CP0's controlled activation/rollback remains unfinished and uninstalled. This fix
removes misleading inspection results; it does not activate PR #3, change GitHub
main or certify a future update. No operating service restart was needed for it.
