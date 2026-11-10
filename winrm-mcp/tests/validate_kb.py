"""
Validate knowledge/known_events.json. Run before committing any change to the KB:

    .venv\\Scripts\\python.exe tests\\validate_kb.py

Exits 0 when every check passes (warnings are allowed), 1 otherwise.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import kb  # noqa: E402

REQUIRED = ("source", "eventId", "priority", "suggestedFix", "rootCauseAnalysis", "scope", "reviewed", "addedOn", "addedBy")
errors: list[str] = []
warnings: list[str] = []


def label(e):
    return f"{e.get('source')}|{e.get('eventId')}" + (f" /{e['messagePattern'][:40]}/" if e.get("messagePattern") else "")


def main() -> int:
    try:
        doc = json.loads(kb.KB_PATH.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        print(f"FAIL: cannot parse {kb.KB_PATH}: {exc}")
        return 1
    if doc.get("schemaVersion") != "2.0":
        errors.append(f"schemaVersion is {doc.get('schemaVersion')!r}, expected '2.0'")
    entries = doc.get("entries")
    if not isinstance(entries, list) or not entries:
        print("FAIL: 'entries' missing or empty")
        return 1

    seen: dict[tuple, str] = {}
    for e in entries:
        name = label(e)
        for key in REQUIRED:
            if e.get(key) in (None, ""):
                errors.append(f"{name}: missing '{key}'")
        if e.get("priority") not in ("H", "M", "L"):
            errors.append(f"{name}: priority must be H, M or L (got {e.get('priority')!r})")
        if e.get("scope") not in kb.SCOPES:
            errors.append(f"{name}: scope must be one of {sorted(kb.SCOPES)} (got {e.get('scope')!r})")
        if not isinstance(e.get("reviewed"), bool):
            errors.append(f"{name}: reviewed must be true or false")
        if not isinstance(e.get("eventId"), int):
            errors.append(f"{name}: eventId must be an integer")
        if "tags" in e and not isinstance(e["tags"], list):
            errors.append(f"{name}: tags must be a list")

        key = (str(e.get("source")).casefold(), e.get("eventId"), e.get("messagePattern") or "", e.get("scope"))
        if key in seen:
            errors.append(f"{name}: duplicate of an earlier entry (same source, ID, pattern and scope)")
        seen[key] = name

        pattern = e.get("messagePattern")
        if pattern:
            try:
                compiled = re.compile(pattern)
            except re.error as exc:
                errors.append(f"{name}: messagePattern does not compile: {exc}")
                continue
            example = e.get("exampleMessage")
            if example is None:
                warnings.append(f"{name}: has a messagePattern but no exampleMessage to prove it")
            elif not compiled.search(example):
                errors.append(f"{name}: messagePattern does not match its own exampleMessage")
        if e.get("tags") and "benign-if-scan-correlated" in e["tags"] and "benign" in e["tags"]:
            errors.append(f"{name}: use 'benign' OR 'benign-if-scan-correlated', not both")

    # Every exampleMessage must resolve to an entry for its own source/ID through the real matcher
    for e in entries:
        example = e.get("exampleMessage")
        if example and e.get("scope") in kb.SCOPES:
            hit = kb.match_entry(e["source"], e["eventId"], example, e["scope"] if e["scope"] != "both" else "server", doc)
            if hit is None:
                errors.append(f"{label(e)}: exampleMessage is not matched by any entry via the matcher")

    unreviewed = sum(1 for e in entries if e.get("reviewed") is False)
    print(f"{len(entries)} entries | scope {_count(entries, 'scope')} | priority {_count(entries, 'priority')} | unreviewed {unreviewed}")
    for w in warnings:
        print(f"WARN: {w}")
    for err in errors:
        print(f"FAIL: {err}")
    print("PASS" if not errors else f"{len(errors)} error(s)")
    return 0 if not errors else 1


def _count(entries, field):
    out: dict = {}
    for e in entries:
        out[e.get(field)] = out.get(e.get(field), 0) + 1
    return out


if __name__ == "__main__":
    sys.exit(main())
