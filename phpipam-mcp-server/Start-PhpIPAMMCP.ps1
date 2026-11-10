# Initial version by a colleague, built with the toolbox and reference material provided by Caleb A. Morrow, who reworked, extended, tested and deployed it
# Contributor: Caleb A. Morrow - 2026-09-14 - Switched credential target from a personal API credential to IPAM RO
# Contributor: Caleb A. Morrow - 2026-09-23 - Added -Transport/-Port/-BindAddress for Streamable HTTP hosting; exit code passthrough

<#
.SYNOPSIS
    Launches the phpIPAM MCP server with the API credential retrieved from
    Windows Credential Manager (no secret stored in the Claude config).

.DESCRIPTION
    Mirrors the the company credential standard used by the Qualys, Valimail, and
    Freshservice MCP servers: the phpIPAM app token is pulled at runtime from
    Credential Manager, injected into the environment only for the child node
    process, and cleared afterward.

    Runs over stdio for a local client by default, or over Streamable HTTP when
    hosted as a Windows service on mcp-host.

.PARAMETER Transport
    stdio (default) for a local client, or http to serve Streamable HTTP at /mcp.

.PARAMETER Port
    Listening port for -Transport http (3105 in the MCP port map).

.PARAMETER BindAddress
    Bind address for -Transport http. Keep the default loopback address and publish
    the server through the TLS front end.

.EXAMPLE
    .\Start-PhpIPAMMCP.ps1 -Transport http -Port 3105

.NOTES
    Store the credential once (the password is the phpIPAM app token from
    Administration -> API -> claude -> App Token):
      cmdkey /generic:"IPAM RO" /user:<phpipam_user> /pass:<app-token>

    Override the target name with $env:PHPIPAM_CRED_TARGET.
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

try {
    Write-Verbose "$(Get-Date -Format o) Retrieving phpIPAM credential from Windows Credential Manager"
    Import-Module CredentialManager -ErrorAction Stop
    $credTarget = if ($env:PHPIPAM_CRED_TARGET) { $env:PHPIPAM_CRED_TARGET } else { 'IPAM RO' }
    $cred = Get-StoredCredential -Target $credTarget -ErrorAction Stop
    if (-not $cred) {
        throw "Credential '$credTarget' not found. Run: cmdkey /generic:`"IPAM RO`" /user:<phpipam_user> /pass:<app-token>"
    }
    $password = $cred.GetNetworkCredential().Password
}
catch {
    Write-Error "Failed to retrieve phpIPAM credential: $_"
    exit 1
}

$env:PHPIPAM_BASE_URL  = 'https://ipam.example.com'
$env:PHPIPAM_APP_ID    = 'claude'
# The stored password IS the phpIPAM app token (Administration -> API -> claude -> App Token).
$env:PHPIPAM_APP_TOKEN = $password

$env:MCP_TRANSPORT = $Transport
$env:MCP_HOST      = $BindAddress
$env:MCP_PORT      = if ($Port) { "$Port" } else { $null }

Write-Verbose "$(Get-Date -Format o) Starting phpIPAM MCP server (transport: $Transport)"
try {
    & 'C:\Program Files\nodejs\node.exe' (Join-Path $PSScriptRoot 'dist\index.js')
    $exitCode = $LASTEXITCODE
}
finally {
    $env:PHPIPAM_APP_TOKEN = $null
}
exit $exitCode
# Initial version by a colleague, built with the toolbox and reference material provided by Caleb A. Morrow, who reworked, extended, tested and deployed it
# Contributor: Caleb A. Morrow - 2026-09-14 - Switched credential target from a personal API credential to IPAM RO
# Contributor: Caleb A. Morrow - 2026-09-23 - Added -Transport/-Port/-BindAddress for Streamable HTTP hosting; exit code passthrough
