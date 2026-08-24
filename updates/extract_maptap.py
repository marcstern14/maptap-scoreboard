#!/usr/bin/env python3
"""
Maptap iMessage Extractor
Reads ~/Library/Messages/chat.db, finds Maptap scores, writes scores.json
"""

import sqlite3
import json
import hashlib
import re
import os
import sys
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# ── CONFIGURATION ────────────────────────────────────────────────────────────
# players.json maps SHA-256 hashed phone numbers → display names.
# This keeps real phone numbers out of the repo while allowing lookups.
# To add a player, hash their E.164 number:
#   python3 -c "import hashlib; print(hashlib.sha256('+1XXXXXXXXXX'.encode()).hexdigest())"

PLAYERS_FILE = Path(__file__).parent / "players.json"


def hash_phone(phone):
    """SHA-256 hash a phone number for lookup against players.json."""
    return hashlib.sha256(phone.encode()).hexdigest()


def _load_players():
    """Load the PLAYERS dict and OWNER_PHONE hash from players.json."""
    if not PLAYERS_FILE.exists():
        sys.exit(
            f"❌  Missing {PLAYERS_FILE}\n"
            f"   Copy players.example.json → players.json and add hashed phone numbers."
        )
    with open(PLAYERS_FILE) as f:
        data = json.load(f)
    return data["players"], data["owner"]


PLAYERS, OWNER_PHONE = _load_players()

# Where to write the output (relative to this script, or absolute path)
OUTPUT_FILE = Path(__file__).parent.parent / "scores.json"

# ─────────────────────────────────────────────────────────────────────────────

WEIGHTS = [1, 1, 2, 3, 3]
DB_PATH = Path.home() / "Library" / "Messages" / "chat.db"


def extract_body_text(blob):
    """Extract plain text from attributedBody (typedstream format).

    The text is stored after a \\x01+ marker followed by a length byte.
    RCS messages often store content here instead of the text column.
    """
    if not blob:
        return None
    try:
        idx = blob.find(b"\x01+")
        if idx < 0:
            return None
        length = blob[idx + 2]
        text_start = idx + 3
        text = blob[text_start : text_start + length].decode("utf-8", errors="ignore")
        return text.strip() if text.strip() else None
    except Exception:
        return None


def open_db():
    """Copy DB to temp file to avoid lock issues, return connection."""
    env_path = os.environ.get("MAPTAP_DB_COPY")
    if env_path:
        return sqlite3.connect(env_path), env_path
    if not DB_PATH.exists():
        sys.exit(f"❌  Could not find iMessage database at {DB_PATH}")
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    shutil.copy2(DB_PATH, tmp.name)
    return sqlite3.connect(tmp.name), tmp.name


def apple_time_to_iso(ts):
    """Convert Apple epoch (nanoseconds since 2001-01-01) to ISO date string."""
    if not ts:
        return None
    # macOS Monterey+ uses nanoseconds; older uses seconds
    if ts > 1e12:
        ts = ts / 1e9
    apple_epoch = datetime(2001, 1, 1, tzinfo=timezone.utc)
    dt = apple_epoch + __import__('datetime').timedelta(seconds=ts)
    return dt.strftime("%b %-d %Y")


def normalize_handle(handle_id):
    """Strip spaces/dashes from phone numbers for consistent matching."""
    if not handle_id:
        return None
    h = handle_id.strip()
    # Remove formatting characters but keep +
    h = re.sub(r'[\s\-\(\)]', '', h)
    # Normalize 10-digit US numbers to E.164
    if re.match(r'^\d{10}$', h):
        h = '+1' + h
    return h


def resolve_player(handle_id):
    """Return display name for a handle, or a formatted fallback."""
    normalized = normalize_handle(handle_id)
    if not normalized:
        return f"Unknown ({handle_id})"
    hashed = hash_phone(normalized)
    if hashed in PLAYERS:
        return PLAYERS[hashed]
    # Try matching without country code
    stripped = normalized.lstrip('+1')
    if stripped:
        alt_hash = hash_phone('+1' + stripped)
        if alt_hash in PLAYERS:
            return PLAYERS[alt_hash]
    return f"Unknown ({handle_id})"


def parse_maptap_message(text):
    """
    Parse a Maptap share message. Returns dict or None.

    Expected format:
        maptap.gg May 8
        97🔥 96🔥 49🫣 80✨ 97🔥
        Final score: 822
    """
    if not text:
        return None

    text = text.strip()

    final_match = re.search(r'(?:final\s*score)[:\s]+(\d+)', text, re.IGNORECASE)
    reported = int(final_match.group(1)) if final_match else None

    # Extract date
    date_match = re.search(
        r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}(?:\s+\d{4})?',
        text, re.IGNORECASE
    )
    date_str = date_match.group(0).strip() if date_match else None

    # Extract 5 round scores — numbers 0-100 adjacent to emoji or on score line
    # Strategy 1: find line that has 5 scores with emoji separators
    rounds = []
    for line in text.split('\n'):
        nums = re.findall(r'\b(\d{1,3})\b', line)
        nums = [int(n) for n in nums if 0 <= int(n) <= 100]
        if len(nums) == 5:
            rounds = nums
            break

    # Strategy 2: grab first 5 numbers in range 0-100 that aren't the final score
    if not rounds:
        all_nums = re.findall(r'\b(\d{1,3})\b', text)
        exclude = {reported} if reported else set()
        candidates = [int(n) for n in all_nums if 0 <= int(n) <= 100 and int(n) not in exclude]
        if len(candidates) >= 5:
            rounds = candidates[:5]

    if len(rounds) != 5:
        return None

    computed = sum(r * w for r, w in zip(rounds, WEIGHTS))

    return {
        "date": date_str,
        "rounds": rounds,
        "score": computed,
        "reported": reported or computed,
        "perfect": len([i for i in rounds if i == 100]),
    }


