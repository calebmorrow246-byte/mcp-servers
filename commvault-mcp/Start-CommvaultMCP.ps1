# Initial version by a colleague, built with the toolbox and reference material provided by Caleb A. Morrow, who reworked, extended, tested and deployed it
# Contributor: Caleb A. Morrow - 2026-09-24 - Host cvweb01 (the CommServe doesn't serve the API); run from repo .venv; added -Transport/-Port/-BindAddress for Streamable HTTP hosting; error handling and exit code passthrough

<#
.SYNOPSIS
    Starts the Commvault MCP server, loading credentials from Windows Credential Manager.

.DESCRIPTION
    Retrieves the Commvault read-only service account credentials from Windows Credential Manager
    (target: Commvault RO) and launches the Python MCP server against the Command Center API on
    cvweb01, using the repo's own virtual environment (.venv) so it works for any account,
    including svc-mcp.

    Credential type: service account, read-only (one shared account whose Commvault role has only
    the Global 'View' permission; every tool is a GET).

    Runs over stdio for a local client by default, or over Streamable HTTP when
    hosted as a Windows service on mcp-host.

    TLS: cvweb01 presents a self-signed certificate (CN=cvweb01), so certificate
    verification stays off until it gets a the company CA certificate. Traffic is still encrypted.

.PARAMETER Transport
    stdio (default) for a local client, or http to serve Streamable HTTP at /mcp.

.PARAMETER Port
    Listening port for -Transport http (3112 in the MCP port map).

.PARAMETER BindAddress
    Bind address for -Transport http. Keep the default loopback address and publish
    the server through the TLS front end.

.EXAMPLE
    .\Start-CommvaultMCP.ps1 -Transport http -Port 3112

.NOTES
    Store credentials (the name has a space, so not cmdkey; on mcp-host use
    Server\MCP-Hosting\Set-McpServiceCredentials.ps1 -Target 'Commvault RO').

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
    Write-Verbose "$(Get-Date -Format o) Retrieving Commvault credential from Windows Credential Manager"
    Import-Module CredentialManager -ErrorAction Stop
    $cred = Get-StoredCredential -Target 'Commvault RO' -ErrorAction Stop
    if (-not $cred) {
        throw "Credential 'Commvault RO' not found. Store it as a generic credential named 'Commvault RO'."
    }
}
catch {
    Write-Error "Failed to retrieve Commvault credential: $_"
    exit 1
}

# The Command Center API is served by the web server, not the CommServe (cv01 has no 443 listener)
$env:COMMVAULT_HOST       = 'cvweb01.example.com'
$env:COMMVAULT_USERNAME   = $cred.UserName
$env:COMMVAULT_PASSWORD   = $cred.GetNetworkCredential().Password
$env:COMMVAULT_API_PATH   = '/commandcenter/api'
# Self-signed certificate on cvweb01; turn on once it has a the company CA certificate
$env:COMMVAULT_VERIFY_SSL = 'false'
$env:COMMVAULT_TIMEOUT    = '30'

$env:MCP_TRANSPORT = $Transport
$env:MCP_HOST      = $BindAddress
$env:MCP_PORT      = if ($Port) { "$Port" } else { $null }

Write-Verbose "$(Get-Date -Format o) Starting Commvault MCP server (transport: $Transport)"
try {
    & $python (Join-Path $PSScriptRoot 'server.py')
    $exitCode = $LASTEXITCODE
}
finally {
    $env:COMMVAULT_PASSWORD = $null
}
exit $exitCode
# Initial version by a colleague, built with the toolbox and reference material provided by Caleb A. Morrow, who reworked, extended, tested and deployed it
# Contributor: Caleb A. Morrow - 2026-09-24 - Host cvweb01 (the CommServe doesn't serve the API); run from repo .venv; added -Transport/-Port/-BindAddress for Streamable HTTP hosting; error handling and exit code passthrough
