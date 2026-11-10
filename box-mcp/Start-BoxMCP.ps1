# Authored by Caleb A. Morrow

<#
.SYNOPSIS
    Starts the Box MCP server, loading the Box app credentials from Windows Credential Manager.

.DESCRIPTION
    Retrieves the Box Client Credentials Grant app credentials (target: Box CCG; user field = app
    client ID, password = app client secret) from Windows Credential Manager and launches the Python
    MCP server, using the repo's own virtual environment (.venv) so it works for any account,
    including svc-mcp.

    Credential type: service account. The app requests tokens for one Box user (box.admin), so the
    server sees what that user sees. Read-only by construction: the server issues only GET requests
    to allow-listed Box API paths and never calls Box AI.

    Runs over stdio for a local client by default, or over Streamable HTTP when hosted as a Windows
    service on mcp-host.

.PARAMETER Transport
    stdio (default) for a local client, or http to serve Streamable HTTP at /mcp.

.PARAMETER Port
    Listening port for -Transport http (3120 in the MCP port map).

.PARAMETER BindAddress
    Bind address for -Transport http. Keep the default loopback address and publish the server
    through the TLS front end.

.PARAMETER SubjectId
    Box user ID the token is issued for (box.admin's user ID). Not a secret. Required.

.PARAMETER SubjectType
    user (default) or enterprise. Use enterprise to act as the app's service account instead.

.EXAMPLE
    .\Start-BoxMCP.ps1 -Transport http -Port 3120 -SubjectId 12345678 -Verbose

.NOTES
    Store the credential on mcp-host with Server\MCP-Hosting\Set-McpServiceCredentials.ps1
    -Target 'Box CCG'. On a workstation cmdkey rejects spaces in target names, so store it as
    cmdkey /generic:BoxCCG /user:<client id> /pass:<client secret> and pass -CredentialTarget BoxCCG.

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

    # box.admin's Box user ID (not a secret). The NSSM service passes only -Transport and -Port, so set
    # the default here once the ID is known (same pattern as the Unixi tenant ID).
    [ValidatePattern('^(\d+)?$')]
    [string]$SubjectId = '20075269845',

    [ValidateSet('user', 'enterprise')]
    [string]$SubjectType = 'user',

    [string]$CredentialTarget = 'Box CCG'
)

$ErrorActionPreference = 'Stop'

if ($Transport -eq 'http' -and -not $Port) {
    Write-Error '-Port is required when -Transport is http'
    exit 1
}

if (-not $SubjectId) {
    Write-Error 'SubjectId is not set. Pass -SubjectId <box.admin user ID> or set the parameter default in this script.'
    exit 1
}

$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -Path $python)) {
    Write-Error "Python virtual environment not found at $python. Create it first (see .NOTES)."
    exit 1
}

try {
    Write-Verbose "$(Get-Date -Format o) Retrieving Box app credentials from Windows Credential Manager"
    Import-Module CredentialManager -ErrorAction Stop
    $cred = Get-StoredCredential -Target $CredentialTarget -ErrorAction Stop
    if (-not $cred) {
        throw "Credential '$CredentialTarget' not found. Store it as a generic credential (user = Box app client ID, password = client secret)."
    }
}
catch {
    Write-Error "Failed to retrieve Box credential: $_"
    exit 1
}

$env:BOX_CLIENT_ID     = $cred.UserName
$env:BOX_CLIENT_SECRET = $cred.GetNetworkCredential().Password
$env:BOX_SUBJECT_ID    = $SubjectId
$env:BOX_SUBJECT_TYPE  = $SubjectType
$env:BOX_TIMEOUT       = '60'

$env:MCP_TRANSPORT = $Transport
$env:MCP_HOST      = $BindAddress
$env:MCP_PORT      = if ($Port) { "$Port" } else { $null }

Write-Verbose "$(Get-Date -Format o) Starting Box MCP server (transport: $Transport, subject: $SubjectType $SubjectId)"
try {
    & $python (Join-Path $PSScriptRoot 'server.py')
    $exitCode = $LASTEXITCODE
}
finally {
    $env:BOX_CLIENT_SECRET = $null
}
exit $exitCode

# Authored by Caleb A. Morrow
