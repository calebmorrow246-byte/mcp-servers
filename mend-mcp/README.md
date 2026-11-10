# Mend (SCA / SAST) MCP server

**Language:** Python · **Tools:** 32 (counted from source) · **Access:** Read-only by construction

> Part of the [`mcp-servers`](../README.md) collection. Scrubbed of identifying information (hosts, tenants, accounts, addresses are placeholders).

## Why this exists
Open-source and code-security findings were spread across Mend dashboards, which made it hard to answer 'what is vulnerable, how bad, and where?'.

## Why it was built this way
Named tools cover applications, projects, scan summaries, policy violations and dependency findings (by library or root library), and `api_get` reaches any GET operation in Mend's own OpenAPI description. Read-only is enforced in code, not by convention: the client only sends GET requests, and only to paths listed in the shipped `endpoints.json` (87 paths); report exports and finding suppression are deliberately not exposed. It also forwards two of Mend's own hosted assistant tools (library CVE/licence lookup and SAST review of a code snippet). Documented limits of the service account (some admin endpoints return 401/403) are kept in the README.

## What it improves
One place to ask for vulnerability and licence findings, with a hard guarantee that the assistant cannot change anything in Mend.

---

## Reference

Read-only MCP server for the Mend platform (SCA, SAST, container images, AI, administration). Hosted on mcp-host as `mend` (port 3121, service `MCP-mend`).

- **REST API 3.0**: `api_get` reaches every GET operation in Mend's OpenAPI description (`endpoints.json`, 87 paths; `list_endpoints` shows them). Named tools cover the common ones (projects, SCA findings by library or root library, libraries, licenses, SAST findings, image findings, zero-day events, reports, workflows, activity log, groups, users).
- **Mend hosted MCP assistants**: `check_dependency` (library CVE and license lookup) and `review_code_change` (SAST review of code you send) forward to `https://saas.whitesourcesoftware.com/mcp`.
- **Read-only by construction**: the client sends only GET requests, and only to paths in `endpoints.json`. Report exports (POST) and finding suppression are deliberately not exposed.
- **Auth**: shared service account `svc_infra`. Credential Manager target `Mend API` (user = email, password = Mend user key). Over HTTP each caller uses their own gateway bearer token; the Mend key never leaves the server.

## Run locally (stdio)

    uv venv .venv; uv pip install --link-mode=copy --python .venv\Scripts\python.exe -r requirements.txt
    .\Start-MendMCP.ps1

## Service account limits (verified 2026-11-10)

Works: applications, projects, totals (need `fromDate` and `toDate`), SCA findings, libraries, violations, zero-day events, reports, integrations. 403 or 401: users, groups, labels, activity logs, workflows (the service account's role lacks them; raise the role in Mend if needed). Scans list was empty for the first project checked; image, SAST and AI findings returned empty for it as well.

## Refreshing endpoints.json

Download `https://api-docs.mend.io/_bundle/platform/3.0.json?download`, keep the `get` operations, strip `/api/v3.0` from each path, and store `{path, summary, tag, query[]}` per entry.
