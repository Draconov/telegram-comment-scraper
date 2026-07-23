# Telegram Comment Scraper for Research

A configurable Python tool for collecting posts and comments from public Telegram channels for academic, linguistic, and NLP research.

The scraper reads a local CSV list of channels, stores the collected material in SQLite, and exports research-ready CSV files. On the first run, it automatically displays a Telegram login QR code in the terminal. Later runs reuse the saved local session, so a separate login command is normally unnecessary.

## Features

- Collects posts from multiple public Telegram channels.
- Collects up to a configurable number of comments per post.
- Supports optional date and keyword filters.
- Stores posts, comments, source metadata, reactions, views, and forwarding counts.
- Skips unavailable channels and posts without linked discussion threads without stopping the full run.
- Handles Telegram `FloodWaitError` responses.
- Saves data to a local SQLite database.
- Exports individual tables and a joined comments dataset to CSV.
- Pseudonymizes sender IDs with HMAC-SHA256 by default.
- Does not save raw sender IDs or usernames by default.
- Keeps credentials, sessions, source lists, databases, and exports outside Git.

## How it works

```text
sources.csv
    ↓
run_scraper.py
    ↓
Check Telegram session
    ├── authorized → continue
    └── not authorized → show QR in terminal → save local session
    ↓
Collect posts and comments
    ↓
data/telegram_research.sqlite
    ↓
export_dataset.py
    ↓
exports/*.csv
```

## Requirements

- Python 3.10 or newer
- A Telegram account
- Telegram API credentials for your own account
- Access to the public channels listed in `sources.csv`

## Project structure

```text
.
├── .env.example              # Template for private local credentials
├── .gitignore                # Excludes secrets and collected data
├── config.yaml               # Scraping, privacy, and export settings
├── export_dataset.py         # Exports SQLite tables to CSV
├── requirements.txt          # Python dependencies
├── run_scraper.py            # Main scraper entry point
├── sources.example.csv       # Safe example source list
└── src/
    ├── __init__.py
    ├── db.py                 # SQLite schema and write operations
    ├── export.py             # CSV export logic
    ├── login_qr.py           # Automatic terminal QR authentication
    ├── scraper.py            # Telegram collection workflow
    ├── settings.py           # Environment and YAML configuration
    ├── sources.py            # Source CSV loading and validation
    └── utils.py              # Dates, delays, normalization, pseudonyms
```

## Installation

### Windows PowerShell

Clone or download the repository, open PowerShell in the project directory, and run:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
Copy-Item sources.example.csv sources.csv
```

When PowerShell blocks virtual-environment activation, run this once in the same window:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\Activate.ps1
```

### macOS or Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
cp sources.example.csv sources.csv
```

## Configuration

The project uses two local configuration files:

- `.env` contains private credentials and secrets.
- `config.yaml` contains non-secret scraper settings.

### 1. Configure `.env`

Open `.env` and fill in the following values:

```dotenv
TELEGRAM_API_ID=your_numeric_api_id
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_SESSION_NAME=sessions/research_session
ANONYMIZATION_SALT=your_private_random_salt
```

Generate a strong anonymization salt locally:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

Keep the same salt throughout one research project. Changing it causes the same Telegram sender to receive a different pseudonymous identifier in later scraping runs.

Never commit or share `.env`, the anonymization salt, or Telegram session files.

### 2. Configure `sources.csv`

Copy `sources.example.csv` to `sources.csv`, then replace the example row with the public channels required for the research.

```csv
source_id,channel_title,channel_url,telegram_username,language,source_type,topic_label,toxicity_expected,notes,active
source_001,Public channel,https://t.me/channelname,@channelname,uk,news,general,unknown,Research source,true
```

The scraper accepts a channel through `telegram_username`, `channel_url`, or `channel`. Rows with `active=false` are skipped. When `source_id` is empty, the normalized channel username is used automatically.

Recommended field meanings:

| Field | Purpose |
|---|---|
| `source_id` | Stable local identifier for the source |
| `channel_title` | Human-readable channel name |
| `channel_url` | Public Telegram link |
| `telegram_username` | Channel username, with or without `@` |
| `language` | Expected language code, such as `uk` |
| `source_type` | Source category, such as news, blog, or community |
| `topic_label` | Research topic or thematic label |
| `toxicity_expected` | Optional expectation recorded before collection |
| `notes` | Local research notes |
| `active` | Whether the row should be scraped |

The real `sources.csv` is ignored by Git because it may contain a private research plan.

### 3. Configure `config.yaml`

Default settings:

```yaml
input:
  sources_file: "sources.csv"

database:
  path: "data/telegram_research.sqlite"

scraping:
  posts_per_channel: 100
  comments_per_post: 100
  scrape_comments: true
  after_date: null
  before_date: null
  keyword_filter: null
  include_posts_without_text: false
  min_delay_seconds: 0.5
  max_delay_seconds: 1.5
  stop_on_flood_wait: false

privacy:
  hash_sender_ids: true
  save_sender_ids: false
  save_usernames: false

export:
  output_dir: "exports"
