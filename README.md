# Telegram Research Scraper

A configurable Telegram scraper for collecting posts and comments from channels listed in a sources table.

The scraper is designed for academic / linguistic research. It stores:

- Telegram channel posts
- post metadata
- comments under each post
- source labels from the sources table
- hashed sender IDs for privacy

## Features

- Reads channels from `sources.example.csv` or your own `sources.csv`
- Variable number of posts per channel
- Variable number of comments per post
- Saves data into SQLite
- Exports posts and comments to CSV
- Keeps comments linked to their original posts
- Does not download media by default
- Hashes sender IDs by default

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt