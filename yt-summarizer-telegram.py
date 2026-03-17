#!/usr/bin/env python3
"""
yt-summarizer-telegram.py — YouTube summarizer via Telegram bot

Usage:
    export TELEGRAM_BOT_TOKEN="your-token-here"
    python3 yt-summarizer-telegram.py
"""

import os
import re
import sys
import subprocess
import requests
import threading
import time
import sqlite3
import json
from pathlib import Path

# Project directory (where this script and mcp config live)
PROJECT_DIR = Path(__file__).parent.resolve()
TRANSCRIPTS_DIR = PROJECT_DIR / "transcripts"
TRANSCRIPTS_DIR.mkdir(exist_ok=True)

# Add youtube-mcp to path so we can import transcript functions directly
sys.path.insert(0, str(PROJECT_DIR / "youtube-mcp"))
from server import extract_video_id, get_video_metadata, get_video_transcript

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    print("Error: Set TELEGRAM_BOT_TOKEN environment variable")
    exit(1)

API = f"https://api.telegram.org/bot{BOT_TOKEN}"
YT_PATTERN = re.compile(r'https?://(?:www\.)?(?:youtube\.com|youtu\.be)/\S+')

# Chunking config: ~15 minutes per chunk (in seconds)
CHUNK_DURATION_SECS = 15 * 60

# In-memory map: chat_id → video_id (lost on restart, that's fine)
latest_video = {}

DB_PATH = PROJECT_DIR / "sessions.db"


