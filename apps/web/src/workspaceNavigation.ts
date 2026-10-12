import { Activity, BrainCircuit, ChartNoAxesCombined, History, LayoutDashboard, Settings2, Wallet } from "lucide-react";

export const workspaceAreas = [
  { id: "overview", label: "Overview", icon: LayoutDashboard, description: "Current operation, next actions and attention", views: [["dashboard", "Dashboard"], ["attention", "Attention & Decisions"]] },
  { id: "markets", label: "Markets", icon: Activity, description: "Observed markets, charts, findings and coverage", views: [["watch", "Market Watch"], ["charts", "Charts"], ["scanner", "Scanner & Findings"], ["coverage", "Data Coverage"]] },
  { id: "research", label: "Research", icon: BrainCircuit, description: "Investigations, experiments, strategies and knowledge", views: [["investigations", "Investigations"], ["experiments", "Numerical Research"], ["strategies", "Strategies"], ["knowledge", "Knowledge & Lessons"], ["training", "Training Preparation"], ["controls", "Research Controls"]] },
  { id: "accounts", label: "Accounts", icon: Wallet, description: "Separate paper accounts, positions, orders and limits", views: [["summary", "Account Summary"], ["positions", "Positions"], ["orders", "Orders & Trades"], ["safeguards", "Risk & Safeguards"]] },
  { id: "results", label: "Results", icon: ChartNoAxesCombined, description: "Performance, costs, comparisons and qualification", views: [["performance", "Performance"], ["costs", "Costs & Economics"], ["comparisons", "Matched Comparisons"], ["qualification", "Paper Qualification"], ["readiness", "Live Readiness"]] },
  { id: "history", label: "History", icon: History, description: "Original journals, research decisions and retained records", views: [["activity", "Recent Activity"], ["trades", "Trade History"], ["journal", "Account Journal"], ["investigations", "Research History"], ["matches", "Historical Matches"], ["trials", "Original Trial History"]] },
  { id: "settings", label: "Settings", icon: Settings2, description: "Saved setup, models, storage and system health", views: [["setup", "Setup & Resume"], ["models", "Model Connections"], ["storage", "Data & Storage"], ["system", "System Health"], ["practice", "Retained Practice"]] },
] as const;
export type WorkspaceArea = (typeof workspaceAreas)[number]["id"];
export type WorkspacePage = "dashboard" | "attention" | "markets" | "coverage" | "strategies" | "ai-lab" | "accounts" | "orders" | "analytics" | "risk" | "history" | "settings";
export type WorkspaceRoute = { area: WorkspaceArea; view: string; page: WorkspacePage; lab: string };
export function workspaceHref(area: WorkspaceArea, view?: string) {
  const first = workspaceAreas.find(item => item.id === area)!.views[0][0];
  return `#${area}${view && view !== first ? `?view=${view}` : ""}`;
}

/** Resolve original bookmarks as well as the new destinations; never rewrite evidence URLs. */
export function workspaceRoute(hash: string): WorkspaceRoute {
  const [base, query = ""] = hash.replace(/^#/, "").split("?");
  const params = new URLSearchParams(query);
  let area: WorkspaceArea = "overview", view = "dashboard";
  if (workspaceAreas.some(item => item.id === base)) {
    area = base as WorkspaceArea;
    const views = workspaceAreas.find(item => item.id === area)!.views;
    view = params.get("view") ?? views[0][0];
  } else {
    const legacy: Record<string, [WorkspaceArea, string]> = {
      dashboard: ["overview", "dashboard"], "ai-lab": ["results", "comparisons"],
      "role-research": ["research", "investigations"], "experiment-lab": ["research", "experiments"],
      "strategy-lab": ["research", "strategies"], strategies: ["research", "strategies"],
      knowledge: ["research", "knowledge"], "research-reviews": ["research", "knowledge"], "reviewer-connection": ["research", "knowledge"],
      "training-data": ["research", "training"], "model-lab": ["settings", "models"],
      "forward-learning": ["results", "qualification"], "live-readiness": ["results", "readiness"],
      risk: ["accounts", "safeguards"], orders: ["accounts", "orders"], analytics: ["results", "performance"],
      "account-economics": ["results", "costs"], experiment: ["accounts", "summary"], "paper-campaigns": ["accounts", "summary"],
      "live-quotes": ["markets", "watch"], operations: ["settings", "system"], options: ["settings", "practice"], roadmap: ["results", "readiness"],
    };
    if (Object.hasOwn(legacy, base)) [area, view] = legacy[base];
    if (["teaching:", "lab-result:", "lab-comparison:"].some(prefix => base.startsWith(prefix))) [area, view] = ["research", "training"];
  }
  if (area === "accounts" && ["performance", "comparisons", "qualification", "readiness"].includes(view)) area = "results";
  if (area === "research" && view === "autonomous") [area, view] = ["results", "comparisons"];
  if (area === "research" && view === "history") [area, view] = ["history", "matches"];
  if (area === "settings" && ["knowledge", "training"].includes(view)) area = "research";
  if (area === "overview" && params.has("notice")) view = "attention";
  // Original chart/finding links predate focused market pages and keep every parameter.
  if (area === "markets" && !params.has("view")) {
    if (params.has("candle_run")) view = "charts";
    else if ([...params.keys()].some(key => key.startsWith("scanner_") || key === "pattern_comparison_request" || key === "daily_shortlist")) view = "scanner";
  }
  const views = workspaceAreas.find(item => item.id === area)!.views;
  if (!views.some(item => item[0] === view)) view = views[0][0];
  let page: WorkspacePage = "ai-lab", lab = "roles";
  if (area === "overview") page = view === "attention" ? "attention" : "dashboard";
  else if (area === "markets") page = view === "coverage" ? "coverage" : "markets";
  else if (area === "research") {
    if (view === "strategies") page = "strategies";
    lab = ({ investigations: "roles", experiments: "experiments", knowledge: "knowledge", training: "training", controls: "controls" } as Record<string, string>)[view];
  } else if (area === "accounts") page = view === "summary" ? "accounts" : view === "safeguards" ? "risk" : "orders";
  else if (area === "results") {
    page = ["performance", "costs"].includes(view) ? "analytics" : view === "readiness" ? "risk" : "ai-lab";
    lab = view === "qualification" ? "learning" : "autonomous";
  } else if (area === "history") {
    page = ["trades", "journal"].includes(view) ? "orders" : ["investigations", "matches"].includes(view) ? "ai-lab" : "history";
    lab = view === "matches" ? "history" : "roles";
  } else { page = view === "models" ? "ai-lab" : "settings"; lab = "models"; }
  return { area, view, page, lab };
}
