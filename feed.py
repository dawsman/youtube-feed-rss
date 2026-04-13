#!/usr/bin/env python3
"""
YouTube Feed RSS Manager
Curate YouTube subscriptions into tagged, filterable RSS feeds.
"""

import sqlite3
import argparse
import sys
import os
from datetime import datetime, timezone
from pathlib import Path

import yt_dlp
from feedgen.feed import FeedGenerator

DEFAULT_DB = Path.home() / ".config" / "youtube-feed" / "feed.db"
DEFAULT_OUTPUT = Path.home() / ".config" / "youtube-feed" / "feed.xml"


def get_db_path():
    return Path(os.environ.get("YTFeed_DB", DEFAULT_DB))


def get_output_dir():
    return Path(os.environ.get("YTFeed_OUTPUT", DEFAULT_OUTPUT)).parent


def init_db(db_path: Path):
    """Initialize SQLite database with schema."""
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS channels (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            tags TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS videos (
            id TEXT PRIMARY KEY,
            channel_id TEXT REFERENCES channels(id),
            title TEXT NOT NULL,
            published_at TIMESTAMP,
            fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE INDEX IF NOT EXISTS idx_videos_channel ON videos(channel_id);
        CREATE INDEX IF NOT EXISTS idx_videos_published ON videos(published_at);
    """)
    conn.commit()
    conn.close()
    print(f"Initialized database: {db_path}")


def normalize_tags(tags: str) -> str:
    """Normalize tag string to lowercase, comma-separated."""
    if not tags:
        return ""
    return ",".join(
        sorted(set(t.strip().lower() for t in tags.split(",") if t.strip()))
    )


def get_channel_info(channel_id: str) -> dict:
    """Fetch channel metadata via yt-dlp."""
    ydl_opts = {
        "quiet": True,
        "extract_flat": True,
        "skip_download": True,
    }

    url = f"https://www.youtube.com/channel/{channel_id}"
    if channel_id.startswith("@"):
        url = f"https://www.youtube.com/{channel_id}"
    elif "/" not in channel_id and len(channel_id) != 24:
        url = f"https://www.youtube.com/c/{channel_id}"

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            return {
                "id": info.get("channel_id", channel_id),
                "name": info.get("channel", channel_id),
            }
        except Exception as e:
            print(f"Error fetching channel: {e}", file=sys.stderr)
            sys.exit(1)


def add_channel(db_path: Path, channel_id: str, tags: str = ""):
    """Add a channel to the database."""
    info = get_channel_info(channel_id)
    normalized_tags = normalize_tags(tags)

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO channels (id, name, tags) VALUES (?, ?, ?)",
            (info["id"], info["name"], normalized_tags),
        )
        conn.commit()
        tag_str = f" [{normalized_tags}]" if normalized_tags else ""
        print(f"Added: {info['name']}{tag_str}")
    except sqlite3.IntegrityError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()


def list_channels(db_path: Path, tag: str = None):
    """List channels, optionally filtered by tag."""
    conn = sqlite3.connect(db_path)

    if tag:
        cursor = conn.execute(
            "SELECT id, name, tags FROM channels WHERE tags LIKE ? ORDER BY name",
            (f"%{tag.lower()}%",),
        )
    else:
        cursor = conn.execute("SELECT id, name, tags FROM channels ORDER BY name")

    rows = cursor.fetchall()
    conn.close()

    if not rows:
        print("No channels found.")
        return

    for row in rows:
        channel_id, name, tags = row
        tag_str = f" [{tags}]" if tags else ""
        print(f"{name}{tag_str}")
        print(f"  ID: {channel_id}")


def tag_channel(
    db_path: Path, name_query: str, add_tags: str = None, remove_tags: str = None
):
    """Add or remove tags from a channel."""
    conn = sqlite3.connect(db_path)

    cursor = conn.execute(
        "SELECT id, name, tags FROM channels WHERE name LIKE ?", (f"%{name_query}%",)
    )
    rows = cursor.fetchall()

    if not rows:
        print(f"No channel matching '{name_query}' found.")
        conn.close()
        return

    if len(rows) > 1:
        print(f"Multiple matches for '{name_query}':")
        for row in rows:
            print(f"  - {row[1]}")
        conn.close()
        return

    channel_id, name, current_tags = rows[0]
    current_set = set(current_tags.split(",")) if current_tags else set()

    if add_tags:
        current_set.update(t.strip().lower() for t in add_tags.split(","))
    if remove_tags:
        current_set.discard(remove_tags.lower())

    new_tags = normalize_tags(",".join(current_set))

    conn.execute("UPDATE channels SET tags = ? WHERE id = ?", (new_tags, channel_id))
    conn.commit()
    conn.close()

    tag_str = f" [{new_tags}]" if new_tags else ""
    print(f"Updated: {name}{tag_str}")


def search_channels(db_path: Path, query: str):
    """Search channels by name or tags."""
    conn = sqlite3.connect(db_path)
    cursor = conn.execute(
        "SELECT id, name, tags FROM channels WHERE name LIKE ? OR tags LIKE ? ORDER BY name",
        (f"%{query}%", f"%{query}%"),
    )
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        print(f"No channels matching '{query}' found.")
        return

    for row in rows:
        channel_id, name, tags = row
        tag_str = f" [{tags}]" if tags else ""
        print(f"{name}{tag_str}")


def fetch_videos(db_path: Path, max_videos: int = 10):
    """Sync latest videos from all channels."""
    conn = sqlite3.connect(db_path)
    cursor = conn.execute("SELECT id FROM channels")
    channel_ids = [row[0] for row in cursor.fetchall()]
    conn.close()

    ydl_opts = {
        "quiet": True,
        "extract_flat": True,
        "skip_download": True,
        "playlistend": max_videos,
    }

    total_added = 0

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        for channel_id in channel_ids:
            url = f"https://www.youtube.com/channel/{channel_id}/videos"
            try:
                playlist = ydl.extract_info(url, download=False)
                if not playlist.get("entries"):
                    continue

                conn = sqlite3.connect(db_path)
                for entry in playlist["entries"]:
                    video_id = entry.get("id")
                    title = entry.get("title", "Unknown")

                    try:
                        conn.execute(
                            "INSERT OR IGNORE INTO videos (id, channel_id, title, published_at) VALUES (?, ?, ?, ?)",
                            (video_id, channel_id, title, datetime.now(timezone.utc)),
                        )
                        if conn.total_changes > 0:
                            total_added += 1
                    except sqlite3.IntegrityError:
                        pass

                conn.commit()
                conn.close()

            except Exception as e:
                print(f"Error fetching {channel_id}: {e}", file=sys.stderr)

    print(f"Synced {total_added} new videos")


def generate_feeds(db_path: Path, output_dir: Path):
    """Generate RSS feeds from database."""
    conn = sqlite3.connect(db_path)

    # Get all videos with channel info
    cursor = conn.execute("""
        SELECT v.id, v.title, v.published_at, c.name, c.tags
        FROM videos v
        JOIN channels c ON v.channel_id = c.id
        ORDER BY v.published_at DESC
        LIMIT 100
    """)
    rows = cursor.fetchall()

    # Group by tag
    tag_videos = {}
    for row in rows:
        video_id, title, published_at, channel_name, tags = row
        tag_list = tags.split(",") if tags else ["untagged"]
        for tag in tag_list:
            tag = tag.strip() or "untagged"
            if tag not in tag_videos:
                tag_videos[tag] = []
            tag_videos[tag].append(
                {
                    "id": video_id,
                    "title": title,
                    "channel": channel_name,
                    "published": published_at,
                }
            )

    conn.close()

    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate master feed
    fg = FeedGenerator()
    fg.title("YouTube Feed")
    fg.description("Curated YouTube subscriptions")
    fg.link(href="https://youtube.com")

    for video in rows[:50]:
        video_id, title, published_at, channel_name, tags = video
        fe = fg.add_entry()
        fe.title(f"[{channel_name}] {title}")
        fe.link(href=f"https://youtube.com/watch?v={video_id}")
        if published_at:
            fe.published(published_at)

    master_path = output_dir / "feed.xml"
    fg.rss_file(str(master_path))
    print(f"Generated: {master_path}")

    # Generate per-tag feeds
    for tag, videos in tag_videos.items():
        fg = FeedGenerator()
        fg.title(f"YouTube Feed - {tag}")
        fg.description(f"YouTube videos tagged: {tag}")
        fg.link(href="https://youtube.com")

        for video in videos[:30]:
            fe = fg.add_entry()
            fe.title(f"[{video['channel']}] {video['title']}")
            fe.link(href=f"https://youtube.com/watch?v={video['id']}")
            fe.category(term=tag)

        tag_path = output_dir / f"feed-{tag}.xml"
        fg.rss_file(str(tag_path))
        print(f"Generated: {tag_path}")


def show_stats(db_path: Path):
    """Show database statistics."""
    conn = sqlite3.connect(db_path)

    cursor = conn.execute("SELECT COUNT(*) FROM channels")
    channel_count = cursor.fetchone()[0]

    cursor = conn.execute("SELECT COUNT(*) FROM videos")
    video_count = cursor.fetchone()[0]

    cursor = conn.execute("SELECT tags FROM channels WHERE tags IS NOT NULL")
    all_tags = set()
    for row in cursor.fetchall():
        all_tags.update(t.strip() for t in row[0].split(",") if t.strip())

    conn.close()

    print(f"Channels: {channel_count}")
    print(f"Videos: {video_count}")
    print(f"Tags: {len(all_tags)}")
    if all_tags:
        print(f"  {', '.join(sorted(all_tags))}")


def main():
    parser = argparse.ArgumentParser(description="YouTube Feed RSS Manager")
    parser.add_argument(
        "--db", help="Database path (default: ~/.config/youtube-feed/feed.db)"
    )
    parser.add_argument(
        "--output", help="Output directory (default: ~/.config/youtube-feed/)"
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # init
    subparsers.add_parser("init", help="Initialize database")

    # add
    add_parser = subparsers.add_parser("add", help="Add a channel")
    add_parser.add_argument("channel_id", help="YouTube channel ID or @handle")
    add_parser.add_argument("--tag", help="Comma-separated tags")

    # list
    list_parser = subparsers.add_parser("list", help="List channels")
    list_parser.add_argument("--tag", help="Filter by tag")

    # tag
    tag_parser = subparsers.add_parser("tag", help="Tag a channel")
    tag_parser.add_argument("name", help="Channel name (partial match)")
    tag_parser.add_argument("--add", help="Tags to add (comma-separated)")
    tag_parser.add_argument("--remove", help="Tag to remove")

    # search
    search_parser = subparsers.add_parser("search", help="Search channels")
    search_parser.add_argument("query", help="Search term")

    # sync
    sync_parser = subparsers.add_parser("sync", help="Fetch latest videos")
    sync_parser.add_argument("--max", type=int, default=10, help="Videos per channel")

    # generate
    subparsers.add_parser("generate", help="Generate RSS feeds")

    # stats
    subparsers.add_parser("stats", help="Show statistics")

    args = parser.parse_args()

    db_path = Path(args.db) if args.db else get_db_path()
    output_dir = Path(args.output) if args.output else get_output_dir()

    if args.command == "init":
        init_db(db_path)
    elif args.command == "add":
        add_channel(db_path, args.channel_id, args.tag or "")
    elif args.command == "list":
        list_channels(db_path, args.tag)
    elif args.command == "tag":
        tag_channel(db_path, args.name, args.add, args.remove)
    elif args.command == "search":
        search_channels(db_path, args.query)
    elif args.command == "sync":
        fetch_videos(db_path, args.max)
    elif args.command == "generate":
        generate_feeds(db_path, output_dir)
    elif args.command == "stats":
        show_stats(db_path)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
