# MCP Servers — giving AI assistants safe, scoped access to infrastructure

Twenty [Model Context Protocol](https://modelcontextprotocol.io) servers that connect an AI assistant to the systems a small infrastructure team runs every day: ITSM, monitoring, vulnerability management, backup, storage, virtualisation, DNS and email security, identity and secrets discovery, CMDB and IPAM, and more. Fourteen are Python (FastMCP) and six are TypeScript (official MCP SDK).

> This repository has been scrubbed of identifying information: company, tenant, host and account names, addresses and IDs are placeholders. Several servers began as a colleague's first draft, written with the toolbox and reference material I built for that purpose. For every one of them I reworked, extended, tested and deployed the result to production and verified it; file headers note where a first draft came from.

---

## Why this exists

Routine infrastructure work is mostly *finding and cross-referencing facts* spread across a dozen consoles: is the backup green, what is this IP, which hosts carry this vulnerability, what renews soon. Every console is its own login, its own query language and its own click path. Putting an AI assistant in front of them turns those round trips into questions. But an assistant with raw admin credentials is a liability, so the real engineering question was **how much access each integration should have, and where the guarantee should live**.

## Why they were built this way

- **One small server per system, with the narrowest useful surface.** Many are 3 to 15 tools. Fewer, well-described tools beat a thin wrapper over a whole API.
- **The safety guarantee is placed deliberately, and each README says where it lives.**
  - *By construction (nothing to misuse):* Route 53 has no write tool at all; Mend only sends GETs to an allow-listed path file; the Unixi proxy only exposes a fixed allow-list of upstream tools so a vendor adding a write tool later changes nothing; WinRM goes through a constrained read-only JEA endpoint (no shell); NetApp and UCS implement no mutating calls.
  - *By guarded writes:* BrandSight's every write defaults to `dry_run: true`; Device42's single write runs as the caller's own login with a dry-run default, field allow-list, 25-device cap and change log; PRTG's pause requires a reason written to PRTG's audit trail; WP Engine exposes only two approved non-destructive writes.
  - *By the credential, not the code:* XenServer's server can issue mutating calls, and it is read-only in practice because its account has a read-only role on the hypervisor (verified when a cancel was refused with `RBAC_PERMISSION_DENIED`). The README documents this explicitly.
  - *Broad by design, and labelled that way:* Freshservice (98 tools, about 40 able to change data) and Valimail expose full read/write; that breadth is exactly why a scoped, purpose-built app was used for automated ticket triage instead.
- **Secrets never live in client config.** Every server has a `Start-*MCP.ps1` launcher that reads credentials from Windows Credential Manager at start-up and hands them to the child process only.
- **A shared, reviewed transport.** Twelve of the fourteen Python servers use an identical `mcp_transport.py` (the other two are variants) and each TypeScript server has an equivalent `src/transport.ts`. It supports stdio for local use and Streamable HTTP for central hosting. In HTTP mode it requires a per-user bearer token (stored only as SHA-256 hashes, re-read when the file changes so revocation is immediate), compares in constant time, caps request bodies at 4 MB, and writes one audit line per request: user, JSON-RPC method and tool name, **never the arguments**. Optional per-user backend credentials arrive as headers and are never logged.
- **Hosted centrally.** Servers run as Windows services on one host behind a TLS front end, each on a dedicated port and route, so users hold a personal token and never the backend key.
- **Verified against the live system, not the docs.** Endpoints, quirks and permission limits were checked against real instances, and the READMEs record what was found (for example Commvault paths that 404 on a given version, or Mend endpoints a service account can't reach).

## What it improves

- Cross-system questions that used to take several consoles are answered in one conversation.
- Each assistant action is attributable (per-user token plus audit line, and for Device42 the person's own login).
- Adding a system is a small, repeatable job: copy the pattern, pick the narrowest tools, write the launcher.

## The servers

| Server | Language | Tools | Access |
|---|---|---|---|
| [box-mcp](box-mcp) | Python | 50 | Read-only |
| [commvault-mcp](commvault-mcp) | Python | 14 | Read-only |
| [delinea-mcp](delinea-mcp) | Python | 26 | Read-only, metadata only |
| [device42-mcp](device42-mcp) | Python | 21 | Read-only + one guarded write |
| [freshservice_mcp](freshservice_mcp) | Python | 98 | Broad read/write |
| [mcp-brandsight](mcp-brandsight) | TypeScript | 23 | Read/write, writes default to dry run |
| [mend-mcp](mend-mcp) | Python | 32 | Read-only by construction |
| [metallic-mcp](metallic-mcp) | Python | 19 | Read-only |
| [netapp-mcp](netapp-mcp) | Python | 29 | Read-only |
| [phpipam-mcp-server](phpipam-mcp-server) | TypeScript | 13 | Read-only |
| [prtg-mcp-server](prtg-mcp-server) | TypeScript | 5 | Read-only + pause/resume |
| [qualys-mcp-server](qualys-mcp-server) | TypeScript | 7 | Read-only |
| [route53-mcp-server](route53-mcp-server) | TypeScript | 3 | Read-only (no write path) |
| [saas-manager-mcp](saas-manager-mcp) | Python | 12 | Read-only |
| [ucs-mcp](ucs-mcp) | Python | 10 | Read-only by construction |
| [unixi-mcp](unixi-mcp) | Python | 7 allow-listed + derived | Read-only by construction |
| [valimail-mcp-server](valimail-mcp-server) | TypeScript | 26 | Read/write |
| [winrm-mcp](winrm-mcp) | Python | 15 | Read-only by construction |
| [wpengine-mcp](wpengine-mcp) | Python | 27 | Read-only + two approved writes |
| [xenserver-mcp](xenserver-mcp) | Python | 62 | Read-only via hypervisor role |

Tool counts are counted from source at the time of publishing.

## Run one

```powershell
# Python server (example: Mend)
uv venv .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
.\Start-MendMCP.ps1                   # stdio for local use; add -Transport http -Port <n> to host it

# TypeScript server (example: PRTG)
npm install; npm run build
.\Start-PrtgMCP.ps1
```

Store each credential once in Windows Credential Manager under the target named in that server's README, then register the launcher as the MCP command (see `.mcp.json.example`). Review a server's tool list before pointing it at production, especially those marked read/write.

## Honest limits

- Most servers were developed and tested interactively against live systems; there is no automated regression suite for them (the WinRM knowledge base has a validator). Adding mocked-HTTP tests and CI is the next hardening step.
- Verification dates and permission limits in the READMEs reflect the time of writing.
- Several folders (marked in their READMEs) ship generic example data in place of environment-specific allow-lists and knowledge bases.

## License

MIT — see `LICENSE`.
