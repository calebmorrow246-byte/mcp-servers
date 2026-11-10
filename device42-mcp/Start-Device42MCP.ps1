# Initial version by a colleague, built with the toolbox and reference material provided by Caleb A. Morrow, who reworked, extended, tested and deployed it
# Contributor: Caleb A. Morrow - 2026-09-24 - Run from repo .venv; added -Transport/-Port/-BindAddress for Streamable HTTP hosting; TLS certificate verification on (d42 has a public cert); error handling and exit code passthrough

<#
.SYNOPSIS
    Starts the Device42 MCP server, loading credentials from Windows Credential Manager.

.DESCRIPTION
    Retrieves the Device42 read-only service account credentials from Windows Credential Manager
    (target: Device42 RO) and launches the Python MCP server, using the repo's own virtual
    environment (.venv) so it works for any account, including svc-mcp.

    Credential type: service account, read-only (one shared account; every tool is a GET).

    Runs over stdio for a local client by default, or over Streamable HTTP when
    hosted as a Windows service on mcp-host.

.PARAMETER Transport
    stdio (default) for a local client, or http to serve Streamable HTTP at /mcp.

.PARAMETER Port
    Listening port for -Transport http (3111 in the MCP port map).

.PARAMETER BindAddress
    Bind address for -Transport http. Keep the default loopback address and publish
    the server through the TLS front end.

.EXAMPLE
    .\Start-Device42MCP.ps1 -Transport http -Port 3111

.NOTES
    Store credentials with (the name has a space, so not cmdkey; on mcp-host use
    Server\MCP-Hosting\Set-McpServiceCredentials.ps1 -Target 'Device42 RO'):
      Control Panel -> Credential Manager -> Add a generic credential, address 'Device42 RO'

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
    Write-Verbose "$(Get-Date -Format o) Retrieving Device42 credential from Windows Credential Manager"
    Import-Module CredentialManager -ErrorAction Stop
    $cred = Get-StoredCredential -Target 'Device42 RO' -ErrorAction Stop
    if (-not $cred) {
        throw "Credential 'Device42 RO' not found. Store it as a generic credential named 'Device42 RO'."
    }
}
catch {
    Write-Error "Failed to retrieve Device42 credential: $_"
    exit 1
}

$env:D42_HOST       = 'd42.example.com'
$env:D42_USERNAME   = $cred.UserName
$env:D42_PASSWORD   = $cred.GetNetworkCredential().Password
# d42.example.com presents a publicly trusted certificate, so verify it (CLAUDE.md: no insecure TLS)
$env:D42_VERIFY_SSL = 'true'
$env:D42_TIMEOUT    = '30'

$env:MCP_TRANSPORT = $Transport
$env:MCP_HOST      = $BindAddress
$env:MCP_PORT      = if ($Port) { "$Port" } else { $null }

Write-Verbose "$(Get-Date -Format o) Starting Device42 MCP server (transport: $Transport)"
try {
    & $python (Join-Path $PSScriptRoot 'server.py')
    $exitCode = $LASTEXITCODE
}
finally {
    $env:D42_PASSWORD = $null
}
exit $exitCode
# Initial version by a colleague, built with the toolbox and reference material provided by Caleb A. Morrow, who reworked, extended, tested and deployed it
# Contributor: Caleb A. Morrow - 2026-09-24 - Run from repo .venv; added -Transport/-Port/-BindAddress for Streamable HTTP hosting; TLS certificate verification on (d42 has a public cert); error handling and exit code passthrough
