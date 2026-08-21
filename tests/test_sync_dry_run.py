from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import sync  # noqa: E402  (the script directory is added above)


class DryRunTests(unittest.TestCase):
    def test_dry_run_skips_link_article_and_agent_fetches(self) -> None:
        """Dry-run may query X, but it must not contact bookmark destinations."""

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            config = sync.Config(
                user_id="123",
                app_name="test-app",
                output_dir=root / "notes",
                sync_state_path=root / "state.json",
                tags_vocabulary=["x-bookmarks", "productivity"],
                summary_backend="auto",
            )
            bookmark = sync.Bookmark(
                tweet_id="999",
                created_at="2026-08-21T12:00:00Z",
                username="author",
                display_name="Author",
                text="A saved link",
                tweet_url="https://x.com/author/status/999",
                note_urls=["https://public.example/article"],
                external_urls=["https://public.example/article"],
                article_url="https://x.com/i/article/999",
                article_title="Example",
            )

            with (
                mock.patch.object(sync, "extract_article") as extract_article,
                mock.patch.object(sync, "fetch_link_contexts") as fetch_links,
                mock.patch.object(sync, "generate_content") as generate_content,
            ):
                destination = sync.process_bookmark(
                    bookmark,
                    config,
                    config.output_dir,
                    existing_notes={},
                    dry_run=True,
                )

            self.assertIsNotNone(destination)
            extract_article.assert_not_called()
            fetch_links.assert_not_called()
            generate_content.assert_not_called()
            self.assertFalse(config.output_dir.exists())


if __name__ == "__main__":
    unittest.main()
