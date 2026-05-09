# maptap-scoreboard

Family scoreboard for [Maptap](https://maptap.gg), hosted on GitHub Pages.

## Setup

### 1. Grant Full Disk Access

The extractor reads `~/Library/Messages/chat.db`, which requires Full Disk Access:

**System Settings → Privacy & Security → Full Disk Access** → add your terminal app (Terminal.app or iTerm2).

### 2. Configure players

Edit `updates/extract_maptap.py` and update the `PLAYERS` dict with phone numbers (E.164 format) mapped to display names. Set `OWNER_PHONE` to your own number.

### 3. Run the extractor

```bash
python3 updates/extract_maptap.py
```

This scans all iMessage chats for Maptap score messages and writes `scores.json` to the repo root.

### 4. Deploy to GitHub Pages

Push the repo to GitHub, then go to **Settings → Pages** and set the source to **Deploy from a branch**, branch `main`, folder `/ (root)`.

The site will be live at `https://<username>.github.io/maptap-scoreboard/`.

## Daily auto-update

The included launchd plist runs the update script daily at 9 PM, which extracts new scores and pushes `scores.json` to GitHub.

### Install

```bash
cp ~/Library/LaunchAgents/com.maptap.update.plist ~/Library/LaunchAgents/  # if not already there
launchctl load ~/Library/LaunchAgents/com.maptap.update.plist
```

### Manage

```bash
# Run immediately
launchctl start com.maptap.update

# Stop the daily job
launchctl unload ~/Library/LaunchAgents/com.maptap.update.plist

# Reload after editing the plist
launchctl unload ~/Library/LaunchAgents/com.maptap.update.plist
launchctl load ~/Library/LaunchAgents/com.maptap.update.plist
```

### Change the schedule

Edit `~/Library/LaunchAgents/com.maptap.update.plist` and update the `StartCalendarInterval` values (24-hour time):

```xml
<key>Hour</key>
<integer>21</integer>
<key>Minute</key>
<integer>0</integer>
```

Logs are written to `update.log` in the repo root (gitignored). If the Mac is asleep at the scheduled time, macOS will run the job when it next wakes up.
