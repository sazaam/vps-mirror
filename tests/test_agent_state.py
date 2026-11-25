#!/usr/bin/env python3
"""Tests for curated agent config and the opt-in agent-state snapshot."""

from __future__ import annotations

import contextlib
import importlib.machinery
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).resolve().parents[1] / "vpsclone"
_loader = importlib.machinery.SourceFileLoader("vpsclone", str(MODULE_PATH))
_spec = importlib.util.spec_from_loader("vpsclone", _loader)
vpsclone = importlib.util.module_from_spec(_spec)
_loader.exec_module(vpsclone)


class AgentSnapshotTests(unittest.TestCase):
    def test_config_defaults_to_opt_in(self):
        cfg = vpsclone.normalize_agent_state(None)
        self.assertFalse(cfg["enable"])
        self.assertEqual(cfg["paths"], ["~/.local/state/opencode"])
        self.assertEqual(cfg["files"], {})

    def test_snapshot_stages_state_files_and_honours_denylist(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            data = Path(td) / "data"
            state = home / ".local/state/opencode"
            state.mkdir(parents=True)
            data.mkdir()
            (state / "model.json").write_text('{"model":"test"}')
            (state / "service.json").write_text('{"token":"do-not-ship"}')

            cfg = vpsclone.normalize_agent_state({
                "enable": True,
                "paths": ["~/.local/state/opencode"],
                "exclude": ["*service.json*"],
            })
            copied, skipped, owners = [], [], {}
            with mock.patch.object(vpsclone, "VPS_DATA", data):
                files = vpsclone.snapshot_agent_state(
                    str(home), cfg, vpsclone.load_denylist(),
                    copied, skipped, owners)

            self.assertIn("~/.local/state/opencode/model.json", files)
            self.assertFalse(any("service.json" in k for k in files))
            self.assertTrue(any("service.json" in s[0] for s in skipped))
            self.assertTrue((data / files[
                "~/.local/state/opencode/model.json"]).is_file())

    def test_disabled_config_stages_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            data = Path(td) / "data"
            state = home / ".local/state/opencode"
            state.mkdir(parents=True)
            data.mkdir()
            (state / "model.json").write_text("{}")
            cfg = vpsclone.normalize_agent_state({"enable": False})
            with mock.patch.object(vpsclone, "VPS_DATA", data):
                files = vpsclone.snapshot_agent_state(
                    str(home), cfg, vpsclone.load_denylist(), [], [], {})
            self.assertEqual(files, {})

    def test_replay_writes_enabled_snapshot_only(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            data = Path(td) / "data"
            staged = data / "agent-state/state/model.json"
            staged.parent.mkdir(parents=True)
            staged.write_text('{"model":"test"}')
            target = home / ".local/state/opencode/model.json"
            m = {
                "target": {"home": str(home), "user": "saz"},
                "capture_owners": {},
                "agent_state": {
                    "enable": True,
                    "files": {"~/.local/state/opencode/model.json":
                              "agent-state/state/model.json"},
                },
            }
            with mock.patch.object(vpsclone, "VPS_DATA", data), \
                 contextlib.redirect_stdout(io.StringIO()):
                vpsclone.step_agent_state(m, False, None)
            self.assertEqual(target.read_text(), '{"model":"test"}')

            target.unlink()
            m["agent_state"]["enable"] = False
            with mock.patch.object(vpsclone, "VPS_DATA", data), \
                 contextlib.redirect_stdout(io.StringIO()):
                vpsclone.step_agent_state(m, False, None)
            self.assertFalse(target.exists())

    def test_agent_state_is_a_first_class_task(self):
        self.assertIn("agent_state", vpsclone.TASK_LADDER)
        self.assertIn("agent_state", vpsclone.default_task_defs())
        self.assertIn("agent_state", vpsclone.CONVERGENCE_FOR_TASK)


if __name__ == "__main__":
    unittest.main()
