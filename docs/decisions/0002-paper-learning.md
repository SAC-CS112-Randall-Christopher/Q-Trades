# 0002 — Authorized Tier 3 paper learning

2026-09-27. Supersedes the implementation scope in 0001. The source foundation stays
verbatim. Chris explicitly authorized continuous fake trading, four-hour automatic
refinement, and fake replenishment after falling below $5 in this conversation.

Use PostgreSQL for financial records. Start at USD 100; restore to 100 only below 5
after liquidation and a recorded failure review. Preserve all costs, losses, funding,
and failed or unresolved attempts. The target is reaching 1,000 before failure in
most attempts. A win does not reset capital; recrossing is not another win.

Auto-refinement means selecting among frozen paper candidates under forward-evidence
gates. It does not grant an LLM financial authority, raise risk limits, or permit real
trades or paid API calls. A supervised local application does continuous work; a
four-hour thread heartbeat provides additional oversight while Codex is available.