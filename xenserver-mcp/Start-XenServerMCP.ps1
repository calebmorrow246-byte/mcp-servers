# Initial version by a colleague, built with the toolbox and reference material provided by Caleb A. Morrow, who reworked, extended, tested and deployed it
# Contributor: Caleb A. Morrow - 2026-09-23 - Credential target XenServer (svc.XenServerRO) with -PoolMaster defaulting to MO-JC; fixed $host (read-only automatic variable) assignment; run from repo .venv instead of a hardcoded path; added -Transport/-Port/-BindAddress for Streamable HTTP hosting; error handling and exit code passthrough

<#
.SYNOPSIS
    Starts the XenServer MCP server, loading credentials from Windows Credential Manager.

.DESCRIPTION
    Retrieves the read-only XenServer service account (target: XenServer, user
    svc.XenServerRO, shared by all three pools) from Windows Credential Manager and
    launches the Python MCP server against one pool master, using the repo's own
    virtual environment (.venv) so it works for any account, including svc-mcp.

    Runs over stdio for a local client by default, or over Streamable HTTP when
    hosted as a Windows service on mcp-host.

.PARAMETER PoolMaster
    Pool master to connect to. Defaults to MO-JC (192.0.2.142).
    Other pools: Dallas 192.0.2.38, Duluth 192.0.2.12.

.PARAMETER Transport
    stdio (default) for a local client, or http to serve Streamable HTTP at /mcp.

.PARAMETER Port
    Listening port for -Transport http (3110 in the MCP port map).

.PARAMETER BindAddress
    Bind address for -Transport http. Keep the default loopback address and publish
    the server through the TLS front end.

.EXAMPLE
    .\Start-XenServerMCP.ps1 -Transport http -Port 3110

.NOTES
    Store credentials with:
      cmdkey /generic:XenServer /user:svc.XenServerRO /pass:<password>

    Create the virtual environment once with:
      uv venv .venv; uv pip install --python .venv\Scripts\python.exe -r requirements.txt
#>
[CmdletBinding()]
param(
    [string]$PoolMaster = '192.0.2.142',

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
    Write-Verbose "$(Get-Date -Format o) Retrieving XenServer credential from Windows Credential Manager"
    Import-Module CredentialManager -ErrorAction Stop
    $cred = Get-StoredCredential -Target 'XenServer' -ErrorAction Stop
    if (-not $cred) {
        throw "Credential 'XenServer' not found. Run: cmdkey /generic:XenServer /user:svc.XenServerRO /pass:<password>"
    }
}
catch {
    Write-Error "Failed to retrieve XenServer credential: $_"
    exit 1
}

$env:XENSERVER_HOST       = $PoolMaster
$env:XENSERVER_USERNAME   = $cred.UserName
$env:XENSERVER_PASSWORD   = $cred.GetNetworkCredential().Password
$env:XENSERVER_VERIFY_SSL = 'false'
$env:XENSERVER_TIMEOUT    = '60'

$env:MCP_TRANSPORT = $Transport
$env:MCP_HOST      = $BindAddress
$env:MCP_PORT      = if ($Port) { "$Port" } else { $null }

Write-Verbose "$(Get-Date -Format o) Starting XenServer MCP server against $PoolMaster (transport: $Transport)"
try {
    & $python (Join-Path $PSScriptRoot 'server.py')
    $exitCode = $LASTEXITCODE
}
finally {
    $env:XENSERVER_PASSWORD = $null
}
exit $exitCode
# Initial version by a colleague, built with the toolbox and reference material provided by Caleb A. Morrow, who reworked, extended, tested and deployed it
# Contributor: Caleb A. Morrow - 2026-09-23 - Credential target XenServer (svc.XenServerRO) with -PoolMaster defaulting to MO-JC; fixed $host (read-only automatic variable) assignment; run from repo .venv instead of a hardcoded path; added -Transport/-Port/-BindAddress for Streamable HTTP hosting; error handling and exit code passthrough
