import { spawn } from "node:child_process";

export interface ValimailApiCredentials {
  clientId: string;
  appId: string;
}

/**
 * Resolve Valimail API credentials (the client-id / app-id pair shown once when
 * an API key is created in Account Settings -> API Keys).
 *
 * Order of precedence:
 *   1. Env vars VALIMAIL_CLIENT_ID + VALIMAIL_APP_ID (useful for CI / quick tests).
 *   2. Windows Credential Manager generic credential (the the company standard),
 *      retrieved via the CredentialManager PowerShell module's Get-StoredCredential.
 *      Stored as username = client-id, password = app-id.
 *
 * Store the credential once:
 *   cmdkey /generic:"Valimail API" /user:<client-id> /pass:<app-id>
 *
 * Override the target name with VALIMAIL_CRED_TARGET (default "Valimail API").
 */
export async function resolveCredentials(): Promise<ValimailApiCredentials> {
  const envClientId = process.env.VALIMAIL_CLIENT_ID;
  const envAppId = process.env.VALIMAIL_APP_ID;
  if (envClientId && envAppId) {
    return { clientId: envClientId, appId: envAppId };
  }

  const target = process.env.VALIMAIL_CRED_TARGET || "Valimail API";
  return readFromCredentialManager(target);
}

function readFromCredentialManager(target: string): Promise<ValimailApiCredentials> {
  // Emit the credential as compact JSON so values with special characters
  // survive transport across stdout intact.
  const script = `
$ErrorActionPreference = 'Stop'
try {
  Import-Module CredentialManager -ErrorAction Stop
  $c = Get-StoredCredential -Target $env:VALIMAIL_CRED_TARGET
  if (-not $c) { [Console]::Error.WriteLine('CRED_NOT_FOUND'); exit 2 }
  [pscustomobject]@{
    clientId = $c.UserName
    appId = $c.GetNetworkCredential().Password
  } | ConvertTo-Json -Compress
} catch {
  [Console]::Error.WriteLine($_.Exception.Message)
  exit 1
}
`;

  return new Promise((resolve, reject) => {
    const child = spawn(
      "pwsh",
      ["-NoProfile", "-NonInteractive", "-Command", script],
      { env: { ...process.env, VALIMAIL_CRED_TARGET: target } }
    );

    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (d) => (stdout += d.toString()));
    child.stderr.on("data", (d) => (stderr += d.toString()));

    child.on("error", (err) => {
      reject(
        new Error(
          `Could not launch 'pwsh' to read the Valimail credential. Ensure PowerShell 7+ is installed and on PATH. Underlying error: ${err.message}`
        )
      );
    });

    child.on("close", (code) => {
      if (code === 2) {
        reject(
          new Error(
            `No stored credential found for target "${target}". Create it with: cmdkey /generic:${target} /user:<client-id> /pass:<app-id>`
          )
        );
        return;
      }
      if (code !== 0) {
        reject(
          new Error(
            `Failed to read credential "${target}" from Windows Credential Manager: ${stderr.trim() || `exit code ${code}`}`
          )
        );
        return;
      }
      try {
        const parsed = JSON.parse(stdout.trim()) as ValimailApiCredentials;
        if (!parsed.clientId || !parsed.appId) {
          reject(new Error(`Credential "${target}" is missing a client-id or app-id.`));
          return;
        }
        resolve(parsed);
      } catch {
        reject(new Error(`Unexpected output while reading credential "${target}": ${stdout.trim()}`));
      }
    });
  });
}
