#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from html import unescape
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0.0.0 Safari/537.36 x-bookmark-archiver/1.0"
)


@dataclass(slots=True)
class FetchResult:
    ok: bool
    source: str
    url: str
    title: str | None = None
    content: str | None = None
    error: str | None = None


@dataclass(slots=True)
class ArticleExtraction:
    ok: bool
    source: str
    article_url: str
    title: str | None = None
    full_text: str | None = None
    word_count: int | None = None
    error: str | None = None


def normalize_whitespace(text: str) -> str:
    lines: list[str] = []
    blank_pending = False
    for raw_line in unescape(text).replace("\r\n", "\n").split("\n"):
        line = " ".join(raw_line.split()).strip()
        if not line:
            if lines:
                blank_pending = True
            continue
        if blank_pending and lines:
            lines.append("")
        blank_pending = False
        lines.append(line)
    return "\n".join(lines).strip()


def strip_tags(html_text: str) -> str:
    return re.sub(r"<[^>]+>", " ", html_text, flags=re.IGNORECASE)


def detect_title(html_text: str) -> str | None:
    patterns = [
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+name=["\']twitter:title["\'][^>]+content=["\']([^"\']+)["\']',
        r"<title[^>]*>(.*?)</title>",
        r"<h1[^>]*>(.*?)</h1>",
    ]
    for pattern in patterns:
        match = re.search(pattern, html_text, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            continue
        value = normalize_whitespace(strip_tags(match.group(1)))
        if value:
            return value
    return None


def remove_noise_blocks(html_text: str) -> str:
    patterns = [
        r"<script\b[^>]*>.*?</script>",
        r"<style\b[^>]*>.*?</style>",
        r"<noscript\b[^>]*>.*?</noscript>",
        r"<svg\b[^>]*>.*?</svg>",
        r"<canvas\b[^>]*>.*?</canvas>",
        r"<iframe\b[^>]*>.*?</iframe>",
        r"<nav\b[^>]*>.*?</nav>",
        r"<header\b[^>]*>.*?</header>",
        r"<footer\b[^>]*>.*?</footer>",
        r"<aside\b[^>]*>.*?</aside>",
        r"<form\b[^>]*>.*?</form>",
    ]
    cleaned = html_text
    for pattern in patterns:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE | re.DOTALL)
    return cleaned


def extract_main_text(html_text: str) -> tuple[str | None, str]:
    cleaned = remove_noise_blocks(html_text)
    title = detect_title(cleaned)

    body_match = re.search(r"<body[^>]*>(.*)</body>", cleaned, flags=re.IGNORECASE | re.DOTALL)
    candidate = body_match.group(1) if body_match else cleaned

    for tag_name in ("article", "main"):
        tag_match = re.search(
            rf"<{tag_name}[^>]*>(.*)</{tag_name}>",
            candidate,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if tag_match:
            candidate = tag_match.group(1)
            break

    candidate = re.sub(r"(?i)<br\s*/?>", "\n", candidate)
    candidate = re.sub(
        r"(?i)</(p|div|section|article|main|li|ul|ol|h1|h2|h3|h4|h5|h6|tr|table)>",
        "\n",
        candidate,
    )
    candidate = re.sub(r"(?i)<li[^>]*>", "\n- ", candidate)
    text = normalize_whitespace(strip_tags(candidate))
    return title, text


def fetch_readable_url(
    url: str,
    *,
    timeout_seconds: int = 20,
    max_chars: int = 16_000,
) -> FetchResult:
    request = Request(
        url,
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            content_type = (response.headers.get("content-type") or "").lower()
            charset = response.headers.get_content_charset() or "utf-8"
            payload = response.read().decode(charset, errors="replace")
    except HTTPError as exc:
        return FetchResult(ok=False, source="web_fetch_fallback", url=url, error=f"HTTP {exc.code}: {exc.reason}")
    except URLError as exc:
        return FetchResult(ok=False, source="web_fetch_fallback", url=url, error=str(exc.reason))
    except OSError as exc:
        return FetchResult(ok=False, source="web_fetch_fallback", url=url, error=str(exc))

    title: str | None = None
    if "html" in content_type or not content_type:
        title, content = extract_main_text(payload)
    elif content_type.startswith("text/") or "json" in content_type or "xml" in content_type:
        content = normalize_whitespace(payload)
    else:
        return FetchResult(
            ok=False,
            source="web_fetch_fallback",
            url=url,
            error=f"Unsupported content type: {content_type}",
        )

    if not content:
        return FetchResult(
            ok=False,
            source="web_fetch_fallback",
            url=url,
            title=title,
            error="No readable content extracted",
        )

    return FetchResult(
        ok=True,
        source="web_fetch_fallback",
        url=url,
        title=title,
        content=content[:max_chars].strip(),
    )


def candidate_fetcher_paths(explicit: Path | None = None) -> list[Path]:
    candidates: list[Path] = []
    if explicit:
        candidates.append(explicit)

    for env_name in ("X_TWEET_FETCHER_PATH", "X_TWEET_FETCHER_ROOT"):
        raw = os.getenv(env_name)
        if not raw:
            continue
        path = Path(raw).expanduser()
        candidates.append(path / "scripts" / "fetch_tweet.py" if path.is_dir() else path)

    home = Path.home()
    candidates.extend(
        [
            home / ".openclaw" / "workspace" / "skills" / "x-tweet-fetcher" / "scripts" / "fetch_tweet.py",
            home / ".openclaw" / "skills" / "x-tweet-fetcher" / "scripts" / "fetch_tweet.py",
            home / ".codex" / "skills" / "x-tweet-fetcher" / "scripts" / "fetch_tweet.py",
        ]
    )
    return candidates


def discover_x_tweet_fetcher(explicit: Path | None = None) -> Path | None:
    for path in candidate_fetcher_paths(explicit):
        if path.is_file():
            return path
    return None


def run_x_tweet_fetcher(fetcher_path: Path, url: str, timeout_seconds: int = 45) -> ArticleExtraction:
    command = [sys.executable or "python3", str(fetcher_path), "--url", url]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return ArticleExtraction(ok=False, source="x_tweet_fetcher", article_url=url, error=str(exc))

    if completed.returncode != 0:
        error = completed.stderr.strip() or completed.stdout.strip() or f"Exit code {completed.returncode}"
        return ArticleExtraction(ok=False, source="x_tweet_fetcher", article_url=url, error=error)

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return ArticleExtraction(
            ok=False,
            source="x_tweet_fetcher",
            article_url=url,
            error=f"Invalid JSON from x-tweet-fetcher: {exc}",
        )

    tweet = payload.get("tweet") or {}
    article = tweet.get("article") or {}
    full_text = normalize_whitespace(article.get("full_text") or "")
    title = normalize_whitespace(article.get("title") or "") or None
    if not full_text:
        return ArticleExtraction(
            ok=False,
            source="x_tweet_fetcher",
            article_url=url,
            title=title,
            error="x-tweet-fetcher returned no article text",
        )

    return ArticleExtraction(
        ok=True,
        source="x_tweet_fetcher",
        article_url=url,
        title=title,
        full_text=full_text,
        word_count=len(full_text.split()),
    )


def extract_article(
    article_url: str,
    *,
    article_title: str | None = None,
    plain_text: str | None = None,
    x_tweet_fetcher_path: Path | None = None,
    timeout_seconds: int = 20,
) -> ArticleExtraction:
    normalized_title = normalize_whitespace(article_title or "") or None
    normalized_plain_text = normalize_whitespace(plain_text or "")
    if normalized_plain_text:
        return ArticleExtraction(
            ok=True,
            source="api_plain_text",
            article_url=article_url,
            title=normalized_title,
            full_text=normalized_plain_text,
            word_count=len(normalized_plain_text.split()),
        )

    fetcher = discover_x_tweet_fetcher(x_tweet_fetcher_path)
    if fetcher:
        fetched = run_x_tweet_fetcher(fetcher, article_url)
        if fetched.ok:
            if normalized_title and not fetched.title:
                fetched.title = normalized_title
            return fetched

    web_result = fetch_readable_url(article_url, timeout_seconds=timeout_seconds)
    if web_result.ok and web_result.content:
        return ArticleExtraction(
            ok=True,
            source=web_result.source,
            article_url=article_url,
            title=normalized_title or web_result.title,
            full_text=web_result.content,
            word_count=len(web_result.content.split()),
        )

    return ArticleExtraction(
        ok=False,
        source="web_fetch_fallback",
        article_url=article_url,
        title=normalized_title,
        error=web_result.error or "No article content extracted",
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract full text for X Articles.")
    parser.add_argument("--article-url", required=True, help="Full https://x.com/i/article/... URL")
    parser.add_argument("--article-title", help="Optional article title from the X API")
    parser.add_argument("--plain-text", help="Optional plain_text field from the X API")
    parser.add_argument(
        "--x-tweet-fetcher-path",
        help="Optional path to x-tweet-fetcher/scripts/fetch_tweet.py",
    )
    parser.add_argument("--text-only", action="store_true", help="Print full article text only")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    extraction = extract_article(
        args.article_url,
        article_title=args.article_title,
        plain_text=args.plain_text,
        x_tweet_fetcher_path=Path(args.x_tweet_fetcher_path).expanduser()
        if args.x_tweet_fetcher_path
        else None,
    )

    if args.text_only:
        if not extraction.ok or not extraction.full_text:
            print(extraction.error or "Unable to extract article text", file=sys.stderr)
            return 1
        print(extraction.full_text)
        return 0

    dump_kwargs = {"ensure_ascii": False}
    if args.pretty:
        dump_kwargs["indent"] = 2
    print(json.dumps(asdict(extraction), **dump_kwargs))
    return 0 if extraction.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
