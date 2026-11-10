# Authored by Caleb A. Morrow

<#
.SYNOPSIS
    Starts the WPEngine MCP server, loading the shared REST API credential from Windows Credential Manager.

.DESCRIPTION
    Retrieves the WPEngine Hosting Platform API credential (target: WPEngine API) from Windows
    Credential Manager and launches the Python MCP server, using the repo's own virtual environment
    (.venv) so it works for any account, including svc-mcp.

    Credential type: shared, account-level API user/password (one account-wide credential; WPEngine
    has no read-only role, so "read-only" is enforced by which tools server.py implements, not by
    the credential).

    Per-install SFTP credentials (target: 'WPEngine SFTP <install-name>') are NOT loaded here — they
    are fetched on demand by sftp_tools.py at call time, since the set of installs can grow
    independently of a server restart.

    Runs over stdio for a local client by default, or over Streamable HTTP when hosted as a Windows
    service on mcp-host.

.PARAMETER Transport
    stdio (default) for a local client, or http to serve Streamable HTTP at /mcp.

.PARAMETER Port
    Listening port for -Transport http (3116 in the MCP port map).

.PARAMETER BindAddress
    Bind address for -Transport http. Keep the default loopback address and publish
    the server through the TLS front end.

.EXAMPLE
    .\Start-WpEngineMCP.ps1 -Transport http -Port 3116

.NOTES
    Store the REST API credential with (the name has a space, so not cmdkey; on mcp-host use
    Server\MCP-Hosting\Set-McpServiceCredentials.ps1 -Target 'WPEngine API'):
      Control Panel -> Credential Manager -> Add a generic credential, address 'WPEngine API'

    Store each install's SFTP credential the same way, one target per install:
      Set-McpServiceCredentials.ps1 -Target 'WPEngine SFTP <install-name>'

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
    Write-Verbose "$(Get-Date -Format o) Retrieving WPEngine API credential from Windows Credential Manager"
    Import-Module CredentialManager -ErrorAction Stop
    $cred = Get-StoredCredential -Target 'WPEngine API' -ErrorAction Stop
    if (-not $cred) {
        throw "Credential 'WPEngine API' not found. Store it as a generic credential named 'WPEngine API'."
    }
}
catch {
    Write-Error "Failed to retrieve WPEngine API credential: $_"
    exit 1
}

$env:WPENGINE_API_USER     = $cred.UserName
$env:WPENGINE_API_PASSWORD = $cred.GetNetworkCredential().Password
$env:WPENGINE_TIMEOUT      = '30'

$env:MCP_TRANSPORT = $Transport
$env:MCP_HOST      = $BindAddress
$env:MCP_PORT      = if ($Port) { "$Port" } else { $null }

Write-Verbose "$(Get-Date -Format o) Starting WPEngine MCP server (transport: $Transport)"
try {
    & $python (Join-Path $PSScriptRoot 'server.py')
    $exitCode = $LASTEXITCODE
}
finally {
    $env:WPENGINE_API_PASSWORD = $null
}
exit $exitCode
# Authored by Caleb A. Morrow