def init_db():
    """Open SQLite DB and create tables if needed."""
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""CREATE TABLE IF NOT EXISTS videos (
        video_id TEXT PRIMARY KEY,
        title TEXT, channel TEXT, summary_text TEXT,
        chunks TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        video_id TEXT NOT NULL REFERENCES videos(video_id),
        chat_id INTEGER NOT NULL,
        message_id INTEGER,
        role TEXT NOT NULL,
        content TEXT,
        created_at REAL
    )""")
    conn.commit()
    return conn


db = init_db()


def save_video(video_id, title, channel, summary_text, chunks):
    """Insert or replace a video record."""
    db.execute(
        "INSERT OR REPLACE INTO videos (video_id, title, channel, summary_text, chunks) VALUES (?,?,?,?,?)",
        (video_id, title, channel, summary_text, json.dumps([(s, e, t) for s, e, t in chunks])),
    )
    db.commit()


def save_message(video_id, chat_id, message_id, role, content):
    """Record a user or assistant message."""
    db.execute(
        "INSERT INTO messages (video_id, chat_id, message_id, role, content, created_at) VALUES (?,?,?,?,?,?)",
        (video_id, chat_id, message_id, role, content, time.time()),
    )
    db.commit()


def get_video(video_id):
    """Return a video dict or None."""
    row = db.execute("SELECT * FROM videos WHERE video_id=?", (video_id,)).fetchone()
    if not row:
        return None
    return {
        "video_id": row["video_id"], "title": row["title"],
        "channel": row["channel"], "summary_text": row["summary_text"],
        "chunks": json.loads(row["chunks"]),
    }


def get_video_by_message(chat_id, message_id):
    """Find which video a bot message belongs to (reply-chain lookup)."""
    row = db.execute(
        "SELECT video_id FROM messages WHERE chat_id=? AND message_id=? AND role='assistant' LIMIT 1",
        (chat_id, message_id),
    ).fetchone()
    if not row:
        return None
    return get_video(row["video_id"])


def get_history(video_id, limit=5):
    """Return recent conversation pairs for a video as [(role, content), ...]."""
    rows = db.execute(
        "SELECT role, content FROM messages WHERE video_id=? ORDER BY id DESC LIMIT ?",
        (video_id, limit * 2),
    ).fetchall()
    return [(r["role"], r["content"]) for r in reversed(rows)]


def get_updates(offset=None):
    """Long poll for messages (30s timeout)"""
    params = {"timeout": 30}
    if offset:
        params["offset"] = offset
    try:
        r = requests.get(f"{API}/getUpdates", params=params, timeout=35)
        return r.json().get("result", [])
    except Exception:
        return []


def send_message(chat_id, text, reply_to_message_id=None):
    """Send reply to chat, splitting if over 4096 chars. Returns first message_id."""
    first_msg_id = None
    while text:
        chunk = text[:4096]
        text = text[4096:]
        payload = {"chat_id": chat_id, "text": chunk}
        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id
        resp = requests.post(f"{API}/sendMessage", json=payload)
        if first_msg_id is None:
            try:
                first_msg_id = resp.json().get("result", {}).get("message_id")
            except Exception:
                pass
    return first_msg_id


def send_typing(chat_id):
    """Send typing indicator."""
    requests.post(f"{API}/sendChatAction", json={
        "chat_id": chat_id,
        "action": "typing",
    })


class TypingIndicator:
    """Sends typing action every 4s in a background thread."""

    def __init__(self, chat_id):
        self.chat_id = chat_id
        self._stop = threading.Event()
        self._thread = None

    def __enter__(self):
        send_typing(self.chat_id)
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *args):
        self._stop.set()
        self._thread.join(timeout=5)

    def _loop(self):
        while not self._stop.wait(4):
            send_typing(self.chat_id)


def format_timestamp(seconds):
    """Format seconds as H:MM:SS or M:SS."""
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def chunk_segments(segments):
    """Split transcript segments into chunks of ~CHUNK_DURATION_SECS each.

    Returns list of (start_time, end_time, text) tuples.
    """
    if not segments:
        return []

    chunks = []
    current_texts = []
    chunk_start = segments[0].get("start", 0)

    for seg in segments:
        seg_start = seg.get("start", 0)
        # Start new chunk if we've exceeded the duration threshold
        if current_texts and (seg_start - chunk_start) >= CHUNK_DURATION_SECS:
            chunk_end = seg_start
            chunks.append((chunk_start, chunk_end, " ".join(current_texts)))
            current_texts = []
            chunk_start = seg_start
        current_texts.append(seg.get("text", ""))

    # Final chunk
    if current_texts:
        last = segments[-1]
        chunk_end = last.get("start", 0) + last.get("duration", 0)
        chunks.append((chunk_start, chunk_end, " ".join(current_texts)))

    return chunks


def call_claude(prompt, timeout=120, web_search=False, transcript_search=False):
    """Call claude --print --model haiku and return the output."""
    cmd = ["claude", "--print", "--model", "haiku"]
    allowed_tools = []
    if web_search:
        allowed_tools.append("mcp__duckduckgo__search")
    if transcript_search:
        allowed_tools.append("mcp__youtube-mcp__search_transcript")
    if allowed_tools:
        cmd += ["--mcp-config", str(PROJECT_DIR / ".mcp.json"),
                "--allowedTools", ",".join(allowed_tools)]
    cmd += ["--", prompt]
    env = {**os.environ, "CLAUDECODE": ""}
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=PROJECT_DIR,
        env=env,
    )
    return result.stdout.strip() or result.stderr.strip() or "No response"


def summarize(url, chat_id):
    """Fetch transcript directly and summarize with Claude Haiku.

    Returns dict: {text, video_id, title, channel, chunks}
    On error, video_id is None so session creation is skipped.
    """
    video_id = extract_video_id(url)
    metadata = get_video_metadata(video_id)

    if "error" in metadata:
        return {"text": f"Failed to get video info: {metadata['error']}",
                "video_id": None, "title": None, "channel": None, "chunks": []}

    title = metadata.get("title", "Unknown")
    channel = metadata.get("channel", "Unknown")

    transcript_data = get_video_transcript(video_id)
    if "error" in transcript_data:
        return {"text": f"Failed to get transcript: {transcript_data['error']}",
                "video_id": None, "title": title, "channel": channel, "chunks": []}

    segments = transcript_data.get("segments", [])
    if not segments:
        return {"text": "No transcript segments found.",
                "video_id": None, "title": title, "channel": channel, "chunks": []}

    # Cache transcript segments to disk for search_transcript tool
    (TRANSCRIPTS_DIR / f"{video_id}.json").write_text(json.dumps(segments))

    chunks = chunk_segments(segments)
    num_chunks = len(chunks)

    print(f"  Video: {title} | {num_chunks} chunk(s)")

    header = f"**{title}** — {channel}\n\n"

    if num_chunks == 1:
        full_text = chunks[0][2]
        prompt = f"""Summarize this YouTube video transcript. The video is titled "{title}" by {channel}.

