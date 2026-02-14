# YouTube Feed RSS

A lightweight Python tool to curate YouTube subscriptions into tagged, filterable RSS feeds. Built for people who want algorithm-free video consumption with their own organizational logic.

## Why

YouTube's subscription feed is chronological chaos. This gives you:
- **Tag-based filtering** — organize channels by topic (tech, finance, cooking, etc.)
- **Multiple RSS outputs** — one master feed, or per-tag feeds
- **Manual curation** — you decide what goes in, not an algorithm
- **Portable data** — SQLite database you own and can query

## Quick Start

```bash
# Setup
pip install -r requirements.txt

# Initialize database
python feed.py init

# Add a channel
python feed.py add "UCYO_jab_esuFRV4b17AJtAw" --tag "math,education"

# Tag existing channels
python feed.py tag "Channel Name" --add "new-tag"

# List channels by tag
python feed.py list --tag "math"

# Search channels
python feed.py search "3blue"

# Generate RSS feeds
python feed.py sync          # Fetch latest videos
python feed.py generate      # Build feed.xml and feed-<tag>.xml files

# Stats
python feed.py stats
```

## Database Schema

```sql
CREATE TABLE channels (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    tags TEXT,  -- comma-separated: "tech,programming,linux"
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE videos (
    id TEXT PRIMARY KEY,
    channel_id TEXT REFERENCES channels(id),
    title TEXT NOT NULL,
    published_at TIMESTAMP,
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## RSS Output

- `feed.xml` — Master feed with all channels
- `feed-<tag>.xml` — Per-tag feeds (e.g., `feed-tech.xml`)

Each feed includes:
- Channel name in item title: `[Channel] Video Title`
- Tags as categories
- YouTube link + embed
- Published date

## Use Cases

- **Feed readers** — Import into Feedly, Inoreader, FreshRSS
- **Automation** — `cron` job to sync daily, generate feeds
- **Archive** — Query SQLite for "what did I watch in 2024?"
- **Sharing** — Host feeds on a static site for others

## Requirements

- Python 3.9+
- `yt-dlp` (for metadata extraction)
- `feedgen` (for RSS generation)

## License

MIT
