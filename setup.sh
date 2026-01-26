#!/bin/bash
# setup.sh — One-time setup for yt-summarizer

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Require bot token
if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
    echo "❌ TELEGRAM_BOT_TOKEN not set"
    echo ""
    echo "1. Create a bot: message @BotFather on Telegram, send /newbot"
    echo "2. Run: TELEGRAM_BOT_TOKEN=\"your-token\" ./setup.sh"
    exit 1
fi

echo "🔧 Setting up yt-summarizer..."

# Check for uv
if ! command -v uv &> /dev/null; then
    echo "📦 Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

# Initialize submodule if needed
if [ ! -f "youtube-mcp/server.py" ]; then
    echo "📦 Initializing youtube-mcp submodule..."
    git submodule update --init --recursive
fi

# Create venv and install dependencies
echo "📦 Creating virtual environment..."
uv venv .venv

echo "📦 Installing dependencies..."
uv pip install --python .venv/bin/python requests
uv pip install --python .venv/bin/python -r youtube-mcp/requirements.txt

# Check for Claude CLI
if ! command -v claude &> /dev/null; then
    echo ""
    echo "⚠️  Claude CLI not found. Install from: https://docs.anthropic.com/en/docs/claude-cli"
    echo "   Then re-run this script."
    exit 1
fi

# Install service based on OS
if [[ "$OSTYPE" == "darwin"* ]]; then
    echo "🍎 Installing macOS service..."
    
    cat > ~/Library/LaunchAgents/com.user.yt-summarizer.plist << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.user.yt-summarizer</string>
    <key>ProgramArguments</key>
    <array>
        <string>${SCRIPT_DIR}/.venv/bin/python</string>
        <string>${SCRIPT_DIR}/yt-summarizer-telegram.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${SCRIPT_DIR}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/yt-summarizer.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/yt-summarizer.err</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
        <key>TELEGRAM_BOT_TOKEN</key>
        <string>${TELEGRAM_BOT_TOKEN}</string>
    </dict>
</dict>
</plist>
EOF

    launchctl unload ~/Library/LaunchAgents/com.user.yt-summarizer.plist 2>/dev/null || true
    launchctl load ~/Library/LaunchAgents/com.user.yt-summarizer.plist
    
    echo "✅ Service installed and started!"
    echo "   Logs: tail -f /tmp/yt-summarizer.log"
    echo "   Stop: launchctl unload ~/Library/LaunchAgents/com.user.yt-summarizer.plist"

elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    echo "🐧 Installing Linux service..."
    
    mkdir -p ~/.config/systemd/user
    
    cat > ~/.config/systemd/user/yt-summarizer.service << EOF
[Unit]
Description=YouTube Summarizer Telegram Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=${SCRIPT_DIR}
ExecStart=${SCRIPT_DIR}/.venv/bin/python ${SCRIPT_DIR}/yt-summarizer-telegram.py
Restart=always
RestartSec=10
Environment=TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin

[Install]
WantedBy=default.target
EOF

    systemctl --user daemon-reload
    systemctl --user enable yt-summarizer
    systemctl --user start yt-summarizer
    
    echo "✅ Service installed and started!"
    echo "   Logs: journalctl --user -u yt-summarizer -f"
    echo "   Stop: systemctl --user stop yt-summarizer"
fi

echo ""
echo "🎬 Done! Share a YouTube link to your bot on Telegram."
