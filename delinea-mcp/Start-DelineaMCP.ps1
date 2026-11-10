# Initial version by a colleague, built with the toolbox and reference material provided by Caleb A. Morrow, who reworked, extended, tested and deployed it

<#
.SYNOPSIS
    Starts the Delinea MCP server, loading the Delinea Platform service user from Windows Credential Manager.

.DESCRIPTION
    Retrieves the Delinea Platform service user (target: DelineaPlatform; user field = service user
    username, password = its password) from Windows Credential Manager and launches the Python MCP
    server, using the repo's own virtual environment (.venv) so it works for any account, including svc-mcp.

    Credential type: service account (one shared read-only service user scoped to Discovery). Read-only
    by construction: the server issues only GET requests to /v1/discovery paths and redacts credential
    fields.

    Runs over stdio for a local client by default, or over Streamable HTTP when hosted as a Windows
    service on mcp-host.

.PARAMETER Transport
    stdio (default) for a local client, or http to serve Streamable HTTP at /mcp.

.PARAMETER Port
    Listening port for -Transport http (3119 in the MCP port map).

.PARAMETER BindAddress
    Bind address for -Transport http. Keep the default loopback address and publish the server
    through the TLS front end.

.PARAMETER TenantHost
    Delinea Platform hostname.

.EXAMPLE
    .\Start-DelineaMCP.ps1 -Transport http -Port 3119 -Verbose

.NOTES
    Store the credential on mcp-host with Server\MCP-Hosting\Set-McpServiceCredentials.ps1
    -Target 'DelineaPlatform'. On a workstation: cmdkey /generic:DelineaPlatform /user:<username> /pass:<password>

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

    [string]$TenantHost = 'example.delinea.app'
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
    Write-Verbose "$(Get-Date -Format o) Retrieving Delinea service user from Windows Credential Manager"
    Import-Module CredentialManager -ErrorAction Stop
    $cred = Get-StoredCredential -Target 'DelineaPlatform' -ErrorAction Stop
    if (-not $cred) {
        throw "Credential 'DelineaPlatform' not found. Store it as a generic credential named 'DelineaPlatform' (user = service username, password = its password)."
    }
}
catch {
    Write-Error "Failed to retrieve Delinea credential: $_"
    exit 1
}

$env:DELINEA_TENANT_HOST   = $TenantHost
$env:DELINEA_CLIENT_ID     = $cred.UserName
$env:DELINEA_CLIENT_SECRET = $cred.GetNetworkCredential().Password
$env:DELINEA_TIMEOUT       = '60'

$env:MCP_TRANSPORT = $Transport
$env:MCP_HOST      = $BindAddress
$env:MCP_PORT      = if ($Port) { "$Port" } else { $null }

Write-Verbose "$(Get-Date -Format o) Starting Delinea MCP server (transport: $Transport)"
try {
    & $python (Join-Path $PSScriptRoot 'server.py')
    $exitCode = $LASTEXITCODE
}
finally {
    $env:DELINEA_CLIENT_SECRET = $null
}
exit $exitCode

# Initial version by a colleague, built with the toolbox and reference material provided by Caleb A. Morrow, who reworked, extended, tested and deployed it
