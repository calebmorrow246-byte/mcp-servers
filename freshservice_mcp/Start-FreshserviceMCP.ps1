# Authored by Caleb A. Morrow

<#
.SYNOPSIS
    Launches the Freshservice MCP server with the API key retrieved from Windows Credential Manager.

.DESCRIPTION
    Runs the server from the repo's own virtual environment (.venv, created with uv) so it
    works for any account, including the svc-mcp service account on mcp-host.

    Runs over stdio for a local client by default, or over Streamable HTTP when
    hosted as a Windows service on mcp-host.

.PARAMETER Transport
    stdio (default) for a local client, or http to serve Streamable HTTP at /mcp.

.PARAMETER Port
    Listening port for -Transport http (3102 in the MCP port map).

.PARAMETER BindAddress
    Bind address for -Transport http. Keep the default loopback address and publish
    the server through the TLS front end.

.EXAMPLE
    .\Start-FreshserviceMCP.ps1 -Transport http -Port 3102

.NOTES
    Store the API key once using:
    cmdkey /generic:FreshserviceAPI /user:apikey /pass:<your-api-key>

    Create the virtual environment once with:
    uv venv .venv; uv pip install --python .venv\Scripts\python.exe .
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

$serverExe = Join-Path $PSScriptRoot '.venv\Scripts\freshservice-mcp.exe'
if (-not (Test-Path -Path $serverExe)) {
    Write-Error "Server not installed at $serverExe. Create the virtual environment first (see .NOTES)."
    exit 1
}

try {
    Write-Verbose "$(Get-Date -Format o) Retrieving Freshservice API key from Windows Credential Manager"
    Import-Module CredentialManager -ErrorAction Stop
    $cred = Get-StoredCredential -Target 'FreshserviceAPI' -ErrorAction Stop
    if (-not $cred) {
        throw "Credential 'FreshserviceAPI' not found. Run: cmdkey /generic:FreshserviceAPI /user:apikey /pass:<your-api-key>"
    }
    $apiKey = [System.Net.NetworkCredential]::new('', $cred.Password).Password
}
catch {
    Write-Error "Failed to retrieve Freshservice API key: $_"
    exit 1
}

$env:FRESHSERVICE_APIKEY = $apiKey
$env:FRESHSERVICE_DOMAIN = 'example.freshservice.com'

$env:MCP_TRANSPORT = $Transport
$env:MCP_HOST      = $BindAddress
$env:MCP_PORT      = if ($Port) { "$Port" } else { $null }

Write-Verbose "$(Get-Date -Format o) Starting Freshservice MCP server (transport: $Transport)"
try {
    & $serverExe
    $exitCode = $LASTEXITCODE
}
finally {
    $env:FRESHSERVICE_APIKEY = $null
}
exit $exitCode
# Authored by Caleb A. Morrow
