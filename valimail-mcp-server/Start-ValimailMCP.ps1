# Authored by Caleb A. Morrow

<#
.SYNOPSIS
    Launches the Valimail MCP server with the API credential retrieved from
    Windows Credential Manager (no secret stored in the Claude config).

.DESCRIPTION
    Mirrors the the company credential standard used by the PRTG, Qualys, and
    Freshservice MCP servers: the client-id/app-id pair is pulled at runtime
    from Credential Manager, injected into the environment only for the child
    node process, and cleared afterward. Register this script (not node
    directly) as the MCP command so the credential never sits in ~/.claude.json.

    Runs over stdio for a local client by default, or over Streamable HTTP when
    hosted as a Windows service on mcp-host.

.PARAMETER Transport
    stdio (default) for a local client, or http to serve Streamable HTTP at /mcp.

.PARAMETER Port
    Listening port for -Transport http (3109 in the MCP port map).

.PARAMETER BindAddress
    Bind address for -Transport http. Keep the default loopback address and publish
    the server through the TLS front end.

.EXAMPLE
    .\Start-ValimailMCP.ps1 -Transport http -Port 3109

.NOTES
    Store the credential once using the client-id/app-id pair shown when the
    Valimail API key was created (Account Settings -> API Keys):
    cmdkey /generic:"Valimail API" /user:<client-id> /pass:<app-id>
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

# Valimail access is per user. Hosted (http), each caller sends their own client-id/app-id in the
# X-Valimail-Client-Id / X-Valimail-App-Id headers, so no shared credential is read here.
# Locally (stdio), use this user's own stored credential.
$env:VALIMAIL_BASE_URL     = 'https://api.valimail.com'
$env:VALIMAIL_ACCOUNT_SLUG = 'example-account'

if ($Transport -eq 'stdio') {
    try {
        Write-Verbose "$(Get-Date -Format o) Retrieving Valimail API credential from Windows Credential Manager"
        Import-Module CredentialManager -ErrorAction Stop
        $cred = Get-StoredCredential -Target 'Valimail API' -ErrorAction Stop
        if (-not $cred) {
            throw "Credential 'Valimail API' not found. Run: cmdkey /generic:`"Valimail API`" /user:<client-id> /pass:<app-id>"
        }
        $env:VALIMAIL_CLIENT_ID = $cred.UserName
        $env:VALIMAIL_APP_ID    = [System.Net.NetworkCredential]::new('', $cred.Password).Password
    }
    catch {
        Write-Error "Failed to retrieve Valimail API credential: $_"
        exit 1
    }
}

$env:MCP_TRANSPORT = $Transport
$env:MCP_HOST      = $BindAddress
$env:MCP_PORT      = if ($Port) { "$Port" } else { $null }

Write-Verbose "$(Get-Date -Format o) Starting Valimail MCP server (transport: $Transport)"
try {
    & 'C:\Program Files\nodejs\node.exe' (Join-Path $PSScriptRoot 'dist\index.js')
    $exitCode = $LASTEXITCODE
}
finally {
    $env:VALIMAIL_CLIENT_ID = $null
    $env:VALIMAIL_APP_ID = $null
}
exit $exitCode
# Authored by Caleb A. Morrow
