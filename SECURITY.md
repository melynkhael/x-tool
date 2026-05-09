# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.2.x   | Yes       |
| < 0.2   | No        |

## Reporting a Vulnerability

If you discover a security issue in X-Tool, please report it responsibly:

1. **Do NOT open a public GitHub issue.**
2. Email the maintainers or use GitHub's private vulnerability reporting feature.
3. Include a description of the issue, steps to reproduce, and potential impact.

We will respond within 72 hours and work with you on a fix.

## Security Design

- **Cookies are stored locally** in `~/.xtool/cookies.json` with `chmod 600`.
- **No data is sent anywhere** except to X's official API endpoints (`x.com`, `twitter.com`).
- **No telemetry or analytics** of any kind.
- **No third-party services** are contacted.
- The Bearer token used is X's public web client token (not a secret).

## Best Practices for Users

- Keep your `~/.xtool/cookies.json` private. Never share it.
- Revoke your X session if you suspect your cookies were compromised.
- Run X-Tool on trusted devices only.
- Delete `~/.xtool/cookies.json` when you're done cleaning up.
