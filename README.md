# YouTube Summarizer

Summarize YouTube videos from your phone. Share a link to your Telegram bot, get a summary back in the same chat.

```
Phone (share to Telegram bot) → Desktop (Claude CLI) → Telegram reply
```

## Requirements

- Mac or Linux machine that stays on
- [Claude CLI](https://docs.anthropic.com/en/docs/claude-cli) with YouTube MCP
- Telegram account

## Setup

### 1. Create your Telegram bot (30 seconds)

1. Open Telegram → message **@BotFather**
2. Send `/newbot`
3. Choose a name (e.g., "My YT Summarizer")
4. Choose a username (e.g., "myname_yt_bot")
5. Copy the token you receive

### 2. Install the script

```bash
mkdir -p ~/.local/bin
curl -o ~/.local/bin/yt-summarizer-telegram.py \
  https://raw.githubusercontent.com/YOURUSER/yt-summarizer/main/yt-summarizer-telegram.py
chmod +x ~/.local/bin/yt-summarizer-telegram.py

# Install dependency
pip install requests
```

### 3. Run it

```bash
export TELEGRAM_BOT_TOKEN="your-token-here"
~/.local/bin/yt-summarizer-telegram.py
```

### 4. Auto-start on boot (optional)

**macOS:**
```bash
# Edit plist first — add your bot token
cp com.user.yt-summarizer.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.user.yt-summarizer.plist
```

**Linux (systemd):**
```bash
# Edit service file first — add your bot token
mkdir -p ~/.config/systemd/user
cp yt-summarizer.service ~/.config/systemd/user/
systemctl --user enable yt-summarizer
systemctl --user start yt-summarizer
```

## Usage

1. Find a YouTube video on your phone
2. Share → Telegram → your bot
3. Get summary in the same chat

## Files

| File | Purpose |
|------|---------|
| `yt-summarizer-telegram.py` | Main script (Mac/Linux) |
| `com.user.yt-summarizer.plist` | Auto-start for macOS |
| `yt-summarizer.service` | Auto-start for Linux |
