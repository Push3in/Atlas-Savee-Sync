# Atlas Savee Sync

Keeps an Atlas library in step with a [Savee](https://savee.com) account. Every hour it brings in
your new Savee saves and files each one into the Atlas collection that matches its Savee board.
Re-board something in Savee and it moves in Atlas on the next run.

It's a single Python script run by macOS `launchd`. It talks to Savee's MCP server and to
Atlas's local MCP server directly — no Claude, no extra dependencies, nothing to keep open.

```
Savee (online) ──► savee_atlas_sync.py (hourly, on one Mac) ──► Atlas library (iCloud) ──► every Mac
```

## What a run does

1. **Imports new saves.** Pages through your newest Savee saves and downloads any that aren't in
   Atlas yet. Each item gets the `savee` tag, the save's title plus its savee.com link as the
   annotation, and the original source URL.
2. **Mirrors boards.** Puts every `savee`-tagged item into exactly the collections that match the
   boards it's on in Savee:
   - Each Savee board maps to a collection with the same name inside Atlas's **Savee** collection
     folder. If that name is already used by a collection outside the folder, it's
     `<name> (Savee)` instead (e.g. `Branding (Savee)`).
   - A save on several boards lands in several collections (no copies — Atlas items can live in
     more than one collection).
   - A save on no board goes to **Unsorted**.
   - A new Savee board gets a new collection in the Savee folder automatically.
3. **Cleans up duplicates.** If the same save was imported twice (see [Several Macs](#several-macs)),
   the newer copy is moved to Atlas's Trash.

It only ever touches `savee`-tagged items and collections inside the Savee folder. Nothing is
deleted from Savee, and nothing in Atlas is permanently deleted.

## Requirements

- macOS with `/usr/bin/python3` (installs with the Command Line Tools if missing)
- Atlas, with the library stored in iCloud Drive and **Settings ▸ Developers ▸ MCP** turned on
- A collection folder named **Savee** in Atlas's sidebar
- A Savee account

## Set up a Mac

```sh
git clone https://github.com/Push3in/Atlas-Savee-Sync.git ~/.local/share/savee-atlas-sync
zsh ~/.local/share/savee-atlas-sync/install.sh
```

`install.sh`:

1. copies Atlas's access key from the library's `.mcp-token` into this Mac's Keychain
   (background jobs aren't allowed to read the library's files),
2. opens Savee in your browser the first time so you can approve read access to your saves and
   boards (the token is stored in the Keychain),
3. writes `~/Library/LaunchAgents/com.yan.savee-atlas-sync.plist` pointing at this folder and
   starts it. It runs at login and then on the hour; if the Mac was asleep, the missed run happens
   when it wakes.

Run it again any time — after moving the folder, or after regenerating the key in Atlas.

## Commands

Run from the repo folder:

| Command | What it does |
|---|---|
| `python3 -I savee_atlas_sync.py sync` | Run a sync now (what launchd runs) |
| `python3 -I savee_atlas_sync.py dry-run` | Show what would be imported or moved, change nothing |
| `python3 -I savee_atlas_sync.py login` | Log in to Savee again |
| `python3 -I savee_atlas_sync.py atlas-key` | Re-copy the Atlas key into the Keychain |
| `tail logs/sync.log` | See recent runs |
| `git pull` | Update; launchd uses the new version on its next run |

A healthy run in the log ends with `done: N/N imported` and `boards mirrored: …`.

## Several Macs

Install it on **one Mac only**, ideally the one that's awake most. The library lives in iCloud, so
every other Mac still gets the imported saves and board changes; they just don't run the sync.
Saves are filed whenever that one Mac is awake, and runs missed while it sleeps happen on wake.

Running it on more than one Mac loses data. Atlas keeps the whole library (items, tags,
collections) in a single `library.json`, and iCloud syncs whole files: when two Macs each save
their own version, the one uploaded last replaces the other, and everything the other Mac added
since its last sync is gone. Hourly runs on two Macs make that likely, and both run on the hour.

The same applies to using Atlas itself: quit it on one Mac before working in it on another, and
let iCloud finish syncing first. Atlas keeps a copy of `library.json` in the library's `backups`
folder before changes, which is how lost items can be found and merged back.

If the same save does get imported twice, the next run keeps the older item and moves the newer
one to Trash.

## Troubleshooting

| Log says | Fix |
|---|---|
| `Not logged in to Savee` / `token refresh failed` | `python3 -I savee_atlas_sync.py login` |
| `Atlas key not in Keychain` | `zsh install.sh` |
| `Atlas MCP unreachable` | Open Atlas and check Settings ▸ Developers ▸ MCP is on |
| HTTP 401 from Atlas | The key was regenerated in Atlas — `zsh install.sh` |
| `FAILED mirroring boards: … boards:read` | Log in again and approve board access |
| `no "Savee" collection folder` | Create a collection folder named Savee in Atlas |

To stop syncing on a Mac:

```sh
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.yan.savee-atlas-sync.plist
rm ~/Library/LaunchAgents/com.yan.savee-atlas-sync.plist
```

## Security

No secrets are stored in this repo. The Savee OAuth token (read-only: `saves:read boards:read`)
and the Atlas key live in each Mac's Keychain under `savee-atlas-sync`. Logs stay local and are
git-ignored.

## Files

| File | Purpose |
|---|---|
| `savee_atlas_sync.py` | The sync: Savee OAuth, MCP clients, import, board mirroring, de-duplication |
| `install.sh` | Per-Mac setup: Keychain, Savee login, launchd job |
| `logs/` | Run log (created on first run, not committed) |
