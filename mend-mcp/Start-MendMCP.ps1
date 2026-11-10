# Authored by Caleb A. Morrow

<#
.SYNOPSIS
    Starts the Mend MCP server, loading the shared Mend API key from Windows Credential Manager.

.DESCRIPTION
    Retrieves the Mend user key (target: Mend API; password = user key) from Windows Credential
    Manager and launches the Python MCP server (read-only Mend REST API 3.0 tools plus Mend's hosted
    assistants) using the repo's own virtual environment (.venv).

    Credential type: shared service account (svc_infra). Clients never see the key; over HTTP
    they authenticate with their own bearer token.

.PARAMETER Transport
    stdio (default) for a local client, or http to serve Streamable HTTP at /mcp.

.PARAMETER Port
    Listening port for -Transport http (3121 in the MCP port map).

.PARAMETER BindAddress
    Bind address. Keep the default loopback address; the TLS front end publishes it.

.PARAMETER UserEmail
    Mend service account email sent as X-UserEmail. Not a secret.

.PARAMETER OrgUuid
    Mend organization UUID sent as X-OrgId. Not a secret.

.PARAMETER CredentialTarget
    Credential Manager target holding the Mend user key (default: Mend API).

.EXAMPLE
    .\Start-MendMCP.ps1 -Transport http -Port 3121 -Verbose

.NOTES
    Store the credential with Server\MCP-Hosting\Set-McpServiceCredentials.ps1 -Target 'Mend API'
    (on a workstation, cmdkey rejects spaces: store it as MendAPI and pass -CredentialTarget MendAPI).

    Create the virtual environment once with:
      uv venv .venv; uv pip install --link-mode=copy --python .venv\Scripts\python.exe -r requirements.txt
#>
[CmdletBinding()]
param(
    [ValidateSet('stdio', 'http')]
    [string]$Transport = 'stdio',

    [ValidateRange(1, 65535)]
    [int]$Port,

    [string]$BindAddress = '127.0.0.1',

    [string]$UserEmail = 'svc_infra@example.com',

    [ValidatePattern('^[0-9a-fA-F-]{36}$')]
    [string]$OrgUuid = '00000000-0000-0000-0000-000000000000',

    [string]$CredentialTarget = 'Mend API'
)

$ErrorActionPreference = 'Stop'

if ($Transport -eq 'http' -and -not $Port) {
    Write-Error '-Port is required when -Transport is http'
    exit 1
}

$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -Path $python)) {
    Write-Error "Python virtual environment not found at $python. Create it first (see .NOTES)."
    exit 1
}

try {
    Write-Verbose "$(Get-Date -Format o) Retrieving Mend API key from Windows Credential Manager"
    Import-Module CredentialManager -ErrorAction Stop
    $cred = Get-StoredCredential -Target $CredentialTarget -ErrorAction Stop
    if (-not $cred) {
        throw "Credential '$CredentialTarget' not found. Store it as a generic credential (password = Mend user key)."
    }
}
catch {
    Write-Error "Failed to retrieve Mend credential: $_"
    exit 1
}

$env:MEND_USER_KEY   = $cred.GetNetworkCredential().Password
$env:MEND_USER_EMAIL = $UserEmail
$env:MEND_ORG_UUID   = $OrgUuid
$env:MCP_TRANSPORT   = $Transport
$env:MCP_HOST        = $BindAddress
$env:MCP_PORT        = if ($Port) { "$Port" } else { $null }

Write-Verbose "$(Get-Date -Format o) Starting Mend MCP server (transport: $Transport)"
try {
    & $python (Join-Path $PSScriptRoot 'server.py')
    $exitCode = $LASTEXITCODE
}
finally {
    $env:MEND_USER_KEY = $null
}
exit $exitCode

# Authored by Caleb A. Morrow
