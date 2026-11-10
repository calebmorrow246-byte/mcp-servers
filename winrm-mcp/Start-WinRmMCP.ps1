# Authored by Caleb A. Morrow
# Contributor: Caleb A. Morrow - 2026-11-02 - Added optional DMZ credential profile

<#
.SYNOPSIS
    Starts the Windows read-only (WinRM/JEA) MCP server, loading credentials from Windows Credential Manager.

.DESCRIPTION
    Retrieves the domain service account that is allowed on the ReadOnly JEA endpoint (target:
    Windows RO, user CORP\svc-winrm-ro) from Windows Credential Manager and launches the
    Python MCP server using the repo's own virtual environment (.venv) so it works for any
    account, including svc-mcp.

    Credential type: service account, read-only. The account is NOT an administrator on any
    server; it can only connect to the constrained ReadOnly endpoint, which exposes nine
    Get-Ro* read-only functions. The server only connects to hosts listed in servers.json.

    Runs over stdio for a local client by default, or over Streamable HTTP when hosted as a
    Windows service on mcp-host.

.PARAMETER Transport
    stdio (default) for a local client, or http to serve Streamable HTTP at /mcp.

.PARAMETER Port
    Listening port for -Transport http (3117 in the MCP port map).

.PARAMETER BindAddress
    Bind address for -Transport http. Keep the default loopback address and publish
    the server through the TLS front end.

.PARAMETER CredentialTarget
    Credential Manager target holding the service account (default: Windows RO).

.EXAMPLE
    .\Start-WinRmMCP.ps1 -Transport http -Port 3117

.NOTES
    Store the credential (the name has a space, so not cmdkey; on mcp-host use
    Server\MCP-Hosting\Set-McpServiceCredentials.ps1 -Target 'Windows RO').

    Create the virtual environment once with:
      uv venv .venv; uv pip install --link-mode=copy --python .venv\Scripts\python.exe -r requirements.txt
#>
[CmdletBinding()]
param(
    [ValidateSet('stdio', 'http')]
    [string]$Transport = 'stdio',

    [ValidateRange(1, 65535)]
    [int]$Port,

    [string]$BindAddress = '127.0.0.1',

    [string]$CredentialTarget = 'Windows RO',

    [string]$DmzCredentialTarget = 'Windows RO DMZ'
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
    Write-Verbose "$(Get-Date -Format o) Retrieving '$CredentialTarget' from Windows Credential Manager"
    Import-Module CredentialManager -ErrorAction Stop
    $cred = Get-StoredCredential -Target $CredentialTarget -ErrorAction Stop
    if (-not $cred) {
        throw "Credential '$CredentialTarget' not found. Store it as a generic credential with that name."
    }
}
catch {
    Write-Error "Failed to retrieve WinRM credential: $_"
    exit 1
}

# The endpoint mapping uses the NetBIOS domain name, so qualify a bare account name
$userName = if ($cred.UserName -match '\\') { $cred.UserName } else { "CORP\$($cred.UserName)" }

$env:WINRM_USERNAME = $userName
$env:WINRM_PASSWORD = $cred.GetNetworkCredential().Password
$env:WINRM_TIMEOUT  = '120'

# Optional DMZ profile (dmz.example.com domain). Servers.json entries with "credential": "dmz" use it.
try {
    $dmzCred = Get-StoredCredential -Target $DmzCredentialTarget -ErrorAction Stop
    if ($dmzCred) {
        $dmzUser = if ($dmzCred.UserName -match '\\') { $dmzCred.UserName } else { "DMZDOMAIN\$($dmzCred.UserName)" }
        $env:WINRM_CRED_DMZ_USERNAME = $dmzUser
        $env:WINRM_CRED_DMZ_PASSWORD = $dmzCred.GetNetworkCredential().Password
    }
    else {
        Write-Warning "DMZ credential '$DmzCredentialTarget' not found; DMZ servers will be unavailable."
    }
}
catch {
    Write-Warning "DMZ credential '$DmzCredentialTarget' not loaded: $_"
}

$env:MCP_TRANSPORT = $Transport
$env:MCP_HOST      = $BindAddress
$env:MCP_PORT      = if ($Port) { "$Port" } else { $null }

Write-Verbose "$(Get-Date -Format o) Starting Windows read-only MCP server (transport: $Transport)"
try {
    & $python (Join-Path $PSScriptRoot 'server.py')
    $exitCode = $LASTEXITCODE
}
finally {
    $env:WINRM_PASSWORD = $null
    $env:WINRM_CRED_DMZ_PASSWORD = $null
}
exit $exitCode
# Authored by Caleb A. Morrow
# Contributor: Caleb A. Morrow - 2026-11-02 - Added optional DMZ credential profile
