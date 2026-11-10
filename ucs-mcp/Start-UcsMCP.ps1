# Authored by Caleb A. Morrow

<#
.SYNOPSIS
    Starts the Cisco UCS Manager MCP server, loading credentials from Windows Credential Manager.

.DESCRIPTION
    Retrieves the UCS Manager read-only account (target: UCS RO, user ROUser) from Windows
    Credential Manager and launches the Python MCP server against ucs-manager.example.com, using
    the repo's own virtual environment (.venv) so it works for any account, including svc-mcp.

    Credential type: service account, read-only. The server is read-only by construction (it only
    implements login/logout and configResolve* reads) and the account has a read-only UCS role.

    Runs over stdio for a local client by default, or over Streamable HTTP when
    hosted as a Windows service on mcp-host.

.PARAMETER Transport
    stdio (default) for a local client, or http to serve Streamable HTTP at /mcp.

.PARAMETER Port
    Listening port for -Transport http (3114 in the MCP port map).

.PARAMETER BindAddress
    Bind address for -Transport http. Keep the default loopback address and publish
    the server through the TLS front end.

.EXAMPLE
    .\Start-UcsMCP.ps1 -Transport http -Port 3114

.NOTES
    Store the credential (the name has a space, so not cmdkey; on mcp-host use
    Server\MCP-Hosting\Set-McpServiceCredentials.ps1 -Target 'UCS RO').

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
    Write-Verbose "$(Get-Date -Format o) Retrieving UCS credential from Windows Credential Manager"
    Import-Module CredentialManager -ErrorAction Stop
    $cred = Get-StoredCredential -Target 'UCS RO' -ErrorAction Stop
    if (-not $cred) {
        throw "Credential 'UCS RO' not found. Store it as a generic credential named 'UCS RO'."
    }
}
catch {
    Write-Error "Failed to retrieve UCS credential: $_"
    exit 1
}

$env:UCS_HOST       = 'ucs-manager.example.com'
$env:UCS_USERNAME   = $cred.UserName
$env:UCS_PASSWORD   = $cred.GetNetworkCredential().Password
# ucs-manager presents a publicly trusted (GoDaddy) certificate, so verify it
$env:UCS_VERIFY_SSL = 'true'
$env:UCS_TIMEOUT    = '60'

$env:MCP_TRANSPORT = $Transport
$env:MCP_HOST      = $BindAddress
$env:MCP_PORT      = if ($Port) { "$Port" } else { $null }

Write-Verbose "$(Get-Date -Format o) Starting UCS Manager MCP server (transport: $Transport)"
try {
    & $python (Join-Path $PSScriptRoot 'server.py')
    $exitCode = $LASTEXITCODE
}
finally {
    $env:UCS_PASSWORD = $null
}
exit $exitCode
# Authored by Caleb A. Morrow
