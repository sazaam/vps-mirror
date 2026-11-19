#!/usr/bin/env python3
"""Tests for the thin ssh/scp remote driver."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "vpsclone"
_loader = importlib.machinery.SourceFileLoader("vpsclone", str(MODULE_PATH))
_spec = importlib.util.spec_from_loader("vpsclone", _loader)
vpsclone = importlib.util.module_from_spec(_spec)
_loader.exec_module(vpsclone)


class RemoteDriverTests(unittest.TestCase):
    def test_ssh_argv_forces_tty_and_keeps_port_explicit(self):
        argv = vpsclone.remote_ssh_argv("saz@new-vps", 2222, "echo hi", tty=True)
        self.assertEqual(argv[:2], ["ssh", "-p"])
        self.assertIn("2222", argv)
        self.assertIn("-tt", argv)
        self.assertEqual(argv[-2:], ["saz@new-vps", "echo hi"])

    def test_scp_argv_uses_target_addressing(self):
        argv = vpsclone.remote_scp_argv(
            "saz@new-vps", 22, Path("/tmp/b.tar.gz"), "/tmp/x/b.tar.gz")
        self.assertEqual(argv[:2], ["scp", "-P"])
        self.assertEqual(argv[-1], "saz@new-vps:/tmp/x/b.tar.gz")


if __name__ == "__main__":
    unittest.main()
