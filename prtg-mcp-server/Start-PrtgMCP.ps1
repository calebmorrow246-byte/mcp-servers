# Authored by Caleb A. Morrow

<#
.SYNOPSIS
    Launches the PRTG MCP server with the API token retrieved from Windows
    Credential Manager (no secret stored in the Claude config).

.DESCRIPTION
    Mirrors the the company credential standard used by the Qualys and Freshservice
    MCP servers: the API token is pulled at runtime from Credential Manager,
    injected into the environment only for the child node process, and cleared
    afterward. Register this script (not node directly) as the MCP command so the
    token never sits in ~/.claude.json.

    Runs over stdio for a local client by default, or over Streamable HTTP when
    hosted as a Windows service on mcp-host.

.PARAMETER Transport
    stdio (default) for a local client, or http to serve Streamable HTTP at /mcp.

.PARAMETER Port
    Listening port for -Transport http (3106 in the MCP port map).

.PARAMETER BindAddress
    Bind address for -Transport http. Keep the default loopback address and publish
    the server through the TLS front end.

.EXAMPLE
    .\Start-PrtgMCP.ps1 -Transport http -Port 3106

.NOTES
    Store the token once using:
    cmdkey /generic:"PRTG API" /user:apitoken /pass:<your-api-token>
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

# PRTG access is per user. Hosted (http), each caller sends their own token in the X-PRTG-Api-Token
# header, so no shared token is read here. Locally (stdio), use this user's own stored token.
$apiToken = $null
if ($Transport -eq 'stdio') {
    try {
        Write-Verbose "$(Get-Date -Format o) Retrieving PRTG API token from Windows Credential Manager"
        Import-Module CredentialManager -ErrorAction Stop
        $cred = Get-StoredCredential -Target 'PRTG API' -ErrorAction Stop
        if (-not $cred) {
            throw "Credential 'PRTG API' not found. Run: cmdkey /generic:`"PRTG API`" /user:apitoken /pass:<your-api-token>"
        }
        $apiToken = [System.Net.NetworkCredential]::new('', $cred.Password).Password
    }
    catch {
        Write-Error "Failed to retrieve PRTG API token: $_"
        exit 1
    }
}

$env:PRTG_BASE_URL  = 'https://monitor.example.com'
$env:PRTG_API_TOKEN = $apiToken
$env:PRTG_INSECURE  = 'true'

$env:MCP_TRANSPORT = $Transport
$env:MCP_HOST      = $BindAddress
$env:MCP_PORT      = if ($Port) { "$Port" } else { $null }

Write-Verbose "$(Get-Date -Format o) Starting PRTG MCP server (transport: $Transport)"
try {
    & 'C:\Program Files\nodejs\node.exe' (Join-Path $PSScriptRoot 'dist\index.js')
    $exitCode = $LASTEXITCODE
}
finally {
    $env:PRTG_API_TOKEN = $null
}
exit $exitCode
# Authored by Caleb A. Morrow
