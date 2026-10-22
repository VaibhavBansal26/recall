"""Generates the n8n workflow JSON in n8n/workflows/ (targets n8n 2.44).

Run `python3 n8n/build_workflows.py` after editing. The JSON files are what get imported; this
script only exists so the three workflows stay consistent with each other.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

OUT = Path(__file__).parent / "workflows"
BACKEND = "{{ $env.RECALL_BACKEND_URL }}"
SECRET_HEADER = {
    "sendHeaders": True,
    "headerParameters": {
        "parameters": [{"name": "X-Recall-Secret", "value": "={{ $env.RECALL_SHARED_SECRET }}"}]
    },
}


def node(name: str, type_: str, version: float, x: int, y: int, **params: Any) -> dict[str, Any]:
    return {
        "id": name.lower().replace(" ", "-"),
        "name": name,
        "type": f"n8n-nodes-base.{type_}",
        "typeVersion": version,
        "position": [x, y],
        "parameters": params,
    }


def link(*pairs: tuple[str, str, int]) -> dict[str, Any]:
    """connections from (source, target, output index) triples."""
    out: dict[str, Any] = {}
    for source, target, index in pairs:
        outputs = out.setdefault(source, {"main": []})["main"]
        while len(outputs) <= index:
            outputs.append([])
        outputs[index].append({"node": target, "type": "main", "index": 0})
    return out


def condition(left: str, operation: str, right: str | None = None, kind: str = "string") -> dict[str, Any]:
    op: dict[str, Any] = {"type": kind, "operation": operation}
    if right is None:
        op["singleValue"] = True
    cond: dict[str, Any] = {"id": "c-" + hashlib.sha1(f"{left}|{operation}".encode()).hexdigest()[:8], "leftValue": left, "operator": op}
    if right is not None:
        cond["rightValue"] = right
    return {
        "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
        "conditions": [cond],
        "combinator": "and",
    }


def if_node(name: str, x: int, y: int, cond: dict[str, Any]) -> dict[str, Any]:
    return node(name, "if", 2.2, x, y, conditions=cond, options={})


def respond(name: str, x: int, y: int, body: str, code: str | int) -> dict[str, Any]:
    return node(
        name,
        "respondToWebhook",
        1.1,
        x,
        y,
        respondWith="json",
        responseBody=body,
        options={"responseCode": code},
    )


def workflow(wf_id: str, name: str, nodes: list[dict[str, Any]], connections: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": wf_id,
        "name": name,
        "active": True,
        "nodes": nodes,
        "connections": connections,
        "settings": {"executionOrder": "v1"},
        "pinData": {},
    }


def ingest_url() -> dict[str, Any]:
    """POST /webhook/ingest-url {url, track?} -> backend /api/sources."""
    webhook = node("Webhook", "webhook", 2, 0, 200, httpMethod="POST", path="ingest-url", responseMode="responseNode", options={})
    webhook["webhookId"] = "recall-ingest-url"
    nodes = [
        webhook,
        if_node("Secret ok", 240, 200, condition("={{ $json.headers['x-recall-secret'] }}", "equals", "={{ $env.RECALL_SHARED_SECRET }}")),
        respond("Unauthorized", 480, 360, '={{ { "error": "unauthorized" } }}', 401),
        if_node("Has url", 480, 120, condition("={{ $json.body.url || $json.body.uri || '' }}", "notEmpty")),
        respond("Missing url", 720, 280, '={{ { "error": "send {\\"url\\": \\"https://...\\"}" } }}', 400),
        node(
            "Send to Recall",
            "httpRequest",
            4.2,
            720,
            40,
            method="POST",
            url=f"={BACKEND}/api/sources",
            sendBody=True,
            specifyBody="json",
            jsonBody="={{ { \"uri\": $json.body.url || $json.body.uri, \"track_hint\": $json.body.track || null } }}",
            options={"response": {"response": {"fullResponse": True, "neverError": True}}, "timeout": 30000},
            **SECRET_HEADER,
        ),
        respond("Reply", 960, 40, "={{ $json.body }}", "={{ $json.statusCode }}"),
    ]
    connections = link(
        ("Webhook", "Secret ok", 0),
        ("Secret ok", "Has url", 0),
        ("Secret ok", "Unauthorized", 1),
        ("Has url", "Send to Recall", 0),
        ("Has url", "Missing url", 1),
        ("Send to Recall", "Reply", 0),
    )
    return workflow("recall-ingest-url", "Recall: ingest URL", nodes, connections)


def ingest_inbox() -> dict[str, Any]:
    """Files dropped in /files/inbox: PDFs are uploaded, text/Markdown/.url files are scanned for links."""
    nodes = [
        node(
            "Watch inbox",
            "localFileTrigger",
            1,
            0,
            200,
            triggerOn="folder",
            path="/files/inbox",
            events=["add"],
            options={"awaitWriteFinish": True, "ignoreInitial": False, "usePolling": True},
        ),
        if_node("Is PDF", 240, 200, condition("={{ $json.path }}", "endsWith", ".pdf")),
        node("Read PDF", "readWriteFile", 1, 480, 80, operation="read", fileSelector="={{ $json.path }}", options={"dataPropertyName": "data"}),
        node(
            "Upload PDF",
            "httpRequest",
            4.2,
            720,
            80,
            method="POST",
            url=f"={BACKEND}/api/sources/upload",
            sendBody=True,
            contentType="multipart-form-data",
            bodyParameters={"parameters": [{"parameterType": "formBinaryData", "name": "file", "inputDataFieldName": "data"}]},
            options={"response": {"response": {"neverError": True}}, "timeout": 60000},
            **SECRET_HEADER,
        ),
        if_node("Is text or links", 480, 320, condition("={{ /\\.(txt|md|url|html?)$/i.test($json.path) }}", "true", kind="boolean")),
        node("Read text file", "readWriteFile", 1, 720, 300, operation="read", fileSelector="={{ $json.path }}", options={"dataPropertyName": "data"}),
        node("Text from file", "extractFromFile", 1, 960, 300, operation="text", binaryPropertyName="data", options={}),
        node(
            "Find links",
            "code",
            2,
            1200,
            300,
            jsCode=(
                "// One source per link in the file; if there are no links, a long text is ingested as text.\n"
                "const text = String($input.first().json.data || '');\n"
                "const urls = [...new Set(text.match(/https?:\\/\\/[^\\s<>\"')]+/g) || [])];\n"
                "if (urls.length) return urls.map((u) => ({ json: { uri: u } }));\n"
                "return text.trim().split(/\\s+/).length >= 30 ? [{ json: { text: text.trim() } }] : [];\n"
            ),
        ),
        node(
            "Send to Recall",
            "httpRequest",
            4.2,
            1440,
            300,
            method="POST",
            url=f"={BACKEND}/api/sources",
            sendBody=True,
            specifyBody="json",
            jsonBody="={{ $json }}",
            options={"response": {"response": {"neverError": True}}, "timeout": 30000},
            **SECRET_HEADER,
        ),
    ]
    connections = link(
        ("Watch inbox", "Is PDF", 0),
        ("Is PDF", "Read PDF", 0),
        ("Is PDF", "Is text or links", 1),
        ("Read PDF", "Upload PDF", 0),
        ("Is text or links", "Read text file", 0),
        ("Read text file", "Text from file", 0),
        ("Text from file", "Find links", 0),
        ("Find links", "Send to Recall", 0),
    )
    return workflow("recall-ingest-inbox", "Recall: ingest inbox folder", nodes, connections)


def sync_export() -> dict[str, Any]:
    """Nightly export of every note to Markdown files in /files/exports (also runnable by hand)."""
    nodes = [
        node("Every night", "scheduleTrigger", 1.2, 0, 120, rule={"interval": [{"field": "days", "daysInterval": 1, "triggerAtHour": 3}]}),
        node("Run now", "manualTrigger", 1, 0, 300),
        node(
            "Get notes",
            "httpRequest",
            4.2,
            240,
            200,
            method="GET",
            url=f"={BACKEND}/api/export",
            options={"timeout": 60000},
            **SECRET_HEADER,
        ),
        node("One item per note", "splitOut", 1, 480, 200, fieldToSplitOut="files", options={}),
        node(
            "To file",
            "convertToFile",
            1.1,
            720,
            200,
            operation="toText",
            sourceProperty="content",
            binaryPropertyName="data",
            options={"fileName": "={{ $json.path.replace('/', '__') }}"},
        ),
        node(
            "Write markdown",
            "readWriteFile",
            1,
            960,
            200,
            operation="write",
            fileName="=/files/exports/{{ $binary.data.fileName }}",
            dataPropertyName="data",
            options={"append": False},
        ),
    ]
    connections = link(
        ("Every night", "Get notes", 0),
        ("Run now", "Get notes", 0),
        ("Get notes", "One item per note", 0),
        ("One item per note", "To file", 0),
        ("To file", "Write markdown", 0),
    )
    return workflow("recall-sync-export", "Recall: nightly Markdown export", nodes, connections)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for slug, wf in {
        "ingest-url": ingest_url(),
        "ingest-inbox": ingest_inbox(),
        "sync-export": sync_export(),
    }.items():
        (OUT / f"{slug}.json").write_text(json.dumps(wf, indent=2) + "\n")
        print("wrote", OUT / f"{slug}.json")
