# Replace the public repository safely

These steps update the existing `Draconov/telegram-comment-scraper` clone while keeping local credentials and data out of Git.

## 1. Protect local-only files

Before replacing files, copy these somewhere outside the repository if they exist:

- `.env`
- `sources.csv`
- `sessions/`
- `data/`
- `exports/`

Do not add them to the cleaned package.

## 2. Copy the cleaned files

Copy the contents of this folder into your existing local repository folder. Keep the existing hidden `.git` directory. Do not copy local secrets back until after the Git commit is complete.

## 3. Refresh Git tracking

Run in PowerShell from the repository root:

```powershell
git rm -r --cached .
git add .
python scripts/privacy_check.py
git status
git diff --cached
```

`git rm --cached` refreshes the index and does not delete local files from disk.

## 4. Commit and push

Only after the privacy check and manual diff look clean:

```powershell
git commit -m "Clean repository and update Telegram scraper"
git push origin main
```

## 5. Restore local files

Restore `.env`, `sources.csv`, `sessions/`, `data/`, and `exports/` locally. Confirm they remain absent from `git status`.

## History note

The current public branch shows examples rather than real Telegram credentials, but this package cannot prove that all earlier commits are clean. Inspect history locally before the final push:

```powershell
git log --all -- .env
git log --all -- "*.session"
git log --all -- "*.session-journal"
git log --all -- "*.sqlite"
git log --all -- "*.db"
```

If any secret was committed, rotate or revoke it before rewriting history.
