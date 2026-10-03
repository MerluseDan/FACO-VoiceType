# Security policy

## Supported versions

Security fixes are applied to the latest released version.

| Version | Supported |
| --- | --- |
| 1.2.1 and later | Yes |
| Earlier | No |

## Reporting a vulnerability

Use the repository's **Security** tab and GitHub private vulnerability reporting when available. Do not publish credentials, recorded audio, private logs, device identifiers, exploit details, or other sensitive information in a public issue.

Include the affected version, Linux distribution, desktop session, reproduction steps, impact, and any proposed mitigation. You should receive an acknowledgement after the report is reviewed.

## Security-sensitive behavior

VoiceType needs access to Linux input devices and focused-window injection helpers. Review `install.sh` before use. Run it as the normal desktop user; it requests `sudo` only for explicit system integration operations.
