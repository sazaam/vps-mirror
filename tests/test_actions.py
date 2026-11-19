#!/usr/bin/env python3
"""Tests for the guided-action registry and in-memory value setter."""

from __future__ import annotations

import contextlib
import importlib.machinery
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "vpsclone"
_loader = importlib.machinery.SourceFileLoader("vpsclone", str(MODULE_PATH))
_spec = importlib.util.spec_from_loader("vpsclone", _loader)
vpsclone = importlib.util.module_from_spec(_spec)
_loader.exec_module(vpsclone)


class ActionTests(unittest.TestCase):
    def test_default_actions_are_declared(self):
        actions = vpsclone.default_action_defs()
        ids = [a["id"] for a in actions]
        self.assertEqual(ids, ["provider_snapshot", "github_deploy_key",
                               "data_paths", "vault_unpack", "save_session"])
        for a in actions:
            self.assertIn(a["kind"],
                          {"acknowledge", "prompt_value", "guided_subprocess",
                           "save_session"})

    def test_set_manifest_value_splits_data_paths(self):
        m = {"data": {"paths": []}}
        ok = vpsclone._set_manifest_value(
            m, "data.paths", "/home/saz/data, /srv/backup,,/var/lib/x")
        self.assertTrue(ok)
        self.assertEqual(m["data"]["paths"],
                         ["/home/saz/data", "/srv/backup", "/var/lib/x"])

    def test_set_manifest_value_rejects_bad_target(self):
        m = {"data": {"paths": []}}
        self.assertFalse(vpsclone._set_manifest_value(m, "nope", "x"))
        self.assertFalse(vpsclone._set_manifest_value(m, "data.missing.deep", "x"))

    def test_action_argv_uses_fixed_registry(self):
        argv = vpsclone._action_argv({"command_id": "keygen", "name": "my-key"})
        self.assertIsNotNone(argv)
        self.assertIn("keygen", argv)
        self.assertIn("--name", argv)
        self.assertIn("my-key", argv)
        self.assertIsNone(vpsclone._action_argv({"command_id": "rm -rf /"}))

    def test_binary_install_actions(self):
        data = {"binaries": [
            {"name": "herdr", "path": "~/.local/bin/herdr", "install": ""},
            {"name": "already.ready", "path": "~/.local/bin/x",
             "install": "curl -fsSL https://example.install | bash"},
        ]}
        actions = vpsclone.binary_install_actions(data)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["id"], "binary_install_0_herdr")
        self.assertEqual(actions[0]["target"], "binaries.0.install")
        self.assertEqual(actions[0]["kind"], "prompt_value")
        self.assertEqual(actions[0]["check_task"], "apps")

    def test_set_manifest_value_writes_listed_binary_install(self):
        m = {"binaries": [{"name": "herdr", "install": ""}]}
        ok = vpsclone._set_manifest_value(
            m, "binaries.0.install", "curl -fsSL https://example.install | bash")
        self.assertTrue(ok)
        self.assertEqual(m["binaries"][0]["install"],
                         "curl -fsSL https://example.install | bash")

    def test_tui_apply_uses_in_memory_manifest(self):
        m = {
            "target": {"user": "saz", "home": "/home/saz", "hostname": "vagabond"},
            "binaries": [{"name": "herdr", "path": "~/.local/bin/not-present-xyz",
                          "install": "curl -fsSL https://example.install | bash"}],
        }
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc, manual = vpsclone._tui_dispatch("apply --only=binaries", m, True)
        self.assertEqual(rc, 0)
        self.assertFalse(manual)
        self.assertIn("would run install command for herdr", buf.getvalue())

    def test_secret_detection_finds_paths_not_values(self):
        m = {"binaries": [
            {"name": "ok", "install": "curl -fsSL https://example.install | bash"},
            {"name": "bad", "install": "curl -H 'Authorization: ghp_abcdefghijklmnopqrstuvwxyz' x"},
        ]}
        hits = vpsclone._find_secret_paths(m)
        self.assertEqual(hits, ["manifest.binaries[1].install"])

    def test_persist_session_writes_0600_and_refuses_secrets(self):
        original = vpsclone.MANIFEST
        with tempfile.TemporaryDirectory() as td:
            vpsclone.MANIFEST = Path(td) / "manifest.toml"
            try:
                ok, note = vpsclone._persist_session({"target": {"hostname": "x"}})
                self.assertTrue(ok)
                self.assertIn("0600", note)
                self.assertEqual(vpsclone.MANIFEST.stat().st_mode & 0o777, 0o600)

                ok, note = vpsclone._persist_session(
                    {"binaries": [{"install": "token=ghp_abcdefghijklmnopqrstuvwxyz"}]})
                self.assertFalse(ok)
                self.assertIn("refused", note)
            finally:
                vpsclone.MANIFEST = original


if __name__ == "__main__":
    unittest.main()
