import { spawn } from "node:child_process";

export interface PhpIPAMCredentials {
  username: string;
  password: string;
}

/**
 * Resolve phpIPAM API credentials.
 *
 * Order of precedence:
 *   1. Env vars PHPIPAM_USERNAME + PHPIPAM_PASSWORD (useful for CI / quick tests).
 *   2. Windows Credential Manager generic credential (the the company standard),
 *      retrieved via the CredentialManager PowerShell module's Get-StoredCredential.
 *
 * Store the credential once:
 *   cmdkey /generic:"IPAM RO" /user:<phpipam_user> /pass:<phpipam_password>
 *
 * Override the target name with PHPIPAM_CRED_TARGET (default "IPAM RO").
 */
export async function resolveCredentials(): Promise<PhpIPAMCredentials> {
  const envUser = process.env.PHPIPAM_USERNAME;
  const envPass = process.env.PHPIPAM_PASSWORD;
  if (envUser && envPass) {
    return { username: envUser, password: envPass };
  }

  const target = process.env.PHPIPAM_CRED_TARGET || "IPAM RO";
  return readFromCredentialManager(target);
}

function readFromCredentialManager(target: string): Promise<PhpIPAMCredentials> {
  const script = `
$ErrorActionPreference = 'Stop'
try {
  Import-Module CredentialManager -ErrorAction Stop
  $c = Get-StoredCredential -Target $env:PHPIPAM_CRED_TARGET
  if (-not $c) { [Console]::Error.WriteLine('CRED_NOT_FOUND'); exit 2 }
  [pscustomobject]@{
    username = $c.UserName
    password = $c.GetNetworkCredential().Password
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
      { env: { ...process.env, PHPIPAM_CRED_TARGET: target } }
    );

    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (d) => (stdout += d.toString()));
    child.stderr.on("data", (d) => (stderr += d.toString()));

    child.on("error", (err) => {
      reject(
        new Error(
          `Could not launch 'pwsh' to read the phpIPAM credential. Ensure PowerShell 7+ is installed and on PATH. Underlying error: ${err.message}`
        )
      );
    });

    child.on("close", (code) => {
      if (code === 2) {
        reject(
          new Error(
            `No stored credential found for target "${target}". Create it with: cmdkey /generic:"${target}" /user:<phpipam_user> /pass:<phpipam_password>`
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
        const parsed = JSON.parse(stdout.trim()) as PhpIPAMCredentials;
        if (!parsed.username || !parsed.password) {
          reject(new Error(`Credential "${target}" is missing a username or password.`));
          return;
        }
        resolve(parsed);
      } catch {
        reject(new Error(`Unexpected output while reading credential "${target}": ${stdout.trim()}`));
      }
    });
  });
}
