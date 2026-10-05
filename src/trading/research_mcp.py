"""Stateless private MCP adapter; CP22 remains the scope/revocation/budget owner."""

import json
from typing import Any

import httpx

from trading.research_actors import ResearchActors
from trading.research_knowledge import KnowledgeQuery
from trading.research_reviews import ResearchReviews

PROTOCOLS = {"2025-11-25", "2025-03-26"}
NAMES = {"review_get_packet", "knowledge_search", "evidence_read", "review_get_result"}


def tools() -> list[dict[str, Any]]:
    result = []
    for name in sorted(NAMES):
        properties: dict[str, Any] = {"review": {"type": "string", "maxLength": 60}}
        if name == "knowledge_search":
            properties["query"] = {"type": "string", "minLength": 1, "maxLength": 300}
        if name == "evidence_read":
            properties["citation"] = {"type": "string", "maxLength": 60}
        result.append(
            {
                "name": name,
                "description": "Read permitted frozen Q-Trades research: " + name,
                "inputSchema": {
                    "type": "object",
                    "properties": properties,
                    "required": list(properties),
                    "additionalProperties": False,
                },
                "annotations": {
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "openWorldHint": False,
                },
            }
        )
    return result


class ResearchMCP:
    def __init__(self, actors: ResearchActors, reviews: ResearchReviews):
        self.actors, self.reviews = actors, reviews
        with actors.registry.lock:
            actors.registry.db.execute(
                "CREATE TABLE IF NOT EXISTS review_tool_reads("
                "review TEXT,receipt TEXT,PRIMARY KEY(review,receipt))"
            )

    def call(self, token: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name not in NAMES:
            raise ValueError("Tool is outside the permitted research surface")
        required = {"review"} | (
            {"query"}
            if name == "knowledge_search"
            else {"citation"}
            if name == "evidence_read"
            else set()
        )
        if set(args) != required or not all(isinstance(v, str) for v in args.values()):
            raise ValueError("Strict research tool arguments required")
        if len(args["review"]) > 60:
            raise ValueError("Review unavailable in this permitted context")
        run = self.reviews.get(args["review"])
        with self.actors.registry.transaction():
            self.actors._charge(self.actors.auth(token, run["task"]), 0)
        if name in {"review_get_packet", "review_get_result", "evidence_read"}:
            self.reviews.knowledge.check_passages(
                self.reviews.delivered_passages(run["id"]), external=True
            )
        if name == "review_get_packet":
            value = {"packet": run["packet"], "sha256": run["packet_sha"]}
        elif name == "review_get_result":
            value = {"state": run["state"], "result": run["result"], "reason": run["reason"]}
        elif name == "knowledge_search":
            value = self.reviews.knowledge.retrieve(
                KnowledgeQuery(
                    text=args["query"],
                    cutoff=run["packet"]["cutoff"],
                    symbol="BTCUSD",
                    horizon=self.reviews.worker.get(run["task"])["context"]["question"]["horizon"],
                ),
                external=True,
                task=run["task"],
            )
        else:
            if args["citation"] in run["packet"]["evidence"]:
                value = {
                    "citation": args["citation"],
                    "task": run["task"],
                    "cutoff": run["packet"]["cutoff"],
                    "owner": "existing frozen CP18 evidence / disclosure",
                    "evidence": run["packet"]["evidence"][args["citation"]],
                }
                with self.actors.registry.transaction():
                    actor = self.actors.auth(token, run["task"])
                    self.actors._charge(actor, len(json.dumps(value).encode()), request=False)
                return {"content": [{"type": "text", "text": json.dumps(value)}], "isError": False}
            passages = list(run["packet"]["knowledge"]["passages"])
            with self.actors.registry.lock:
                receipts = self.actors.registry.db.execute(
                    "SELECT receipt FROM review_tool_reads WHERE review=?",
                    (run["id"],),
                ).fetchall()
            for receipt in receipts:
                passages.extend(self.reviews.knowledge.receipt(receipt[0])["passages"])
            passage = next((p for p in passages if p["citation"] == args["citation"]), None)
            if passage is None:
                raise ValueError("Citation is unavailable in this delivered review context")
            # Recheck permission/source status at fetch; return only the exact delivered section.
            self.reviews.knowledge.read(
                passage["source"],
                passage["revision"],
                cutoff=run["packet"]["cutoff"],
                external=True,
            )
            value = passage
        encoded = json.dumps(value, allow_nan=False)
        if len(encoded.encode()) > 65536:
            raise ValueError("Tool output exceeds its 64 KiB boundary")
        with self.actors.registry.transaction():
            actor = self.actors.auth(token, run["task"])
            self.actors._charge(actor, len(encoded.encode()), request=False)
            if name == "knowledge_search":
                self.actors.registry.db.execute(
                    "INSERT OR IGNORE INTO review_tool_reads VALUES(?,?)", (run["id"], value["id"])
                )
        return {"content": [{"type": "text", "text": encoded}], "isError": False}

    def rpc(self, token: str, body: dict[str, Any]) -> dict[str, Any] | None:
        self.actors.auth(token)
        if (
            set(body) - {"jsonrpc", "id", "method", "params"}
            or body.get("jsonrpc") != "2.0"
            or not isinstance(body.get("method"), str)
        ):
            raise ValueError("One valid JSON-RPC request required")
        method, identity = body["method"], body.get("id")
        params = body.get("params", {})
        if not isinstance(params, dict):
            raise ValueError("JSON-RPC parameters must be an object")
        if method == "notifications/initialized" and identity is None:
            with self.actors.registry.transaction():
                self.actors._charge(self.actors.auth(token), 0)
            return None
        if not isinstance(identity, (str, int)) or isinstance(identity, bool):
            raise ValueError("JSON-RPC request identity required")
        if method == "initialize":
            version = params.get("protocolVersion", "2025-11-25")
            result = {
                "protocolVersion": version if version in PROTOCOLS else "2025-11-25",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "qtrades-scoped-research", "version": "1"},
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": tools()}
        elif method == "tools/call":
            if set(params) != {"name", "arguments"} or not isinstance(params["arguments"], dict):
                raise ValueError("Strict tools/call parameters required")
            result = self.call(token, params["name"], params["arguments"])
        else:
            with self.actors.registry.transaction():
                self.actors._charge(self.actors.auth(token), 0)
            return {
                "jsonrpc": "2.0",
                "id": identity,
                "error": {"code": -32601, "message": "Research method unavailable"},
            }
        if method != "tools/call":
            with self.actors.registry.transaction():
                self.actors._charge(self.actors.auth(token), len(json.dumps(result).encode()))
        return {"jsonrpc": "2.0", "id": identity, "result": result}


class LocalMCPClient:
    """Only the owned loopback endpoint; no user/model-selected network targets."""

    def __init__(self, client: httpx.AsyncClient, token: str):
        self.client, self.token, self.counter = client, token, 0

    async def rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.counter += 1
        response = await self.client.post(
            "/api/research/mcp",
            headers={
                "Authorization": "Bearer " + self.token,
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-11-25",
            },
            json={"jsonrpc": "2.0", "id": self.counter, "method": method, "params": params},
        )
        response.raise_for_status()
        if len(response.content) > 70000:
            raise ValueError("MCP response exceeds the client budget")
        body = response.json()
        if "error" in body or body.get("id") != self.counter:
            raise ValueError("MCP call refused or response identity changed")
        return dict(body["result"])

    async def initialize(self) -> None:
        result = await self.rpc(
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "qtrades-reviewer", "version": "1"},
            },
        )
        if result["protocolVersion"] != "2025-11-25":
            raise ValueError("MCP protocol negotiation failed")
        initialized = await self.client.post(
            "/api/research/mcp",
            headers={
                "Authorization": "Bearer " + self.token,
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-11-25",
            },
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        initialized.raise_for_status()
        if initialized.status_code != 202:
            raise ValueError("MCP initialization notification was not accepted")

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self.rpc("tools/call", {"name": name, "arguments": arguments})
