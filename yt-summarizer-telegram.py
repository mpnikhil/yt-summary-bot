#!/usr/bin/env python3
"""
yt-summarizer-telegram.py — YouTube summarizer via Telegram bot

Usage:
    export TELEGRAM_BOT_TOKEN="your-token-here"
    python3 yt-summarizer-telegram.py
"""

import os
import re
import subprocess
import requests

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    print("Error: Set TELEGRAM_BOT_TOKEN environment variable")
    exit(1)

API = f"https://api.telegram.org/bot{BOT_TOKEN}"
YT_PATTERN = re.compile(r'https?://(?:www\.)?(?:youtube\.com|youtu\.be)/\S+')

def get_updates(offset=None):
    """Long poll for messages (30s timeout)"""
    params = {"timeout": 30}
    if offset:
        params["offset"] = offset
    try:
        r = requests.get(f"{API}/getUpdates", params=params, timeout=35)
        return r.json().get("result", [])
    except:
        return []

def send_message(chat_id, text):
    """Send reply to chat"""
    requests.post(f"{API}/sendMessage", json={
        "chat_id": chat_id,
        "text": text[:4096]  # Telegram limit
    })

def summarize(url):
    """Call Claude CLI to summarize video"""
    try:
        result = subprocess.run(
            ["claude", "--print", f"""Summarize this YouTube video. Provide:
1. One-line TLDR
2. 3-5 key bullet points
3. Notable quotes (if any)

{url}"""],
            capture_output=True,
            text=True,
            timeout=120
        )
        return result.stdout or result.stderr or "No response from Claude"
    except subprocess.TimeoutExpired:
        return "⏱️ Timed out processing video"
    except FileNotFoundError:
        return "❌ Claude CLI not found"

def main():
    print("🎬 YouTube Summarizer Bot running...")
    print("   Send a YouTube URL to your bot")
    
    offset = None
    while True:
        updates = get_updates(offset)
        
        for update in updates:
            offset = update["update_id"] + 1
            
            msg = update.get("message", {})
            chat_id = msg.get("chat", {}).get("id")
            text = msg.get("text", "")
            
            if not chat_id or not text:
                continue
            
            # Find YouTube URL in message
            match = YT_PATTERN.search(text)
            if match:
                url = match.group()
                print(f"📥 {url}")
                send_message(chat_id, "⏳ Processing...")
                
                summary = summarize(url)
                send_message(chat_id, f"🎬 Summary:\n\n{summary}")
                print("✅ Sent")
            else:
                send_message(chat_id, "Send me a YouTube URL and I'll summarize it.")

if __name__ == "__main__":
    main()
