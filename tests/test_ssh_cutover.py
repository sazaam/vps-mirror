#!/usr/bin/env python3
"""Tests for the two-phase SSH cutover state helpers."""

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


class SshCutoverTests(unittest.TestCase):
    def test_valid_port(self):
        self.assertTrue(vpsclone._valid_port("22"))
        self.assertTrue(vpsclone._valid_port("65535"))
        self.assertFalse(vpsclone._valid_port("0"))
        self.assertFalse(vpsclone._valid_port("70000"))
        self.assertFalse(vpsclone._valid_port("-1"))

    def test_state_roundtrip_is_0600_and_survives_garbage(self):
        original = vpsclone.CUTOVER_STATE
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ssh-cutover.json"
            vpsclone.CUTOVER_STATE = path
            try:
                self.assertIsNone(vpsclone._load_cutover())
                vpsclone._save_cutover({"old_port": "22", "new_port": "2022",
                                        "prepared_at": "now"})
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(vpsclone._load_cutover()["new_port"], "2022")
                path.write_text("not json", encoding="utf-8")
                self.assertIsNone(vpsclone._load_cutover())
            finally:
                vpsclone.CUTOVER_STATE = original


if __name__ == "__main__":
    unittest.main()
