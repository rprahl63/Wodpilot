"""
FastMCP server exposing the WODpilot issue backlog to a dev session.

Runs as its own container on the NAS and talks to Postgres through the same
PostgREST shim as bot and web (`services.issues`). The published port is bound
to the NetBird IP only, so the server is unreachable from the LAN.

Counterpart on the client side: the `wodpilot-issues` skill in .claude/skills/.
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Any, Dict, List, Optional

from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

from services.issues import (
    claim_issue as _claim_issue,
    get_issue as _get_issue,
    list_issues as _list_issues,
    set_issue_status,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# Fields worth handing to a model – the raw row carries embedding-sized noise
# and internal timestamps that only cost context.
_FIELDS = (
    "id", "title", "body", "kind", "priority", "status",
    "resolution", "created_at", "resolved_at", "notified_at",
)


def _build_auth() -> Optional[StaticTokenVerifier]:
    """Bearer-token check from MCP_TOKEN, or None in dev.

    StaticTokenVerifier keeps the token in plain text, which upstream calls
    development-only. Acceptable here: the port is bound to the NetBird overlay,
    the token comes from the same .env as every other secret, and it guards a
    backlog rather than athlete data.
    """
    token = os.environ.get("MCP_TOKEN", "").strip()
    if not token:
        logger.warning("MCP_TOKEN not set – server runs without authentication")
        return None
    return StaticTokenVerifier(
        tokens={token: {"client_id": "wodpilot-dev", "scopes": ["issues"]}}
    )


mcp = FastMCP(name="wodpilot-issues", auth=_build_auth())


def _shape(issue: Dict[str, Any]) -> Dict[str, Any]:
    """Reduce a row to the fields a dev session needs, with a readable reporter."""
    out = {k: issue.get(k) for k in _FIELDS}
    reporter = issue.get("users") or {}
    out["reporter"] = reporter.get("full_name") or reporter.get("username") or "Unbekannt"
    return out


@mcp.tool
def list_issues(status: str = "open", limit: int = 50) -> List[Dict[str, Any]]:
    """List product issues reported by athletes, most urgent first.

    Args:
        status: 'open', 'in_progress', 'done', 'rejected', a comma-separated
            combination like 'open,in_progress', or 'all' for everything.
        limit: Maximum number of issues to return.
    """
    return [
        _shape(i)
        for i in _list_issues(status=None if status == "all" else status, limit=limit)
    ]


@mcp.tool
def get_issue(issue_id: int) -> Optional[Dict[str, Any]]:
    """Get one issue in full, including its body and reporter. None if unknown."""
    issue = _get_issue(issue_id)
    return _shape(issue) if issue else None


@mcp.tool
def claim_issue(issue_id: int) -> Optional[Dict[str, Any]]:
    """Take an issue: moves it open -> in_progress.

    Returns None when the issue is not 'open' anymore — then someone else is
    already working on it and you must pick a different one.
    """
    issue = _claim_issue(issue_id)
    return _shape(issue) if issue else None


@mcp.tool
def resolve_issue(issue_id: int, resolution: str) -> Optional[Dict[str, Any]]:
    """Close an issue as done and tell the reporter.

    Only call this once the change is deployed on the NAS — the reporter gets
    the message immediately and must be able to see the result.

    Args:
        issue_id: The issue to close.
        resolution: German, one to three sentences, describing what the athlete
            experiences differently now. Sent verbatim over Telegram without
            markup, so write plain prose.
    """
    issue = set_issue_status(issue_id, "done", resolution=resolution)
    return _shape(issue) if issue else None


@mcp.tool
def reject_issue(issue_id: int, reason: str) -> Optional[Dict[str, Any]]:
    """Close an issue as rejected and tell the reporter why.

    Args:
        issue_id: The issue to reject.
        reason: German, plain prose, sent verbatim to the reporter. Say what
            happens instead — a duplicate's number, or where the wish belongs.
    """
    issue = set_issue_status(issue_id, "rejected", resolution=reason)
    return _shape(issue) if issue else None


@mcp.tool
def reopen_issue(issue_id: int) -> Optional[Dict[str, Any]]:
    """Put an issue back to 'open', clearing its resolution.

    Use when a fix turned out not to work. The reporter is not notified.
    """
    issue = set_issue_status(issue_id, "open", resolution="", notify=False)
    return _shape(issue) if issue else None


def main() -> None:
    port = int(os.environ.get("MCP_PORT", "3002"))
    # 0.0.0.0 inside the container – Docker publishes it to the NetBird IP only.
    logger.info("Starting WODpilot issue MCP server on :%d", port)
    mcp.run(transport="http", host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