def extract_scores(conn):
    """Pull all Maptap score messages from the entire iMessage database."""
    owner_name = PLAYERS.get(OWNER_PHONE, "Me")
    cur = conn.cursor()
    cur.execute("""
        SELECT
            m.ROWID,
            m.text,
            m.date,
            m.is_from_me,
            h.id AS handle_id,
            m.attributedBody
        FROM message m
        LEFT JOIN handle h ON h.ROWID = m.handle_id
        WHERE (m.text LIKE '%maptap%'
            OR instr(m.attributedBody, X'6D6170746170') > 0)
        ORDER BY m.date ASC
    """)

    rows = cur.fetchall()
    results = []
    skipped = 0
    seen_ids = set()

    for rowid, text, apple_ts, is_from_me_flag, handle_id, attr_body in rows:
        if not text:
            text = extract_body_text(attr_body)
        if rowid in seen_ids:
            continue
        seen_ids.add(rowid)

        parsed = parse_maptap_message(text)
        if not parsed:
            skipped += 1
            continue

        if is_from_me_flag:
            player = owner_name
        else:
            player = resolve_player(handle_id)

        apple_date = apple_time_to_iso(apple_ts)
        # Prefer the date from the Maptap message (actual game date)
        # over the iMessage timestamp (when it was sent, could be after midnight)
        iso_date = apple_date
        if parsed["date"]:
            try:
                # parsed["date"] is like "April 30" or "May 1" — may lack year
                date_str = parsed["date"]
                if not re.search(r'\d{4}', date_str):
                    # Borrow year from the Apple timestamp
                    apple_year = apple_date.split()[-1] if apple_date else "2026"
                    date_str = date_str + " " + apple_year
                game_dt = datetime.strptime(date_str, "%B %d %Y")
                iso_date = game_dt.strftime("%b %-d %Y")
            except Exception:
                pass
        results.append({
            "id": rowid,
            "player": player,
            "date": parsed["date"] or iso_date,
            "isoDate": iso_date,
            "rounds": parsed["rounds"],
            "score": parsed["score"],
            "reported": parsed["reported"],
            "perfect": parsed["perfect"],
        })

    # Same rounds on the same date = same game; credit the first sender only
    seen_games = set()
    unique = []
    for entry in results:
        game_key = (entry["isoDate"], tuple(entry["rounds"]))
        if game_key in seen_games:
            continue
        seen_games.add(game_key)
        unique.append(entry)

    # One score per player per day (keep the highest)
    best = {}
    for entry in unique:
        key = (entry["player"], entry["isoDate"])
        if key not in best or entry["score"] > best[key]["score"]:
            best[key] = entry
    deduped = sorted(best.values(), key=lambda s: s["id"])

    today = datetime.now().strftime("%b %-d %Y")
    deduped = [e for e in deduped if e["isoDate"] != today]

    # Karen joined starting May 14, 2026
    karen_start = datetime(2026, 5, 14)
    deduped = [e for e in deduped if e["player"] != "Karen"
               or datetime.strptime(e["isoDate"], "%b %d %Y") >= karen_start]

    return deduped, skipped


def main():
    print("🗺️  Maptap iMessage Extractor\n")

    conn, tmp_path = open_db()

    try:
        print("🔍 Extracting scores from all chats...")
        scores, skipped = extract_scores(conn)

        if not scores:
            print("❌  No parseable Maptap scores found.")
            sys.exit(1)

        output = {
            "generated": datetime.now().isoformat(),
            "total": len(scores),
            "scores": scores,
        }
        OUTPUT_FILE.write_text(json.dumps(output, indent=2))

        print(f"✅  Extracted {len(scores)} scores → {OUTPUT_FILE}")
        if skipped:
            print(f"   ({skipped} messages skipped — could not parse)")

        players = {}
        for s in scores:
            players.setdefault(s["player"], []).append(s["score"])

        print("\n📊 Summary:")
        for name, vals in sorted(players.items()):
            avg = sum(vals) / len(vals)
            perfect = sum(1 for s in scores if s["player"] == name and s["perfect"])
            print(f"   {name}: {len(vals)} games, avg {avg:.0f}, {perfect} perfect")

    finally:
        conn.close()
        os.unlink(tmp_path)


if __name__ == "__main__":
    main()
