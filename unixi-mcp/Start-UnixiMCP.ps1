# Authored by Caleb A. Morrow

<#
.SYNOPSIS
    Starts the Unixi MCP proxy, loading the Unixi MCP API key from Windows Credential Manager.

.DESCRIPTION
    Retrieves the Unixi key (target: Unixi MCP API; password = key with purpose "MCP API") from
    Windows Credential Manager and launches the Python proxy using the repo's own virtual
    environment (.venv) so it works for any account, including svc-mcp.

    The proxy fronts Unixi's own beta MCP server (https://app.unixi.io/mcp) and exposes only the
    7 allow-listed read-only get_* tools. Callers authenticate to the proxy with per-user bearer tokens.

    Credential type: service account (one shared tenant-wide Unixi key; Unixi keys cannot be scoped).
    HTTP only: there is no stdio mode.

.PARAMETER Transport
    Accepted for compatibility with Install-McpServices.ps1; the proxy only serves Streamable HTTP.

.PARAMETER Port
    Listening port (3118 in the MCP port map).

.PARAMETER BindAddress
    Bind address. Keep the default loopback address and publish through the TLS front end.

.PARAMETER TenantId
    Unixi tenant GUID (an identifier, not a secret).

.EXAMPLE
    .\Start-UnixiMCP.ps1 -Port 3118 -Verbose

.NOTES
    Store the credential (the name has spaces, so not cmdkey; on mcp-host use
    Server\MCP-Hosting\Set-McpServiceCredentials.ps1 -Target 'Unixi MCP API').

    Create the virtual environment once with:
      uv venv .venv; uv pip install --link-mode=copy --python .venv\Scripts\python.exe -r requirements.txt
#>
[CmdletBinding()]
param(
    [ValidateSet('http')]
    [string]$Transport = 'http',

    [Parameter(Mandatory)]
    [ValidateRange(1, 65535)]
    [int]$Port,

    [string]$BindAddress = '127.0.0.1',

    [ValidatePattern('^[0-9a-fA-F-]{36}$')]
    [string]$TenantId = '00000000-0000-0000-0000-000000000000'
)

$ErrorActionPreference = 'Stop'

$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -Path $python)) {
    Write-Error "Python virtual environment not found at $python. Create it first (see .NOTES)."
    exit 1
}

try {
    Write-Verbose "$(Get-Date -Format o) Retrieving Unixi MCP API key from Windows Credential Manager"
    Import-Module CredentialManager -ErrorAction Stop
    $cred = Get-StoredCredential -Target 'Unixi MCP API' -ErrorAction Stop
    if (-not $cred) {
        throw "Credential 'Unixi MCP API' not found. Store it as a generic credential named 'Unixi MCP API' (password = key)."
    }
}
catch {
    Write-Error "Failed to retrieve Unixi credential: $_"
    exit 1
}

$env:UNIXI_API_KEY   = $cred.GetNetworkCredential().Password
$env:UNIXI_TENANT_ID = $TenantId
$env:UNIXI_TIMEOUT   = '60'

$env:MCP_TRANSPORT = 'http'
$env:MCP_HOST      = $BindAddress
$env:MCP_PORT      = "$Port"

Write-Verbose "$(Get-Date -Format o) Starting Unixi MCP proxy on ${BindAddress}:$Port"
try {
    & $python (Join-Path $PSScriptRoot 'server.py')
    $exitCode = $LASTEXITCODE
}
finally {
    $env:UNIXI_API_KEY = $null
}
exit $exitCode
# Authored by Caleb A. Morrow
