# Initial version by a colleague, built with the toolbox and reference material provided by Caleb A. Morrow, who reworked, extended, tested and deployed it
# Contributor: Caleb A. Morrow - 2026-09-23 - Run from repo .venv; added -Transport/-Port/-BindAddress for Streamable HTTP hosting; exit code passthrough

<#
.SYNOPSIS
    Starts the NetApp ONTAP MCP server, loading credentials from Windows Credential Manager.

.DESCRIPTION
    Retrieves the NetApp read-only service account credentials from Windows Credential Manager
    (target: Netapp) and launches the Python MCP server connected to the ONTAP cluster, using the
    repo's own virtual environment (.venv) so it works for any account, including svc-mcp.

    Runs over stdio for a local client by default, or over Streamable HTTP when
    hosted as a Windows service on mcp-host.

.PARAMETER Transport
    stdio (default) for a local client, or http to serve Streamable HTTP at /mcp.

.PARAMETER Port
    Listening port for -Transport http (3104 in the MCP port map).

.PARAMETER BindAddress
    Bind address for -Transport http. Keep the default loopback address and publish
    the server through the TLS front end.

.EXAMPLE
    .\Start-NetAppMCP.ps1 -Transport http -Port 3104

.NOTES
    Store credentials with:
      cmdkey /generic:Netapp /user:<username> /pass:<password>

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
    Write-Verbose "$(Get-Date -Format o) Retrieving NetApp credential from Windows Credential Manager"
    Import-Module CredentialManager -ErrorAction Stop
    $cred = Get-StoredCredential -Target 'Netapp' -ErrorAction Stop
    if (-not $cred) {
        throw "Credential 'Netapp' not found. Run: cmdkey /generic:Netapp /user:<username> /pass:<password>"
    }
}
catch {
    Write-Error "Failed to retrieve NetApp credential: $_"
    exit 1
}

$env:ONTAP_HOST       = '192.0.2.150'
$env:ONTAP_USERNAME   = $cred.UserName
$env:ONTAP_PASSWORD   = $cred.GetNetworkCredential().Password
$env:ONTAP_VERIFY_SSL = 'false'
$env:ONTAP_TIMEOUT    = '30'

$env:MCP_TRANSPORT = $Transport
$env:MCP_HOST      = $BindAddress
$env:MCP_PORT      = if ($Port) { "$Port" } else { $null }

Write-Verbose "$(Get-Date -Format o) Starting NetApp MCP server (transport: $Transport)"
try {
    & $python (Join-Path $PSScriptRoot 'server.py')
    $exitCode = $LASTEXITCODE
}
finally {
    $env:ONTAP_PASSWORD = $null
}
exit $exitCode
# Initial version by a colleague, built with the toolbox and reference material provided by Caleb A. Morrow, who reworked, extended, tested and deployed it
# Contributor: Caleb A. Morrow - 2026-09-23 - Run from repo .venv; added -Transport/-Port/-BindAddress for Streamable HTTP hosting; exit code passthrough