Provide:
1. One-line TLDR
2. 3-5 key bullet points
3. Notable quotes (if any)

Transcript:
{full_text}"""

        try:
            summary = call_claude(prompt, timeout=120)
            return {"text": header + summary, "video_id": video_id,
                    "title": title, "channel": channel, "chunks": chunks}
        except subprocess.TimeoutExpired:
            return {"text": header + "Timed out processing video.",
                    "video_id": None, "title": title, "channel": channel, "chunks": chunks}
        except Exception as e:
            return {"text": header + f"Error: {e}",
                    "video_id": None, "title": title, "channel": channel, "chunks": chunks}

    # Large video: chunk-by-chunk summarization
    chunk_summaries = []
    for i, (start, end, text) in enumerate(chunks):
        label = f"{format_timestamp(start)}-{format_timestamp(end)}"
        send_message(chat_id, f"Processing chunk {i+1}/{num_chunks} ({label})...")
        print(f"  Chunk {i+1}/{num_chunks}: {label}")

        prompt = f"""Summarize this section ({label}) of a YouTube video titled "{title}" by {channel}.

Provide key points and notable quotes from this section.

Transcript:
{text}"""

        try:
            summary = call_claude(prompt, timeout=120)
            chunk_summaries.append(f"[{label}]\n{summary}")
        except subprocess.TimeoutExpired:
            chunk_summaries.append(f"[{label}]\nTimed out on this chunk.")
        except Exception as e:
            chunk_summaries.append(f"[{label}]\nError: {e}")

    send_message(chat_id, "Combining summaries...")
    combined = "\n\n---\n\n".join(chunk_summaries)

    final_prompt = f"""Below are summaries of different sections of a YouTube video titled "{title}" by {channel}.

Combine these into a single cohesive summary with:
1. One-line TLDR
2. 5-10 key bullet points covering the whole video
3. Notable quotes (if any)

Section summaries:
{combined}"""

    try:
        final_summary = call_claude(final_prompt, timeout=120)
        return {"text": header + final_summary, "video_id": video_id,
                "title": title, "channel": channel, "chunks": chunks}
    except subprocess.TimeoutExpired:
        return {"text": header + "Final combination timed out. Here are the section summaries:\n\n" + combined,
                "video_id": video_id, "title": title, "channel": channel, "chunks": chunks}
    except Exception as e:
        return {"text": header + f"Final combination error: {e}\n\nSection summaries:\n\n" + combined,
                "video_id": video_id, "title": title, "channel": channel, "chunks": chunks}


def find_relevant_chunks(question, chunks):
    """Find transcript chunks matching timestamps mentioned in the question.

    Matches patterns like "1:23:45", "12:34", "5 minutes", "at 30 min".
    Returns list of (label, text) tuples.
    """
    relevant = []

    # Match H:MM:SS or M:SS or MM:SS timestamps
    ts_matches = re.findall(r'(\d{1,2}):(\d{2})(?::(\d{2}))?', question)
    target_secs = []
    for match in ts_matches:
        h_or_m, m_or_s, s = match
        if s:  # H:MM:SS
            target_secs.append(int(h_or_m) * 3600 + int(m_or_s) * 60 + int(s))
        else:  # M:SS
            target_secs.append(int(h_or_m) * 60 + int(m_or_s))

    # Match "N minutes" or "N min"
    min_matches = re.findall(r'(\d+)\s*(?:minutes?|mins?)', question, re.IGNORECASE)
    for m in min_matches:
        target_secs.append(int(m) * 60)

    for target in target_secs:
        for start, end, text in chunks:
            if start <= target <= end:
                label = f"{format_timestamp(start)}-{format_timestamp(end)}"
                if (label, text) not in relevant:
                    relevant.append((label, text))

    return relevant


def handle_followup(video, question, chat_id):
    """Handle a follow-up question about a summarized video.

    video: dict from get_video() with keys video_id, title, channel, summary_text, chunks.
    Loads conversation history from DB.
    """
    # Build conversation history from DB
    history = get_history(video["video_id"], limit=5)
    history_lines = []
    for role, content in history:
        history_lines.append(f"{'User' if role == 'user' else 'Assistant'}: {content}")
    history_text = "\n".join(history_lines)

    # Find relevant transcript chunks if timestamps are mentioned
    chunk_context = ""
    relevant = find_relevant_chunks(question, video["chunks"])
    if relevant:
        chunk_parts = []
        for label, text in relevant[:2]:
            chunk_parts.append(f"[{label}]\n{text}")
        chunk_context = "\n\nRelevant transcript sections:\n" + "\n\n".join(chunk_parts)

    prompt = f"""You are answering a follow-up question about a YouTube video.

