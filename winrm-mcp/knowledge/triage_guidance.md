# Event triage guidance

For events the knowledge base does not recognise (`status: unknown` or `partial` from `triage_events`).
Retuned for servers.

## What to write for each unknown group
- **suggestedFix** — one line. PowerShell preferred. If no action is right, write "No action needed"
  and say why in the root cause. Prefer read-only checks first. Never suggest re-enabling weak TLS
  ciphers or disabling security features to silence an event.
- **rootCauseAnalysis** — 20 words or fewer. Lead with the mechanism, end with the impact. No hedging
  filler; but if you are not sure, say "likely" and mark the whole assessment **unverified**.
- **priority** — exactly one of:
  - **H** = active outage, security event, or data-loss risk
  - **M** = recurring failure, performance regression, or a service that needs attention
  - **L** = benign noise, vendor chatter, transient startup/shutdown race, or a single-occurrence anomaly

## How to weigh it
- Weight by `count`: 100+ in 30 days is recurring and worth attention; a count of 1 with a benign
  message is almost always L.
- Tailor to the server's role (a crash on a domain controller or CA matters more than on a test box).
  Take the role from your CMDB or the your server inventory, not from guesswork.
- Look at `firstSeen` / `lastSeen`: something that started recently, or stopped, tells you more than
  a steady background rate. A fixed number of events per scan on scan days is scanner noise (see your maintenance runbook).
- If you cannot assess an event from its message, say "no known guidance — reviewer to assess".
  Do not invent a fix.

## Adding to the knowledge base
Assessments are not added automatically. After a human has reviewed them, add an entry to
`knowledge/known_events.json` (set `"reviewed": false` until then, include an `exampleMessage` that
the `messagePattern` matches), run `python tests/validate_kb.py`, and commit.
