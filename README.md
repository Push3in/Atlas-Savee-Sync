# Savee → Atlas sync

Imports new Savee saves into the Atlas library and mirrors Savee boards onto the
collections in Atlas's **Savee** folder (saves on no board go to **Unsorted**).
Runs hourly via launchd, no Claude needed. Safe to run on several Macs that share
the same iCloud Atlas library; duplicate imports are moved to Atlas's Trash.

## Set up a Mac

1. Open Atlas on the shared iCloud library (Settings ▸ Developers ▸ MCP on).
2. `git clone <this repo> ~/.local/share/savee-atlas-sync`
3. `zsh ~/.local/share/savee-atlas-sync/install.sh` (opens Savee to log in the first time)

## Use

- Update: `git -C ~/.local/share/savee-atlas-sync pull` (launchd picks it up on the next run)
- Preview: `python3 -I savee_atlas_sync.py dry-run`
- Log: `tail ~/.local/share/savee-atlas-sync/logs/sync.log`
- Re-login to Savee: `python3 -I savee_atlas_sync.py login`

No secrets live in this repo: the Savee token is in the Keychain and the Atlas key is
copied by `install.sh` from the library's `.mcp-token` file into the Keychain
(rerun `install.sh` if you regenerate the key in Atlas).
