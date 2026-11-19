#!/usr/bin/env python3
"""Tests for content-level secret quarantine at capture time.

Run with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "vpsclone"
_loader = importlib.machinery.SourceFileLoader("vpsclone", str(MODULE_PATH))
_spec = importlib.util.spec_from_loader("vpsclone", _loader)
vpsclone = importlib.util.module_from_spec(_spec)
_loader.exec_module(vpsclone)


class CaptureSecretTests(unittest.TestCase):
    def test_content_scan_flags_tokens_but_not_plain_config(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "cli.json"
            src.write_text('{"model": "fast"}', encoding="utf-8")
            self.assertEqual(vpsclone.content_secret_hits(src, ".config/x.json"), [])

            src.write_text('token = "ghp_abcdefghijklmnopqrstuvwxyz"',
                           encoding="utf-8")
            hits = vpsclone.content_secret_hits(src, ".config/x.json")
            self.assertTrue(hits)
            self.assertTrue(any("token" in h or "gh[pousr]" in h for h in hits))

    def test_capture_copy_quarantines_suspicious_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "src" / "cli.json"
            src.parent.mkdir()
            src.write_text('password = "hunter2"\n', encoding="utf-8")
            dst = root / "bundle" / "cli.json"
            copied, skipped = [], []

            ok = vpsclone.capture_copy(
                src, ".config/opencode/cli.json", dst, [], copied, skipped)

            self.assertFalse(ok)
            self.assertFalse(dst.exists())
            self.assertEqual(copied, [])
            self.assertTrue(skipped[0][1].startswith("content secret"))

    def test_capture_allow_releases_false_positive(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "src" / "config.toml"
            src.parent.mkdir()
            src.write_text('password = "not-a-secret"\n', encoding="utf-8")
            dst = root / "bundle" / "config.toml"
            allow = root / "capture-allow.txt"
            allow.write_text("# comment\n.config/herdr/config.toml\n",
                             encoding="utf-8")
            original = vpsclone.CAPTURE_ALLOW
            vpsclone.CAPTURE_ALLOW = allow
            copied, skipped = [], []
            try:
                ok = vpsclone.capture_copy(
                    src, ".config/herdr/config.toml", dst, [], copied, skipped)
            finally:
                vpsclone.CAPTURE_ALLOW = original

            self.assertTrue(ok)
            self.assertTrue(dst.exists())
            self.assertEqual(skipped, [])
            self.assertIn("allowed by capture-allow.txt", copied[0])


if __name__ == "__main__":
    unittest.main()