```

Important options:

| Option | Description |
|---|---|
| `posts_per_channel` | Maximum number of accepted posts per active channel |
| `comments_per_post` | Maximum number of comments collected for each post |
| `scrape_comments` | Enables or disables comment collection |
| `after_date` | Earliest accepted date in ISO format, for example `2026-01-01` |
| `before_date` | Latest accepted date in ISO format |
| `keyword_filter` | Optional Telegram text-search term; use `null` for no keyword filter |
| `include_posts_without_text` | Includes media-only posts when enabled |
| `min_delay_seconds` | Minimum random pause used by the scraper |
| `max_delay_seconds` | Maximum random pause used by the scraper |
| `stop_on_flood_wait` | Stops immediately on a Telegram flood wait when `true`; otherwise waits and continues |
| `hash_sender_ids` | Generates stable pseudonymous sender hashes |
| `save_sender_ids` | Stores raw Telegram sender IDs; disabled by default |
| `save_usernames` | Stores Telegram usernames; disabled by default |

## Run the scraper

Activate the virtual environment, then run:

```powershell
python run_scraper.py
```

### First run

When no authorized Telegram session exists, the program automatically:

1. Connects to Telegram.
2. Displays a QR code in the terminal.
3. Waits for the QR to be scanned in Telegram under **Settings → Devices → Link Desktop Device**.
4. Requests the Telegram two-step verification password when the account uses it.
5. Saves the authorized session locally under `sessions/`.
6. Starts scraping immediately.

The QR code refreshes automatically when it expires.

### Later runs

The scraper detects the saved session and starts without showing another QR code:

```text
Existing Telegram session found.
```

A new QR login is required after the session file is deleted, becomes invalid, or is terminated from Telegram.

### Optional standalone login

Authentication is built into `run_scraper.py`, so this is normally unnecessary. To create or refresh a session without scraping, run:

```powershell
python -m src.login_qr
```

## Database

Collected data is stored by default in:

```text
data/telegram_research.sqlite
```

The database contains three tables:

- `sources` — source metadata from `sources.csv`;
- `posts` — Telegram post text and metadata;
- `comments` — comment text, metadata, and privacy-controlled sender fields.

Existing rows use stable identifiers and are replaced when the same post or comment is collected again. This makes repeated test runs less likely to create duplicate records.

## Export the dataset

After scraping, run:

```powershell
python export_dataset.py
```

The script creates:

```text
exports/
├── 2026-07-23_18-42-15/
│   ├── sources.csv
│   ├── posts.csv
│   ├── comments.csv
│   └── comments_with_source_labels.csv
└── 2026-07-24_10-08-31/
    ├── sources.csv
    ├── posts.csv
    ├── comments.csv
    └── comments_with_source_labels.csv
```

The directory name records the **export time**. Individual database rows also contain a `scraped_at` value that records when each source, post, or comment was collected. Because the SQLite database is cumulative, every export is a snapshot of the database's current contents and may include records collected during earlier runs.

`comments_with_source_labels.csv` joins each comment with selected post and source metadata, making it the most convenient starting point for annotation and NLP preprocessing.

CSV files are written with UTF-8 BOM encoding so Ukrainian text opens more reliably in spreadsheet software.

## Privacy model

The safe defaults are:

```yaml
privacy:
  hash_sender_ids: true
  save_sender_ids: false
  save_usernames: false
```

With these settings, the scraper does not store raw sender IDs or usernames. Instead, it generates a stable HMAC-SHA256 pseudonym from the sender ID and the private `ANONYMIZATION_SALT`.

This supports user-level analysis without directly storing the original Telegram identifier. It is still **pseudonymization, not complete anonymization**. Message text may contain names, usernames, links, phone numbers, locations, or other identifying information. Raw exports therefore require a separate review and redaction process before publication or sharing.

## Files that must remain private

Never commit or publicly share:

```text
.env
sessions/
*.session
*.session-journal
sources.csv
data/
exports/
logs/
```

Before pushing changes, inspect what Git will upload:

```powershell
git status
git diff --cached
git ls-files
```

## Common problems

### `ModuleNotFoundError`

Confirm that the virtual environment is active and reinstall dependencies:

```powershell
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### `Missing environment variable TELEGRAM_API_ID`

Create `.env` from `.env.example` and fill in the required values. `TELEGRAM_API_ID` must contain digits only.

### `ANONYMIZATION_SALT is required`

Generate a salt and add it to `.env`, or disable `hash_sender_ids` in `config.yaml`. Disabling pseudonymization is generally not recommended for research data containing user activity.

### Source file not found

Create the local source list:

```powershell
Copy-Item sources.example.csv sources.csv
```

### Comments are not collected for a post

Some channel posts do not have comments enabled or do not have a valid linked discussion thread. The scraper reports this and continues with the next post.

### Telegram requests a wait

Telegram may return a flood-wait duration. With `stop_on_flood_wait: false`, the scraper waits for the requested time and then continues. Avoid removing all delays or running many concurrent collection jobs from the same account.

## Responsible use

Use this project only for material you are authorized to access and process. Follow applicable law, Telegram rules, research-ethics requirements, data-minimization principles, and your institution's approval process.

Do not use the scraper to bypass access controls, collect private chats, harass users, or publish identifiable personal data. Public accessibility does not automatically make unrestricted redistribution ethically appropriate.
