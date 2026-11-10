# Authored by Caleb A. Morrow

<#
.SYNOPSIS
    Starts the CommVault Metallic MCP server (read-only, tenant ExampleCompanyInc on mXXX.metallic.io).

.DESCRIPTION
    Launches the Python MCP server from the repo's own virtual environment (.venv), so it works for any
    account, including svc-mcp.

    Credential type: service account, read-only (Metallic user MetallicRO, user group RO Access, role RO =
    Global View, associated at the company level). Metallic signs in through SSO, so the server uses an API
    access token (two-hour lifetime) plus refresh token. Every renewal rotates the pair, so the Python
    server reads and writes the pair in the running account's Credential Manager itself
    ('Metallic Access Token' and 'Metallic Refresh Token'). This launcher only checks that both exist.

    The pair can be renewed for about 90 days after the token is created (see the get_token_status tool).
    After that, create a new token for MetallicRO in the Metallic console and store it again.

    Runs over stdio for a local client by default, or over Streamable HTTP when
    hosted as a Windows service on mcp-host.

.PARAMETER Transport
    stdio (default) for a local client, or http to serve Streamable HTTP at /mcp.

.PARAMETER Port
    Listening port for -Transport http (3113 in the MCP port map).

.PARAMETER BindAddress
    Bind address for -Transport http. Keep the default loopback address and publish
    the server through the TLS front end.

.EXAMPLE
    .\Start-MetallicMCP.ps1 -Transport http -Port 3113

.NOTES
    Store or replace the token pair on mcp-host with:
      Server\MCP-Hosting\Set-McpServiceCredentials.ps1 -Target 'Metallic Access Token','Metallic Refresh Token' -Force

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
    Write-Verbose "$(Get-Date -Format o) Checking for the Metallic token pair in Windows Credential Manager"
    Import-Module CredentialManager -ErrorAction Stop
    foreach ($target in 'Metallic Access Token', 'Metallic Refresh Token') {
        if (-not (Get-StoredCredential -Target $target -ErrorAction Stop)) {
            throw "Credential '$target' not found. Store the pair with Set-McpServiceCredentials.ps1 (see .NOTES)."
        }
    }
}
catch {
    Write-Error "Metallic credential check failed: $_"
    exit 1
}

$env:METALLIC_HOST    = 'mXXX.metallic.io'
$env:METALLIC_TIMEOUT = '60'

$env:MCP_TRANSPORT = $Transport
$env:MCP_HOST      = $BindAddress
$env:MCP_PORT      = if ($Port) { "$Port" } else { $null }

Write-Verbose "$(Get-Date -Format o) Starting Metallic MCP server (transport: $Transport)"
& $python (Join-Path $PSScriptRoot 'server.py')
exit $LASTEXITCODE
# Authored by Caleb A. Morrow
