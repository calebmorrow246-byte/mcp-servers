# Box MCP server

**Language:** Python · **Tools:** 50 (counted from source) · **Access:** Read-only

> Part of the [`mcp-servers`](../README.md) collection. Scrubbed of identifying information (hosts, tenants, accounts, addresses are placeholders).

## Why this exists
Policies, runbooks and project documents live in Box, and finding the right one meant clicking through folders or asking someone. An AI assistant needs to read that content, but handing it a person's password is not an option.

## Why it was built this way
Acts as one dedicated service user through a Box Client Credentials Grant app limited to read-only scope, so nobody shares a password and access can be revoked at the app. The secret is stored in Windows Credential Manager. Beyond listing and search, it extracts text from PDF, DOCX and XLSX files so the assistant can actually read documents, not just list them.

## What it improves
Natural-language search and reading across Box (files, folders, comments, collaborations, metadata templates, hubs) instead of manual folder hunting, with no human credential involved.

---

## Reference

Read-only MCP server for **Box**, hosted on mcp-host. It acts as one Box user (box.admin) through a Box
Client Credentials Grant app, so nobody needs the box.admin password.


## Credential model (required by the hosting standard)
- **Type:** service account, acting as box.admin. Read-only.
- Credential Manager target `Box CCG` on mcp-host: user = Box app client ID, password = client secret.
- Non-secret: `-SubjectId` (box.admin's Box user ID) in `Start-BoxMCP.ps1`.
- Box app: Custom App, Server Authentication (Client Credentials Grant), read-only scope, "Generate User Access
  Tokens" and "App + Enterprise Access" enabled, authorized in Admin Console > Platform Apps.

## Tools (all read-only)
| Tool | What it returns |
|------|-----------------|
| `get_token_status` / `who_am_i` | Auth check (never the token) and the Box user the server acts as |
| `search_files` | Keyword search with type, folder, extension and owner filters |
| `list_folder_items` / `get_folder` / `get_file` | Folder contents and details |
| `get_file_text` | Text of a file (direct for text types, Box extracted text for Word/PDF) |
| `list_file_comments` / `list_collaborations` | Comments and who has access |
| `list_metadata_templates` | Enterprise metadata templates |
| `list_hubs` / `get_hub` / `list_hub_items` | Box Hubs |
| `list_hub_collaborations` | Who has access to a Hub |
| `list_users` / `get_user` / `list_user_memberships` / `list_user_email_aliases` | Enterprise users, status, groups, aliases |
| `users_by_domain` | Users counted by login email domain and status (stand-in for Domain Management, which Box does not expose in the API) |
| `list_groups` / `get_group` / `list_group_members` / `list_group_collaborations` | Groups, members, and what they can access |
| `list_admin_events` | Enterprise admin audit log (needs the enterprise events scope) |
| `list_collaboration_allowlist` / `get_collaboration_allowlist_entry` / `list_collaboration_allowlist_exempt_users` | Domain restrictions for collaboration invites |
| `list_pending_collaborations` / `get_collaboration` | Open invitations, one collaboration |
| `list_legal_hold_policies` / `get_legal_hold_policy` / `list_legal_hold_assignments` / `list_files_on_hold` | Legal hold |
| `list_retention_policies` / `get_retention_policy` / `list_retention_assignments` / `list_files_under_retention` | Retention |
| `list_file_versions` / `list_file_tasks` / `get_file_metadata` / `get_folder_metadata` | Item details; metadata includes security classification |
| `list_trash` / `list_folder_locks` / `get_web_link` | Trash, folder locks, web links |
| `list_webhooks` / `get_webhook` / `list_storage_policies` | Enterprise configuration |
| `list_terms_of_service` / `list_terms_of_service_user_statuses` / `list_sign_requests` | Terms of service, Box Sign |

## Scope notes (2026-11-10 live test)
- 403 `insufficient_scope`: `list_file_comments`, `list_admin_events`, `list_legal_hold_policies`, `list_retention_policies`, `list_sign_requests`. Enable the matching scope in the Box Developer Console, then re-authorize the app in the Admin Console.
- `list_file_tasks` returned 403 `forbidden` on a file box.admin could otherwise read; `list_terms_of_service` returned 404 (probably none configured); `list_trash` timed out (box.admin's trash is large).
- Not covered by the Box API: Admin Console Domain Management (verified domains). `list_groups` returned zero groups.

## Safety
- GET only, and only the allow-listed paths in `client.py` (`ALLOWED_PATH`).
- No write tool and no Box AI tool (nothing under `/ai`), so Box AI usage is never triggered.
- Download and representation URLs must be on Box hosts.
- Token request failures return the status and Box's error text only; the secret is never echoed.

## Hosting
- **Port:** 3120. Route: `https://mcp-host.example.com/mcp/box`.
- NSSM service `MCP-box` as svc-mcp, launched by `Start-BoxMCP.ps1 -Transport http -Port 3120`.
- Create the virtual environment with `uv venv .venv; uv pip install --link-mode=copy --python .venv\Scripts\python.exe -r requirements.txt`.

## Testing
1. Run locally over stdio with a workstation credential, then `get_token_status` and `who_am_i`.
2. Visibility: `list_folder_items` and `search_files` on content owned by another user. If box.admin cannot see it,
   either collaborate box.admin on it or ask Box support for the `enterprise_content` scope.

# Authored by Caleb A. Morrow
