import { useEffect, useState } from "react";
import { inContext } from "./productNavigation";
import { RetainedComparison } from "./RetainedComparison";

type Report = {request_id:string;sha256:string;candidate:string;control:string|null;
  decision:string;reasons:string[];created_at:number;daily_blocks?:unknown[];daily_block_count?:number;matched_windows:number;
  evidence_kind:string;uncertainty:string[];artifact_sha256:string|null;rule_sha256?:string|null;
  attribution:{symbols:string[];regime:string;fees:string}};
export type Learning = {incumbent:string;role_version:number;
  reports:Report[];promotions:{rolled_back:boolean;prior_incumbent:string;incumbent:string}[];
  accounts:{account:string;label:string;version:string;control:string|null;drift:string[];
    latest_decisions:Record<string,{reason?:string}>}[];
  qualification_sources?:{account:string;label:string;trial_id:string;rule_sha256:string;state:string;reason:string}[];
  changes:Record<string,string>};

export function LearningPanel({data,unavailable}:{data?:Learning;unavailable:boolean}) {
  const selectedAccount = () => new URLSearchParams(location.hash.split("?")[1] ?? "").get("account") ?? "";
  const [selected,setSelected] = useState(selectedAccount);
  const trialIdentity = () => new URLSearchParams(location.hash.split("?")[1] ?? "").get("trial");
  const [trial,setTrial] = useState(trialIdentity);
  useEffect(() => { const restore = () => { setSelected(selectedAccount()); setTrial(trialIdentity()); }; window.addEventListener("hashchange", restore); window.addEventListener("popstate", restore); return () => { window.removeEventListener("hashchange", restore); window.removeEventListener("popstate", restore); }; }, []);
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState("");
  const [retry,setRetry] = useState<{request_id:string;candidate:string}|null>(()=>{
    try {return JSON.parse(localStorage.getItem("qtrades-learning-retry") ?? "null");}
    catch {return null;}
  });
  const exact = selected || retry?.candidate;
  const a = exact ? data?.accounts.find(a=>a.account===exact) : data?.accounts[0];
  const otherPending = !!retry && !!selected && retry.candidate !== selected;
  async function post(url:string,body?:unknown) {
    setBusy(true);setError("");
    try {
      const response = await fetch(url,{method:"POST",headers:{"X-Local-Operator":"1","Content-Type":"application/json"},
        body:body===undefined ? undefined : JSON.stringify(body),signal:AbortSignal.timeout(8000)});
      if(!response.ok) {const value=await response.json();throw new Error(String(value.detail));}
      return true;
    } catch(e) {setError(String(e));return false;} finally {setBusy(false);}
  }
  async function inspect() {
    if(!a || otherPending)return;
    const request = retry ?? {request_id:crypto.randomUUID(),candidate:a.account};
    localStorage.setItem("qtrades-learning-retry",JSON.stringify(request));setRetry(request);
    if(await post("/api/paper/learning/reports",request)) {
      localStorage.removeItem("qtrades-learning-retry");setRetry(null);
    }
  }
  return <section id="forward-learning" className="lab-result" aria-label="Forward learning and decisions"><h3>Forward comparisons and learning journal</h3>
    <p>Exploratory results stay separate from qualified prospective comparisons. Paper incumbent role: {data?.incumbent ?? "primary"}. A designation changes the research role only; each account keeps its money, positions, policy and losses.</p>
    <p>The frozen policy requires 28 complete subsequent daily blocks, matched incumbent/cash/exposure controls, known costs, drawdown and stability limits, and a dependence/selection margin. Earlier inspected windows cannot become new validation. No trade-count quota.</p>
    {error && <p role="alert">{error}</p>}
    {retry && <p role="status">A saved forward-report acknowledgment for {retry.candidate} remains unresolved. {otherPending && <>This page stays on the selected account. <a href={inContext("#accounts?view=qualification", { account: retry.candidate, trial: null })}>Open the original report recovery</a> before inspecting a different candidate.</>}</p>}
    {trial && <RetainedComparison key={trial} identity={trial} />}
    {data?.qualification_sources?.map(h=><article className="lab-result" key={h.account} aria-label="Original rule result for qualification">
      <h4>{h.label}: review the original exploratory result</h4><p>{h.reason}</p>
      <a href={inContext("#accounts?view=comparisons", { trial: h.trial_id, account: h.account })}>Review this frozen rule and prospective funding</a>
    </article>)}
    {!a ? <p>{exact ? "This selected account has no prospective qualification admission. Review its original comparison above; another candidate cannot replace this selection." : "No frozen prospective candidate has been admitted. The original trial and its history continue."}</p> : <>
      <label>Forward candidate<select value={a.account} disabled={busy || !!retry} onChange={e=>{ setSelected(e.target.value); location.hash = inContext("#accounts?view=qualification", { account: e.target.value, trial: null }); }}>
        {data?.accounts.map(a=><option key={a.account} value={a.account}>{a.label}</option>)}</select></label>
      <p>Version {a.version}. Matched control: {a.control ?? "Not yet funded"}.</p>
      {a.drift.map(r=><p key={r}>Drift / attention: {r}</p>)}
      {Object.entries(a.latest_decisions).map(([symbol,value])=><p key={symbol}>Recorded {symbol} decision: {value.reason ?? "No reason retained"}</p>)}
      <button type="button" disabled={busy || unavailable || !!a.control} onClick={()=>void post(`/api/paper/learning/control/${a.account}`)}>Fund matched frozen incumbent control</button>
      <button type="button" disabled={busy || unavailable || otherPending} onClick={()=>void inspect()}>{retry && !otherPending ? "Confirm frozen forward report" : "Inspect and retain forward comparison"}</button>
      <p>Inspection consumes this information, including an insufficient or negative result. Control funding is separate hypothetical capital and uses a remaining account place.</p>
    </>}
    {data?.reports.filter(r => !exact || r.candidate === exact).map(r=><article className="lab-result" key={r.request_id}><h4>{r.decision==="no_promotion" ? "No promotion" : "Eligible for explicit paper-role approval"}</h4>
      <p>{new Date(r.created_at*1000).toLocaleString()} · {r.evidence_kind} · {r.daily_block_count ?? r.daily_blocks?.length ?? 0} complete daily blocks / {r.matched_windows} matched windows.</p>
      {r.reasons.map(reason=><p key={reason}>{reason}</p>)}
      <p>Frozen {r.rule_sha256 ? "supported rule" : "numerical model"}. Instruments: {r.attribution.symbols?.join(", ")}. Regime: {r.attribution.regime}.</p>
      <details><summary>Original strategy identity</summary><p>{r.rule_sha256 ?? r.artifact_sha256}</p></details>
      {r.uncertainty.map(note=><p key={note}>{note}</p>)}
      <a href={`/api/paper/learning/reports/${r.request_id}`} download>Export retained forward report</a>
      <button type="button" disabled={busy || unavailable || r.decision!=="eligible_for_paper_designation"}
        onClick={()=>void post("/api/paper/learning/role",{action:"designate",expected_version:data.role_version,report_id:r.request_id,report_sha256:r.sha256})}>Approve paper incumbent designation</button>
    </article>)}
    {!!data?.promotions.length && <button type="button" disabled={busy || unavailable || data.promotions.at(-1)?.rolled_back}
      onClick={()=>void post("/api/paper/learning/role",{action:"rollback",expected_version:data.role_version})}>Roll back latest paper designation</button>}
    <dl>{Object.entries(data?.changes ?? {}).map(([key,value])=><div key={key}><dt>{key.replaceAll("_"," ")}</dt><dd>{value}</dd></div>)}</dl>
  </section>;
}
