#!/usr/bin/env python3
"""
Show raw attributedBody content from RCS messages with NULL text.
Run: python3 updates/debug_missing.py
"""

import sqlite3
import shutil
import tempfile
import os
import re
from pathlib import Path
from datetime import datetime, timezone, timedelta

DB_PATH = Path.home() / "Library/Messages/chat.db"
APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)


def main():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    shutil.copy2(DB_PATH, tmp.name)
    conn = sqlite3.connect(tmp.name)
    cur = conn.cursor()

    # Get RCS messages from May 13 with NULL text but attributedBody
    cur.execute("""
        SELECT m.ROWID, m.date, m.is_from_me, h.id, m.attributedBody
        FROM message m
        JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
        LEFT JOIN handle h ON h.ROWID = m.handle_id
        WHERE cmj.chat_id = 72
          AND m.text IS NULL
          AND m.attributedBody IS NOT NULL
        ORDER BY m.date DESC
        LIMIT 5
    """)

    for rowid, ts, is_me, handle, blob in cur.fetchall():
        dt = APPLE_EPOCH + timedelta(seconds=ts / 1e9)
        local = dt.astimezone()
        sender = "ME" if is_me else (handle or "?")

        print(f"=== ROW {rowid}  {local.strftime('%m-%d %H:%M')}  from={sender} ===")
        print(f"blob length: {len(blob)} bytes")
        print(f"repr (first 500): {repr(blob[:500])}")
        print()

        decoded = blob.decode("utf-8", errors="replace")
        cleaned = re.sub(r"[\x00-\x09\x0b\x0c\x0e-\x1f\x7f]", " ", decoded)
        cleaned = re.sub(r" {2,}", "  ", cleaned)
        print(f"decoded (first 500): {cleaned[:500]}")
        print()
        print("---")
        print()

    conn.close()
    os.unlink(tmp.name)


if __name__ == "__main__":
    main()
