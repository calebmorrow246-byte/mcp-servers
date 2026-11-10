# Authored by Caleb A. Morrow

<#
.SYNOPSIS
    Launches the BrandSight MCP server with API credentials retrieved from
    Windows Credential Manager (no secret stored in the Claude config).

.DESCRIPTION
    Mirrors the the company credential standard used by the Valimail, PRTG,
    Qualys, and Freshservice MCP servers: the API key/secret pair is pulled
    at runtime from Credential Manager, injected into the environment only
    for the child node process, and cleared afterward. Register this script
    (not node directly) as the MCP command so credentials never sit in
    ~/.claude.json.

    Runs over stdio for a local client by default, or over Streamable HTTP when
    hosted as a Windows service on mcp-host.

.PARAMETER CustomerId
    BrandSight customer/shopper ID (not a secret). Defaults to the company's ID or
    $env:BRANDSIGHT_CUSTOMER_ID.

.PARAMETER Environment
    BrandSight API environment: production (default) or ote.

.PARAMETER Transport
    stdio (default) for a local client, or http to serve Streamable HTTP at /mcp.

.PARAMETER Port
    Listening port for -Transport http (3103 in the MCP port map).

.PARAMETER BindAddress
    Bind address for -Transport http. Keep the default loopback address and publish
    the server through the TLS front end.

.EXAMPLE
    .\Start-BrandsightMCP.ps1 -Transport http -Port 3103

.NOTES
    Store the credential once using the BrandSight API key/secret pair:
    cmdkey /generic:"Brandsight API" /user:<api-key> /pass:<api-secret>
#>
[CmdletBinding()]
param(
    [string]$CustomerId = $(if ($env:BRANDSIGHT_CUSTOMER_ID) { $env:BRANDSIGHT_CUSTOMER_ID } else { '00000000-0000-0000-0000-000000000000' }),

    [ValidateSet('production', 'ote')]
    [string]$Environment = 'production',

    [ValidateSet('stdio', 'http')]
    [string]$Transport = 'stdio',

    [ValidateRange(1, 65535)]
    [int]$Port,

    [string]$BindAddress = '127.0.0.1'
)

$ErrorActionPreference = 'Stop'

if (-not $CustomerId) {
    Write-Error "BrandSight customer ID not set. Pass -CustomerId or set `$env:BRANDSIGHT_CUSTOMER_ID."
    exit 1
}
if ($Transport -eq 'http' -and -not $Port) {
    Write-Error '-Port is required when -Transport is http'
    exit 1
}

try {
    Write-Verbose "$(Get-Date -Format o) Retrieving BrandSight API credential from Windows Credential Manager"
    Import-Module CredentialManager -ErrorAction Stop
    $cred = Get-StoredCredential -Target 'Brandsight API' -ErrorAction Stop
    if (-not $cred) {
        throw "Credential 'Brandsight API' not found. Run: cmdkey /generic:`"Brandsight API`" /user:<api-key> /pass:<api-secret>"
    }
    $apiSecret = [System.Net.NetworkCredential]::new('', $cred.Password).Password
}
catch {
    Write-Error "Failed to retrieve BrandSight API credential: $_"
    exit 1
}

$env:BRANDSIGHT_API_KEY     = $cred.UserName
$env:BRANDSIGHT_API_SECRET  = $apiSecret
$env:BRANDSIGHT_CUSTOMER_ID = $CustomerId
$env:BRANDSIGHT_ENVIRONMENT = $Environment

$env:MCP_TRANSPORT = $Transport
$env:MCP_HOST      = $BindAddress
$env:MCP_PORT      = if ($Port) { "$Port" } else { $null }

Write-Verbose "$(Get-Date -Format o) Starting BrandSight MCP server (transport: $Transport)"
try {
    & 'C:\Program Files\nodejs\node.exe' (Join-Path $PSScriptRoot 'dist\index.js')
    $exitCode = $LASTEXITCODE
}
finally {
    $env:BRANDSIGHT_API_KEY = $null
    $env:BRANDSIGHT_API_SECRET = $null
}
exit $exitCode
# Authored by Caleb A. Morrow
