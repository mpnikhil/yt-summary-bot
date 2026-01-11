# YouTube Summarizer

Summarize YouTube videos from your phone. Share a link to your Telegram bot, get a summary back in the same chat.

```
Phone (share to Telegram bot) → Desktop (Claude CLI) → Telegram reply
```

## Requirements

- Mac or Linux machine that stays on
- [Claude CLI](https://docs.anthropic.com/en/docs/claude-cli)
- Telegram account

## Setup

### 1. Clone

```bash
git clone --recursive https://github.com/mpnikhil/yt-summarizer.git
cd yt-summarizer
```

### 2. Create your Telegram bot (30 seconds)

1. Open Telegram → message **@BotFather**
2. Send `/newbot`
3. Choose a name and username
4. Copy the token

### 3. Run setup

```bash
TELEGRAM_BOT_TOKEN="your-token-here" ./setup.sh
```

Done! Share a YouTube video to your bot.

## Commands

```bash
# View logs
tail -f /tmp/yt-summarizer.log                    # macOS
journalctl --user -u yt-summarizer -f             # Linux

# Stop service
launchctl unload ~/Library/LaunchAgents/com.user.yt-summarizer.plist   # macOS
systemctl --user stop yt-summarizer                                      # Linux

# Restart service
launchctl unload ~/Library/LaunchAgents/com.user.yt-summarizer.plist && launchctl load ~/Library/LaunchAgents/com.user.yt-summarizer.plist   # macOS
systemctl --user restart yt-summarizer                                   # Linux
```

## Files

| File | Purpose |
|------|---------|
| `yt-summarizer-telegram.py` | Main script |
| `claude-config.json` | MCP config |
| `youtube-mcp/` | YouTube MCP server (submodule) |
| `setup.sh` | Setup + service installation |
