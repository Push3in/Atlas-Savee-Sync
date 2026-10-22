# Notes for Claude

Private notes on what has happened with this sync (incidents, fixes tried, open problems) are in iCloud Drive, not in this public repo:

`~/Library/Mobile Documents/com~apple~CloudDocs/Savee-Sync Notes/NOTES.md`

Read it at the start of a session, and add to it (newest first) when something notable happens. Don't copy its contents into this repo.

## Syncing on request

There is no hourly launchd job any more: the user asks Claude to sync when they want Savee saves brought into Atlas. Then:

1. Ask the user to confirm Atlas is quit on every other Mac and iCloud has finished syncing.
2. Make sure Atlas is open on this Mac (ask the user to open it; don't launch it hidden), then quit and reopen it if it has been open a long time, so it loads the latest `library.json`.
3. Run `python3 -I savee_atlas_sync.py dry-run`, show what would change, then `python3 -I savee_atlas_sync.py sync`.
4. Report the `done: N/N imported` and `boards mirrored: …` lines.
