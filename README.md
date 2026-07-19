# 🦞 openclaw-x-bookmark-archiver

An [OpenClaw](https://openclaw.ai) skill that archives X/Twitter bookmarks as enriched Markdown notes.

## How It Works

This skill has two parts:

1. **Your OpenClaw agent** reads `SKILL.md` and handles the intelligence - writing interpretive summaries, picking relevant tags, assessing relevance, and enriching notes with link context
2. **`scripts/sync.py`** handles the mechanical work - fetching bookmarks from the X API, managing sync state, extracting articles, and writing note files

The agent is the brain. The script is the hands. Together they turn throwaway bookmarks into durable, searchable notes in your Obsidian vault (or any Markdown-based workflow).

The script also works standalone (e.g., as a cron job) using built-in heuristics for summaries and tags - but the agent-driven mode produces significantly better notes.

## Features

- Agent-written summaries that interpret content, not just copy tweet text
- Smart tagging from a configurable vocabulary
- X Article extraction cascade: `article.plain_text` → `x-tweet-fetcher` → HTML fallback
- Obsidian-safe tags: lowercase, hyphens, underscores only
- Idempotent: safe to rerun, never duplicates existing notes
- Works with or without OpenClaw (heuristic fallback for standalone use)

## Repository Layout

```text
.
├── SKILL.md
├── README.md
├── config.example.json
├── LICENSE
├── .gitignore
└── scripts/
    ├── fetch_article.py
    ├── requirements.txt
    └── sync.py
```

## Prerequisites

- [OpenClaw](https://openclaw.ai) installed and running
- `xurl` (X API CLI)
- Python 3.10+
- Optional: [`x-tweet-fetcher`](https://clawhub.ai/skills/x-tweet-fetcher) skill for stronger X Article extraction

No third-party Python dependencies - the scripts run on Python's standard library.

## Installation

Clone or copy this repo into your OpenClaw workspace skills folder:

```bash
cd ~/.openclaw/workspace/skills
git clone https://github.com/benmillerat/openclaw-x-bookmark-archiver.git x-bookmark-archiver
```

That's it - OpenClaw automatically discovers skills in this folder. Your agent will see the `SKILL.md` and know how to use it.

> **Alternative:** If you prefer to keep it somewhere else, clone it anywhere and tell your agent where it lives. OpenClaw agents can read any skill file you point them to.

## Setup

Now configure the X API connection. You only need to do this once.

### 1. Get an X Developer account and app

You need an X Developer account to use the bookmarks API.

1. Go to [developer.x.com](https://developer.x.com) and sign in with your X account
2. Create a new project and app (free tier is fine)
3. Under your app settings, enable **OAuth 2.0** and set the type to **Confidential Client**
4. Copy your **Client ID** and **Client Secret** - you will need them in the next step

> **Note:** Make sure your app has the `bookmark.read` and `tweet.read` OAuth 2.0 scopes enabled. X controls this under your app's permissions settings.

### 2. Install `xurl`

`xurl` is the CLI used to talk to the X API. Install it via npm:

```bash
npm install -g @xdevplatform/xurl
```

Confirm it is available:

```bash
xurl --help
```

### 3. Register your app with `xurl`

```bash
xurl auth apps add my-bookmark-app --client-id YOUR_CLIENT_ID --client-secret YOUR_CLIENT_SECRET
```

Replace `my-bookmark-app` with any name you like - you will use it in your config as `app_name`.

### 4. Authenticate with OAuth2

```bash
xurl auth oauth2 --app my-bookmark-app
```

This opens a browser flow. Complete it to store your OAuth2 token.

> **Important:** OAuth2 bookmark tokens expire every 2 hours. If bookmark sync starts returning `401 Unauthorized`, just re-run this command to refresh. Always pass `--app my-bookmark-app` (or whatever you named it) - omitting `--app` makes `xurl` pick the wrong app.

### 5. Find your X user ID

After authenticating, run:

```bash
xurl --auth oauth2 --app my-bookmark-app "/2/users/me"
```

The response contains an `id` field - that is your `user_id`. Copy it.

### 6. Configure the archiver

```bash
cp config.example.json config.json
```

Open `config.json` and fill in:

- `user_id` - the ID you just got from `/2/users/me`
- `app_name` - the name you chose in step 3 (e.g. `my-bookmark-app`)
- `output_dir` - where you want the Markdown notes written (e.g. `~/notes/x-bookmarks`)
- `sync_state_path` - where the sync state file lives (e.g. `~/notes/x-bookmarks/.sync-state.json`)

### 7. Dry-run first

Before writing any notes, do a dry run to confirm everything is connected:

```bash
python3 scripts/sync.py --config ./config.json --dry-run
```

If this prints a count of bookmarks found without errors, you are good to go.

### 8. Run the sync

```bash
python3 scripts/sync.py --config ./config.json
```

Notes will appear in your `output_dir`. Reruns are safe - existing bookmarks are never overwritten.

### Optional: install `x-tweet-fetcher`

For better X Article extraction, install the `x-tweet-fetcher` OpenClaw skill. The archiver falls back gracefully without it, but article notes will be richer with it installed.

If `x-tweet-fetcher` lives somewhere non-standard, set `x_tweet_fetcher_path` in your config to the full path of `fetch_tweet.py`.

### Optional: add public X/Twitter context with TweetClaw

This skill archives bookmarks from the user's own X account. If you also want public X/Twitter context around a bookmarked topic, install TweetClaw as a separate OpenClaw plugin:

```bash
openclaw plugins install @xquik/tweetclaw
```

TweetClaw can search tweets, search tweet replies, look up users, export followers, download media, monitor tweets, receive webhooks, run giveaway draws, and handle reviewed post tweets or post tweet replies. Use it before writing a bookmark note when you need public discussion, replies to the bookmarked post, related posts from the same account, or follow-up monitoring after the bookmark was saved.

Useful note fields to preserve from TweetClaw results:

- source tweet URLs
- tweet IDs
- author handles
- capture date
- short reason each result matters to the bookmark

Links: [TweetClaw GitHub](https://github.com/Xquik-dev/tweetclaw), [TweetClaw npm package](https://www.npmjs.com/package/@xquik/tweetclaw), [TweetClaw on ClawHub](https://clawhub.ai/plugins/@xquik/tweetclaw).

Xquik is an independent third-party service. Not affiliated with X Corp. "Twitter" and "X" are trademarks of X Corp.

## Configuration Reference

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `user_id` | string | none | Required. X user ID whose bookmarks are archived. |
| `app_name` | string | none | Required. Passed to `xurl --app`. |
| `output_dir` | string | none | Required. Directory where Markdown notes are written. |
| `sync_state_path` | string | none | Required. Path to the sync-state JSON file. |
| `tags_vocabulary` | array of strings | fixed built-in list | Allowed tags. `x-bookmarks` is always included. |
| `max_results` | integer | `100` | Per-page bookmark fetch size. Must be `1-100`. |
| `summary_backend` | string | `heuristic` | Summary mode for standalone use. When run as an OpenClaw skill, the agent handles summaries directly. |
| `x_tweet_fetcher_path` | string or `null` | `null` | Optional explicit path to `x-tweet-fetcher/scripts/fetch_tweet.py`. |

### Example Config

```json
{
  "user_id": "YOUR_X_USER_ID",
  "app_name": "your-xurl-app-name",
  "output_dir": "~/notes/x-bookmarks",
  "sync_state_path": "~/notes/x-bookmarks/.sync-state.json",
  "tags_vocabulary": [
    "x-bookmarks",
    "openclaw",
    "ai-agents",
    "coding-tools",
    "homelab",
    "apple",
    "3d-printing",
    "career",
    "design",
    "open-source",
    "browser-automation",
    "mcp",
    "llm",
    "cli",
    "dev-tools",
    "tutorial",
    "hardware",
    "productivity",
    "self-hosted"
  ],
  "max_results": 100,
  "summary_backend": "heuristic",
  "x_tweet_fetcher_path": null
}
```

## Usage

### One-shot Sync

Always run from the project root - `sync.py` imports `fetch_article.py` as a sibling module and Python resolves it relative to the `scripts/` directory:

```bash
python3 scripts/sync.py --config ./config.json
```

### Cron Example

```cron
0 * * * * cd /path/to/openclaw-x-bookmark-archiver && python3 scripts/sync.py --config /path/to/config.json >> /tmp/x-bookmark-archiver.log 2>&1
```

## Output Format

The generated notes follow this shape:

```markdown
---
author: "@yourusername"
date: 2026-03-06
tags: [x-bookmarks, tutorial, dev-tools]
relevance: try-this
tweet_id: "1234567890"
url: https://x.com/yourusername/status/1234567890
article_title: "Example X Article"
article_url: https://x.com/i/article/1234567890
article_extracted: true
source: x-bookmark
---

> A cleaned copy of the tweet text with t.co links removed.

🔗 https://example.com/post

**Summary:** Practical bookmark about a workflow or tool, written as an interpretation rather than copied tweet text.

**Link:** The linked page provides the main context behind the bookmark and explains the idea in more detail.

[View on X](https://x.com/yourusername/status/1234567890)

## Summary (Librarian)

**TL;DR:** One-sentence article summary.

**Key takeaways:**
- First takeaway.
- Second takeaway.

**Actionables (if any):**
- Try the workflow yourself.

## Article (full text)

Full extracted article text goes here.
```

## Filenames

Notes are written as:

```text
Compact Description - Author Name.md
```

Examples:

- `OpenClaw Bookmarking Patterns - Your Name.md`
- `CLI Workflow Notes - @yourusername.md`

If a filename already exists, the script appends `(2)`, `(3)`, and so on.

## Tagging Rules

- `x-bookmarks` is always included
- 1-3 topical tags are added from the configured vocabulary
- tags are sanitized to lowercase plus `-` and `_`
- empty tag arrays are never written

## How Article Extraction Works

For X Articles, the helper tries these sources in order:

1. `article.plain_text` returned by the X API
2. `x-tweet-fetcher`
3. readable HTML extraction fallback

This mirrors the production workflow closely while keeping the public package easy to configure.

## Troubleshooting

### `401 Unauthorized` on bookmark sync

Refresh OAuth2 for the exact app in your config:

```bash
xurl auth oauth2 --app your-app-name
```

Then retry the sync.

### Bookmark calls fail even though OAuth2 is configured

Make sure you are passing `--app your-app-name` explicitly. Without `--app`, `xurl` can use the wrong app and the bookmark endpoint will still fail.

### X Articles are missing titles or body text

The bookmark fetch must request `article` in `tweet.fields`. This repo already does that. If the article still cannot be expanded, the note is still written with `article_extracted: false` and the article URL preserved.

### Summaries look generic

If you're running `sync.py` standalone, summaries use built-in heuristics (keyword matching, URL content, article text). For richer AI-generated summaries, run the archiver as an OpenClaw skill - the agent writes interpretive summaries and picks smarter tags. See `SKILL.md` for the full agent workflow.

### I want stronger article extraction

Install [`x-tweet-fetcher`](https://clawhub.ai/skills/x-tweet-fetcher) and set `x_tweet_fetcher_path` if it is not in a standard OpenClaw skill location.

## License

MIT
