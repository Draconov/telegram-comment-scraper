# Telegram Research Scraper

A configurable Python scraper for collecting public Telegram channel posts and up to a chosen number of comments per post for academic and linguistic research.

The repository contains source code and safe examples only. Real credentials, Telegram login sessions, research source lists, databases, exports, logs, and QR artifacts are excluded from Git.

## Privacy defaults

- Raw sender IDs are not saved.
- Usernames are not saved.
- Sender IDs are pseudonymized with HMAC-SHA256 and a private local salt.
- Collected data is written to ignored local directories.
- The QR login is rendered directly in the terminal.

Pseudonymization is not the same as full anonymization. Message text can itself contain names, usernames, phone numbers, links, or other identifying information. Do not publish raw exports without a separate review and redaction process.

## Project structure

```text
.
├── .env.example
├── .gitignore
├── config.yaml
├── export_dataset.py
├── login_qr.py
├── requirements.txt
├── run_scraper.py
├── sources.example.csv
└── src/
    ├── db.py
    ├── export.py
    ├── login_qr.py
    ├── scraper.py
    ├── settings.py
    ├── sources.py
    └── utils.py
```

## Installation on Windows PowerShell

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
Copy-Item sources.example.csv sources.csv
```

When PowerShell blocks activation, run this once in the same window and activate again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\Activate.ps1
```

On macOS or Linux, activate with:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
cp sources.example.csv sources.csv
```

## Local credentials

Create Telegram API credentials for your own account and place them only in `.env`:

```dotenv
TELEGRAM_API_ID=your_numeric_api_id
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_SESSION_NAME=sessions/research_session
ANONYMIZATION_SALT=your_random_private_salt
```

Generate the anonymization salt locally:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

The `.env` file and session files are login secrets. Never send them to another person and never commit them.

## Source list

Edit the local `sources.csv`. The file is intentionally ignored by Git. Required channel information can be supplied through `telegram_username`, `channel_url`, or `channel`.

```csv
source_id,channel_title,channel_url,telegram_username,language,source_type,topic_label,toxicity_expected,notes,active
source_001,Public channel,https://t.me/channelname,@channelname,uk,news,general,unknown,Research source,true
```

## QR login

Run:

```powershell
python login_qr.py
```

Scan the terminal QR code in the Telegram mobile application under **Settings → Devices → Link Desktop Device**. The resulting session is stored locally under `sessions/` and is ignored by Git.

## Run the scraper

```powershell
python run_scraper.py
```

The default configuration collects up to 100 posts per active channel and up to 100 comments per post. Posts without an available linked discussion are skipped cleanly instead of stopping the entire scrape.

## Export the dataset

```powershell
python export_dataset.py
```

CSV files are written to `exports/`, which is ignored by Git because exports can contain personal data from Telegram messages.

## Never commit

- `.env`
- Telegram API credentials
- Telegram `.session` or `.session-journal` files
- `ANONYMIZATION_SALT`
- personal phone numbers, email addresses, or absolute user-directory paths
- `sources.csv` when it contains a private research plan
- SQLite databases, CSV exports, logs, screenshots, or QR images

## Responsible use

Collect only material that you are permitted to access and process. Follow applicable law, research-ethics requirements, platform rules, data-minimization principles, and your institution's approval process. Do not use this project to bypass access controls or collect private chats.
