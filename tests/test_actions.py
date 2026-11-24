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
        self.assertEqual(ids, [
            "provider_snapshot", "toolchain", "node_deps", "cargo_deps",
            "github_deploy_key", "data_paths", "allow_symlinks",
            "github_key_check", "ssh_prepare", "fresh_login", "ssh_commit",
            "data_destination", "data_sync_dry", "data_sync_live",
            "vault_unpack", "save_session",
        ])
        for a in actions:
            self.assertIn(a["kind"],
                          {"acknowledge", "prompt_value", "prompt_bool",
                           "guided_subprocess", "toolchain", "project_deps",
                           "save_session"})

    def test_set_manifest_value_splits_data_paths(self):
        m = {"data": {"paths": []}}
        ok = vpsclone._set_manifest_value(
            m, "data.paths", "/home/saz/data, /srv/backup,,/var/lib/x")
        self.assertTrue(ok)
        self.assertEqual(m["data"]["paths"],
                         ["/home/saz/data", "/srv/backup", "/var/lib/x"])

    def test_set_manifest_value_stores_boolean(self):
        m = {"policy": {"allow_symlinks": False}}
        ok = vpsclone._set_manifest_value(m, "policy.allow_symlinks", True)
        self.assertTrue(ok)
        self.assertIs(m["policy"]["allow_symlinks"], True)

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

    def test_new_guided_command_ids_are_fixed(self):
        self.assertEqual(
            vpsclone._action_argv({"command_id": "github_ssh"})[-1],
            "git@github.com",
        )
        m = {"data": {"destination": "saz@new-vps:/srv/data",
                      "paths": ["~/Music", "/srv/notes"]}}
        argv = vpsclone._action_argv({"command_id": "sync_data",
                                      "dry_run": True}, m)
        self.assertEqual(argv[-2:],
                         ["--destination", "saz@new-vps:/srv/data"])
        self.assertIn("--path", argv)
        self.assertIn("~/Music", argv)
        self.assertIn("--dry-run",
                      vpsclone._action_argv({"command_id": "sync_data",
                                             "dry_run": True}, m))
        self.assertIsNone(
            vpsclone._action_argv({"command_id": "sync_data"},
                                  {"data": {"destination": "rm -rf /"}}))

    def test_ssh_cutover_command_ids_are_fixed(self):
        self.assertEqual(
            vpsclone._action_argv({"command_id": "ssh_cutover_prepare",
                                   "rollback_seconds": 600})[-2:],
            ["--rollback-seconds", "600"],
        )
        self.assertEqual(
            vpsclone._action_argv({"command_id": "ssh_cutover_commit"})[-2:],
            ["ssh-cutover-commit", "--confirm-login"],
        )
        self.assertEqual(
            vpsclone._action_argv({"command_id": "ssh_cutover_rollback"})[-1],
            "ssh-cutover-rollback",
        )

    def test_user_key_actions_for_target_added_users(self):
        m = {"users": [
            {"name": "alice", "home": "/home/alice", "authorized_keys": "",
             "authorized_keys_inline": ""},
            {"name": "bob", "home": "/home/bob", "authorized_keys": "ssh/bob.pub",
             "authorized_keys_inline": ""},
        ]}
        actions = vpsclone.user_key_actions(m)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["id"], "user_key_0_alice")
        self.assertEqual(actions[0]["target"], "users.0.authorized_keys_inline")


if __name__ == "__main__":
    unittest.main()
