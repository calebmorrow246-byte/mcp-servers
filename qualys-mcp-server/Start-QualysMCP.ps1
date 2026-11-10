# Authored by Caleb A. Morrow

<#
.SYNOPSIS
    Launches the Qualys MCP server with the API credential retrieved from
    Windows Credential Manager (no secret stored in the Claude config).

.DESCRIPTION
    Follows the the company credential standard used by the PRTG, Valimail, and
    Freshservice MCP servers: the read-only Qualys username/password is pulled at
    runtime from Credential Manager, injected into the environment only for the
    child node process, and cleared afterward. (The server can also read the
    credential itself via src/creds.ts; passing it in avoids spawning a second
    PowerShell process at startup.)

    Runs over stdio for a local client by default, or over Streamable HTTP when
    hosted as a Windows service on mcp-host.

.PARAMETER Transport
    stdio (default) for a local client, or http to serve Streamable HTTP at /mcp.

.PARAMETER Port
    Listening port for -Transport http (3107 in the MCP port map).

.PARAMETER BindAddress
    Bind address for -Transport http. Keep the default loopback address and publish
    the server through the TLS front end.

.EXAMPLE
    .\Start-QualysMCP.ps1 -Transport http -Port 3107

.NOTES
    Store the credential once:
    cmdkey /generic:"Qualys RO" /user:<qualys_user> /pass:<qualys_password>

    Override the target name with $env:QUALYS_CRED_TARGET.
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
    Write-Verbose "$(Get-Date -Format o) Retrieving Qualys credential from Windows Credential Manager"
    Import-Module CredentialManager -ErrorAction Stop
    $credTarget = if ($env:QUALYS_CRED_TARGET) { $env:QUALYS_CRED_TARGET } else { 'Qualys RO' }
    $cred = Get-StoredCredential -Target $credTarget -ErrorAction Stop
    if (-not $cred) {
        throw "Credential '$credTarget' not found. Run: cmdkey /generic:`"Qualys RO`" /user:<qualys_user> /pass:<qualys_password>"
    }
    $password = $cred.GetNetworkCredential().Password
}
catch {
    Write-Error "Failed to retrieve Qualys credential: $_"
    exit 1
}

# POD qg3
$env:QUALYS_BASE_URL = 'https://qualysapi.qg3.apps.qualys.com'
$env:QUALYS_USERNAME = $cred.UserName
$env:QUALYS_PASSWORD = $password

$env:MCP_TRANSPORT = $Transport
$env:MCP_HOST      = $BindAddress
$env:MCP_PORT      = if ($Port) { "$Port" } else { $null }

Write-Verbose "$(Get-Date -Format o) Starting Qualys MCP server (transport: $Transport)"
try {
    & 'C:\Program Files\nodejs\node.exe' (Join-Path $PSScriptRoot 'dist\index.js')
    $exitCode = $LASTEXITCODE
}
finally {
    $env:QUALYS_PASSWORD = $null
}
exit $exitCode
# Authored by Caleb A. Morrow