Video: "{video['title']}" by {video['channel']}
Video ID: {video['video_id']}

Summary:
{video['summary_text']}
{chunk_context}

{"Previous conversation:" + chr(10) + history_text if history_text else ""}

User's question: {question}

You have two tools available:
- search_transcript: Search the full video transcript by keyword. Use this when you need to find specific details, quotes, or topics mentioned in the video that aren't in the summary. Pass video_id="{video['video_id']}" and a search query.
- web search: Use this if the question goes beyond the video content.

Answer concisely based on the video content. Use search_transcript to look up details before saying you don't have access to the transcript."""

    try:
        answer = call_claude(prompt, timeout=120, web_search=True, transcript_search=True)
    except subprocess.TimeoutExpired:
        answer = "Sorry, timed out generating an answer. Try again?"
    except Exception as e:
        answer = f"Error: {e}"

    return answer


def main():
    print("YouTube Summarizer Bot running...")
    print("  Send a YouTube URL to your bot")
    print("  Reply to a summary to ask follow-up questions")

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

            # Check if this is a reply to another message
            reply_to = msg.get("reply_to_message", {}).get("message_id")

            # 1. YouTube URL → summarize, persist to DB
            match = YT_PATTERN.search(text)
            if match:
                url = match.group()
                print(f"Processing: {url}")
                send_message(chat_id, "Processing...")

                with TypingIndicator(chat_id):
                    result = summarize(url, chat_id)

                summary_msg_id = send_message(chat_id, result["text"])
                print("  Sent summary")

                # Persist if summarization succeeded
                if result["video_id"] and summary_msg_id:
                    save_video(result["video_id"], result["title"], result["channel"],
                               result["text"], result["chunks"])
                    save_message(result["video_id"], chat_id, summary_msg_id,
                                 "assistant", result["text"])
                    latest_video[chat_id] = result["video_id"]
                    print(f"  Saved video {result['video_id']} for chat {chat_id}")
                continue

            # 2. Reply to a bot message → look up video by reply target (survives restart)
            video = None
            if reply_to:
                video = get_video_by_message(chat_id, reply_to)

            # 3. Plain text (no URL, no reply match) → fall back to latest video
            if video is None:
                vid_id = latest_video.get(chat_id)
                if vid_id is None:
                    # Check DB for most recent video this chat interacted with
                    row = db.execute(
                        "SELECT video_id FROM messages WHERE chat_id=? ORDER BY id DESC LIMIT 1",
                        (chat_id,),
                    ).fetchone()
                    if row:
                        vid_id = row["video_id"]
                        latest_video[chat_id] = vid_id
                if vid_id:
                    video = get_video(vid_id)

            # 4. No video found
            if video is None:
                send_message(chat_id, "Send me a YouTube URL and I'll summarize it.")
                continue

            # Handle follow-up question
            print(f"  Follow-up Q about \"{video['title']}\": {text[:80]}")

            # Save user message, get answer, save assistant message
            save_message(video["video_id"], chat_id, msg.get("message_id"), "user", text)
            with TypingIndicator(chat_id):
                answer = handle_followup(video, text, chat_id)
            answer_msg_id = send_message(chat_id, answer, reply_to_message_id=msg.get("message_id"))
            save_message(video["video_id"], chat_id, answer_msg_id, "assistant", answer)
            print("  Sent follow-up answer")


if __name__ == "__main__":
    main()
