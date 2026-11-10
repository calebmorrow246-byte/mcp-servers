# Authored by Caleb A. Morrow

<#
.SYNOPSIS
    Launches the Route53 MCP server with AWS credentials retrieved from
    Windows Credential Manager (no secret stored in the Claude config).

.DESCRIPTION
    Mirrors the the company credential standard used by the PRTG, Freshservice,
    and Brandsight MCP servers: the AWS access key/secret are pulled at
    runtime from Credential Manager, injected into the environment only for
    the child node process, and cleared afterward. Register this script (not
    node directly) as the MCP command so the key never sits in .mcp.json.

    This server is read-only by construction - it only implements Route53
    List*/Get* operations (see src/route53-client.ts), there is no
    create/update/delete tool to disable. Technicians perform actual DNS
    changes through normal channels, not through this MCP server.

    Runs over stdio for a local client by default, or over Streamable HTTP when
    hosted as a Windows service on mcp-host.

.PARAMETER Transport
    stdio (default) for a local client, or http to serve Streamable HTTP at /mcp.

.PARAMETER Port
    Listening port for -Transport http (3108 in the MCP port map).

.PARAMETER BindAddress
    Bind address for -Transport http. Keep the default loopback address and publish
    the server through the TLS front end.

.EXAMPLE
    .\Start-Route53MCP.ps1 -Transport http -Port 3108

.NOTES
    Store the key once using:
    cmdkey /generic:"AWS Route53 RO" /user:<AWS_ACCESS_KEY_ID> /pass:<AWS_SECRET_ACCESS_KEY>
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
    Write-Verbose "$(Get-Date -Format o) Retrieving AWS Route53 RO key from Windows Credential Manager"
    Import-Module CredentialManager -ErrorAction Stop
    $cred = Get-StoredCredential -Target 'AWS Route53 RO' -ErrorAction Stop
    if (-not $cred) {
        throw "Credential 'AWS Route53 RO' not found. Run: cmdkey /generic:`"AWS Route53 RO`" /user:<AWS_ACCESS_KEY_ID> /pass:<AWS_SECRET_ACCESS_KEY>"
    }
    $accessKeyId = $cred.UserName
    $secretAccessKey = [System.Net.NetworkCredential]::new('', $cred.Password).Password
}
catch {
    Write-Error "Failed to retrieve AWS Route53 RO key: $_"
    exit 1
}

$env:AWS_ACCESS_KEY_ID = $accessKeyId
$env:AWS_SECRET_ACCESS_KEY = $secretAccessKey
$env:AWS_REGION = 'us-east-1'

$env:MCP_TRANSPORT = $Transport
$env:MCP_HOST      = $BindAddress
$env:MCP_PORT      = if ($Port) { "$Port" } else { $null }

Write-Verbose "$(Get-Date -Format o) Starting Route53 MCP server (transport: $Transport)"
try {
    & 'C:\Program Files\nodejs\node.exe' (Join-Path $PSScriptRoot 'dist\index.js')
    $exitCode = $LASTEXITCODE
}
finally {
    $env:AWS_ACCESS_KEY_ID = $null
    $env:AWS_SECRET_ACCESS_KEY = $null
}
exit $exitCode
# Authored by Caleb A. Morrow
