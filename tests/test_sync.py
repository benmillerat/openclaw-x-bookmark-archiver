from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPTS_DIRECTORY = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIRECTORY))

from sync import SyncState, write_sync_state


class WriteSyncStateTests(unittest.TestCase):
    def test_replaces_state_without_leaving_temporary_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"

            write_sync_state(
                state_path,
                SyncState(last_id="123", last_sync="2026-07-18T00:00:00Z"),
            )

            self.assertEqual(
                json.loads(state_path.read_text(encoding="utf-8")),
                {"last_id": "123", "last_sync": "2026-07-18T00:00:00Z"},
            )
            self.assertEqual(list(Path(directory).glob(".state.json.*.tmp")), [])

    def test_failed_replace_preserves_existing_state_and_cleans_temporary_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            original = '{"last_id":"old"}\n'
            state_path.write_text(original, encoding="utf-8")

            with patch("sync.os.replace", side_effect=OSError("replace failed")):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    write_sync_state(state_path, SyncState(last_id="new"))

            self.assertEqual(state_path.read_text(encoding="utf-8"), original)
            self.assertEqual(list(Path(directory).glob(".state.json.*.tmp")), [])

    def test_failed_fsync_cleans_temporary_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"

            with patch("sync.os.fsync", side_effect=OSError("fsync failed")):
                with self.assertRaisesRegex(OSError, "fsync failed"):
                    write_sync_state(state_path, SyncState(last_id="new"))

            self.assertFalse(state_path.exists())
            self.assertEqual(list(Path(directory).glob(".state.json.*.tmp")), [])

    def test_replacement_preserves_existing_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state_path.write_text('{"last_id":"old"}\n', encoding="utf-8")
            state_path.chmod(0o640)

            write_sync_state(state_path, SyncState(last_id="new"))

            self.assertEqual(state_path.stat().st_mode & 0o777, 0o640)

    def test_replacement_refreshes_modification_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state_path.write_text('{"last_id":"old"}\n', encoding="utf-8")
            old_timestamp = 1_600_000_000
            os.utime(state_path, (old_timestamp, old_timestamp))

            write_sync_state(state_path, SyncState(last_id="new"))

            self.assertGreater(state_path.stat().st_mtime, old_timestamp)

    @unittest.skipIf(os.name == "nt", "ownership is not available on Windows")
    def test_replacement_tolerates_ownership_permission_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state_path.write_text('{"last_id":"old"}\n', encoding="utf-8")

            with patch("sync.os.chown", side_effect=PermissionError("not owner")):
                write_sync_state(state_path, SyncState(last_id="new"))

            self.assertEqual(json.loads(state_path.read_text(encoding="utf-8"))["last_id"], "new")

    @unittest.skipIf(os.name == "nt", "symbolic links require elevated privileges on Windows")
    def test_replacement_preserves_state_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target_path = Path(directory) / "managed-state.json"
            target_path.write_text('{"last_id":"old"}\n', encoding="utf-8")
            state_path = Path(directory) / "state.json"
            state_path.symlink_to(target_path.name)

            write_sync_state(state_path, SyncState(last_id="new", last_sync="2026-07-18T00:00:00Z"))

            self.assertTrue(state_path.is_symlink())
            self.assertEqual(
                json.loads(target_path.read_text(encoding="utf-8")),
                {"last_id": "new", "last_sync": "2026-07-18T00:00:00Z"},
            )

    @unittest.skipIf(os.name == "nt", "symbolic links require elevated privileges on Windows")
    def test_first_write_creates_missing_symlink_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target_path = Path(directory) / "managed-state.json"
            state_path = Path(directory) / "state.json"
            state_path.symlink_to(target_path.name)

            write_sync_state(state_path, SyncState(last_id="first", last_sync="2026-07-18T00:00:00Z"))

            self.assertTrue(state_path.is_symlink())
            self.assertEqual(
                json.loads(target_path.read_text(encoding="utf-8")),
                {"last_id": "first", "last_sync": "2026-07-18T00:00:00Z"},
            )


if __name__ == "__main__":
    unittest.main()
