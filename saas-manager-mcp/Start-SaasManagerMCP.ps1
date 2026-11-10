# Authored by Caleb A. Morrow

<#
.SYNOPSIS
    Starts the 1Password SaaS Manager (formerly Trelica) MCP server, loading its API client
    credentials from Windows Credential Manager.

.DESCRIPTION
    Retrieves the SaaS Manager OAuth client (target: SaaS Manager API; user field = client ID,
    password = client secret) from Windows Credential Manager and launches the Python MCP server,
    using the repo's own virtual environment (.venv) so it works for any account, including svc-mcp.

    Credential type: service account (one shared API client). Read-only by construction: the server
    requests only read scopes and only issues GET requests.

    Runs over stdio for a local client by default, or over Streamable HTTP when
    hosted as a Windows service on mcp-host.

.PARAMETER Transport
    stdio (default) for a local client, or http to serve Streamable HTTP at /mcp.

.PARAMETER Port
    Listening port for -Transport http (3115 in the MCP port map).

.PARAMETER BindAddress
    Bind address for -Transport http. Keep the default loopback address and publish
    the server through the TLS front end.

.EXAMPLE
    .\Start-SaasManagerMCP.ps1 -Transport http -Port 3115

.NOTES
    Store the credential (the name has spaces, so not cmdkey; on mcp-host use
    Server\MCP-Hosting\Set-McpServiceCredentials.ps1 -Target 'SaaS Manager API').

    Create the virtual environment once with:
      uv venv .venv; uv pip install --python .venv\Scripts\python.exe -r requirements.txt
#>
[CmdletBinding()]
param(
    [ValidateSet('stdio', 'http')]
    [string]$Transport = 'stdio',

    [ValidateRange(1, 65535)]
    [int]$Port,

    [string]$BindAddress = '127.0.0.1'
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
    Write-Verbose "$(Get-Date -Format o) Retrieving SaaS Manager API client from Windows Credential Manager"
    Import-Module CredentialManager -ErrorAction Stop
    $cred = Get-StoredCredential -Target 'SaaS Manager API' -ErrorAction Stop
    if (-not $cred) {
        throw "Credential 'SaaS Manager API' not found. Store it as a generic credential named 'SaaS Manager API' (user = client ID, password = client secret)."
    }
}
catch {
    Write-Error "Failed to retrieve SaaS Manager credential: $_"
    exit 1
}

$env:SAAS_MANAGER_HOST          = 'trelica.app'
$env:SAAS_MANAGER_CLIENT_ID     = $cred.UserName
$env:SAAS_MANAGER_CLIENT_SECRET = $cred.GetNetworkCredential().Password
$env:SAAS_MANAGER_TIMEOUT       = '60'

$env:MCP_TRANSPORT = $Transport
$env:MCP_HOST      = $BindAddress
$env:MCP_PORT      = if ($Port) { "$Port" } else { $null }

Write-Verbose "$(Get-Date -Format o) Starting SaaS Manager MCP server (transport: $Transport)"
try {
    & $python (Join-Path $PSScriptRoot 'server.py')
    $exitCode = $LASTEXITCODE
}
finally {
    $env:SAAS_MANAGER_CLIENT_SECRET = $null
}
exit $exitCode
# Authored by Caleb A. Morrow
