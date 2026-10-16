#!/bin/zsh
# Sets up the hourly Savee -> Atlas sync on this Mac, running from this folder.
# Run once per Mac:  zsh install.sh   (again after moving the folder)
set -e
DIR="${0:A:h}"
LABEL="com.yan.savee-atlas-sync"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

mkdir -p "$DIR/logs" "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string><string>-I</string>
    <string>$DIR/savee_atlas_sync.py</string><string>sync</string>
  </array>
  <key>StartInterval</key><integer>3600</integer>
  <key>RunAtLoad</key><true/>
  <key>ProcessType</key><string>Background</string>
  <key>LowPriorityIO</key><true/>
  <key>StandardOutPath</key><string>$DIR/logs/sync.log</string>
  <key>StandardErrorPath</key><string>$DIR/logs/sync.log</string>
</dict>
</plist>
PL

# Savee login lives in this Mac's Keychain; skip if already there.
security find-generic-password -s savee-atlas-sync -a oauth >/dev/null 2>&1 \
  || /usr/bin/python3 -I "$DIR/savee_atlas_sync.py" login

launchctl bootout gui/$(id -u) "$PLIST" 2>/dev/null || true
launchctl bootstrap gui/$(id -u) "$PLIST"
echo "Installed. Log: $DIR/logs/sync.log"
