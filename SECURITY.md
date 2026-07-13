# Security and privacy

## Never commit

- `.env`
- Telegram API credentials
- Telegram `.session` or `.session-journal` files
- `ANONYMIZATION_SALT`
- personal phone numbers, email addresses, or absolute user-directory paths
- `sources.csv` when it contains a private research plan
- SQLite databases, CSV exports, logs, screenshots, or QR images

## If a secret was pushed

Deleting the current file is not enough because Git keeps earlier commits. Revoke or rotate the exposed credential first, terminate the affected Telegram session, and then clean Git history before pushing again.

## Dataset warning

Hashed sender identifiers reduce direct identifiability but do not remove personal information from message text. Treat collected messages as potentially sensitive research data.
