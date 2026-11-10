"""
Known-events knowledge base: loading and matching.

Matching rules (ported from the retired an earlier PowerShell module module):
  1. Filter entries by exact source + eventId (source compared case-insensitively).
  2. Prefer entries whose messagePattern (regex) matches the sample message.
  3. Otherwise fall back to the entry for that source+eventId with no messagePattern.
  4. Otherwise no match.
Entries are limited to the requested scope (server and both by default).
"""

import json
import re
from pathlib import Path
from typing import Any, Optional

KB_PATH = Path(__file__).resolve().parent / "knowledge" / "known_events.json"
GUIDANCE_PATH = Path(__file__).resolve().parent / "knowledge" / "triage_guidance.md"

SCOPES = {"server", "workstation", "both"}
_cache: dict[str, Any] = {"mtime": None, "doc": None}


def load_kb(path: Path = KB_PATH) -> dict[str, Any]:
    """Load the KB, re-reading only when the file changes so edits apply without a restart."""
    mtime = path.stat().st_mtime
    if _cache["mtime"] != mtime:
        _cache["doc"] = json.loads(path.read_text(encoding="utf-8-sig"))
        _cache["mtime"] = mtime
    return _cache["doc"]


def in_scope(entry: dict[str, Any], scope: str) -> bool:
    entry_scope = entry.get("scope", "both")
    return scope == "any" or entry_scope == "both" or entry_scope == scope


def match_entry(source: str, event_id: int, sample: str, scope: str = "server",
                doc: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
    doc = doc or load_kb()
    candidates = [
        e for e in doc["entries"]
        if str(e["source"]).casefold() == str(source).casefold()
        and int(e["eventId"]) == int(event_id) and in_scope(e, scope)
    ]
    if not candidates:
        return None
    for entry in candidates:
        pattern = entry.get("messagePattern")
        if pattern and re.search(pattern, sample or ""):
            return entry
    defaults = [e for e in candidates if not e.get("messagePattern")]
    return defaults[0] if defaults else None


def public_view(entry: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """The fields a caller needs, plus derived flags for the SQM decision."""
    if entry is None:
        return None
    tags = list(entry.get("tags", []))
    return {
        "priority": entry["priority"],
        "suggestedFix": entry["suggestedFix"],
        "rootCauseAnalysis": entry["rootCauseAnalysis"],
        "tags": tags,
        "scope": entry.get("scope", "both"),
        "reviewed": bool(entry.get("reviewed", True)),
        "benign": "benign" in tags,
        "needsScanCorrelation": "benign-if-scan-correlated" in tags,
    }


def classify_group(group: dict[str, Any], scope: str = "server") -> dict[str, Any]:
    """
    Attach KB results to one Get-RoEventSummary group. Each returned message variant is matched on
    its own, since one provider/ID group can mix different messages.
    """
    doc = load_kb()
    variants = group.get("Variants") or [{"Count": group.get("Count"), "Sample": group.get("Sample", "")}]
    results = []
    for variant in variants:
        entry = match_entry(group["Provider"], group["Id"], variant.get("Sample", ""), scope, doc)
        results.append({"count": variant.get("Count"), "sample": variant.get("Sample", ""), "kb": public_view(entry)})
    matched = [r for r in results if r["kb"]]
    # Variants beyond the top 3 are not matched; say so, so a "matched" result is never overstated
    total_variants = int(group.get("VariantsTotal") or len(results))
    if matched and len(matched) == len(results) and total_variants <= len(results):
        status = "matched"
    elif matched:
        status = "partial"
    else:
        status = "unknown"
    out = {
        "log": group.get("LogName"), "provider": group["Provider"], "eventId": group["Id"],
        "level": group.get("Level"), "count": group.get("Count"),
        "firstSeen": group.get("FirstSeen"), "lastSeen": group.get("LastSeen"),
        "status": status, "variantsTotal": total_variants,
    }
    if status == "matched":
        out["kb"] = results[0]["kb"]  # dominant variant's entry
        if len({json.dumps(r["kb"], sort_keys=True) for r in results}) > 1:
            out["variants"] = results  # variants map to different entries: show each
    else:
        # Samples only where a decision is still needed, to keep the response small
        out["variants"] = results
        out["kb"] = matched[0]["kb"] if matched else None
    return out


def list_entries(scope: str = "any", source: Optional[str] = None, event_id: Optional[int] = None,
                 tag: Optional[str] = None, reviewed: Optional[bool] = None) -> list[dict[str, Any]]:
    out = []
    for e in load_kb()["entries"]:
        if not in_scope(e, scope):
            continue
        if source and source.casefold() not in str(e["source"]).casefold():
            continue
        if event_id is not None and int(e["eventId"]) != int(event_id):
            continue
        if tag and tag.casefold() not in [t.casefold() for t in e.get("tags", [])]:
            continue
        if reviewed is not None and bool(e.get("reviewed", True)) != reviewed:
            continue
        out.append({k: e.get(k) for k in ("source", "eventId", "priority", "scope", "reviewed", "tags",
                                          "messagePattern", "suggestedFix", "rootCauseAnalysis")})
    return out
