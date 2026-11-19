#!/usr/bin/env python3
"""Tests for honest, version-aware convergence checks.

Run with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import contextlib
import getpass
import importlib.machinery
import importlib.util
import io
import json
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "vpsclone"
_loader = importlib.machinery.SourceFileLoader("vpsclone", str(MODULE_PATH))
_spec = importlib.util.spec_from_loader("vpsclone", _loader)
vpsclone = importlib.util.module_from_spec(_spec)
_loader.exec_module(vpsclone)


class FakeRunner:
    def __init__(self, responses: dict[str, tuple[int, str]]):
        self.responses = responses

    def __call__(self, args, **kwargs):
        key = " ".join(str(a) for a in args)
        return self.responses.get(key, (127, ""))


def base_manifest() -> dict:
    return {
        "target": {"user": getpass.getuser(), "home": "/home/fixture",
                   "hostname": "fixture"},
        "ssh": {"port": "22", "authorized_keys_file": ""},
        "users": [],
        "packages": {},
        "services": {"enable": []},
        "repos": [],
        "binaries": [],
        "dotfiles": {},
        "system_files": {},
    }


class ConvergenceTests(unittest.TestCase):
    def test_expected_versions_prefers_records_and_skips_nonreplayable_cargo(self):
        m = base_manifest()
        m["packages"] = {
            "npm": ["a", "b"],
            "records": [
                {"installer": "npm", "name": "a", "version": "1.2.3"},
                {"installer": "cargo", "name": "ripgrep", "version": "14.0.0"},
                {"installer": "cargo", "name": "proxy", "version": "0.1",
                 "replayable": False},
            ],
        }
        self.assertEqual(vpsclone.expected_versions(m, "npm"), {"a": "1.2.3"})
        self.assertEqual(vpsclone.expected_versions(m, "cargo"),
                         {"ripgrep": "14.0.0"})
        self.assertEqual(vpsclone.expected_versions(m, "pipx"), {})

    def test_npm_global_versions_parses_scoped_packages(self):
        runner = FakeRunner({
            "npm ls -g --json --depth=0": (0, json.dumps({
                "dependencies": {
                    "opencode": {"version": "1.2.3"},
                    "@scope/tool": {"version": "2.0.0"},
                }
            })),
        })
        self.assertEqual(
            vpsclone.npm_global_versions("/home/fixture", runner=runner),
            {"opencode": "1.2.3", "@scope/tool": "2.0.0"},
        )

    def test_convergence_flags_version_and_commit_drift(self):
        m = base_manifest()
        m["packages"] = {
            "apt": ["htop"],
            "records": [
                {"installer": "npm", "name": "opencode", "version": "1.2.3"},
                {"installer": "cargo", "name": "ripgrep", "version": "14.0.0"},
            ],
        }
        m["services"]["enable"] = ["ssh"]
        m["repos"] = [{"path": "~/proj", "url": "git@github.com:o/r.git",
                       "branch": "main", "commit": "abc1234"}]

        runner = FakeRunner({
            "dpkg-query -W -f=${Status} htop": (0, "install ok installed\n"),
            "npm ls -g --json --depth=0": (0, json.dumps({
                "dependencies": {"opencode": {"version": "9.9.9"}}})),
            "cargo install --list": (0, "ripgrep v14.0.0:\n    /x/ripgrep\n"),
            "systemctl is-active ssh": (0, "active\n"),
            "systemctl is-enabled ssh": (0, "enabled\n"),
            "git -C /home/fixture/proj remote get-url origin":
                (0, "git@github.com:o/r.git\n"),
            "git -C /home/fixture/proj branch --show-current": (0, "main\n"),
            "git -C /home/fixture/proj rev-parse HEAD": (0, "def5678\n"),
            "git -C /home/fixture/proj status --porcelain": (0, ""),
            "ss -tulpn": (0, "LISTEN 0 128 0.0.0.0:22 0.0.0.0:*\n"),
            "sshd -t": (0, ""),
        })

        results = {name: (ok, detail, warn)
                   for name, ok, detail, warn
                   in vpsclone.check_convergence(m, runner=runner)}

        self.assertFalse(results["npm:versions"][0])
        self.assertIn("want 1.2.3, got 9.9.9", results["npm:versions"][1])
        self.assertTrue(results["cargo:versions"][0])
        self.assertFalse(results["repo:~/proj"][0])
        self.assertIn("want=abc1234 got=def5678", results["repo:~/proj"][1])
        self.assertTrue(results["service:ssh"][0])
        self.assertTrue(results["manual:vault"][2])
        self.assertTrue(results["manual:login"][2])

    def test_step_packages_uses_pinned_specs(self):
        m = base_manifest()
        m["packages"] = {
            "records": [
                {"installer": "npm", "name": "opencode", "version": "1.2.3"},
                {"installer": "pipx", "name": "httpie", "version": "3.2.0"},
                {"installer": "cargo", "name": "ripgrep", "version": "14.0.0"},
            ],
        }
        calls = []

        def fake_cmd(args, **kwargs):
            calls.append([str(a) for a in args])
            return 0, ""

        original_cmd = vpsclone.cmd
        original_which = vpsclone.shutil.which
        vpsclone.cmd = fake_cmd
        vpsclone.shutil.which = lambda name: f"/usr/bin/{name}"
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                vpsclone.step_packages(m, False, None)
        finally:
            vpsclone.cmd = original_cmd
            vpsclone.shutil.which = original_which

        npm_call = next(c for c in calls if c[:2] == ["npm", "install"])
        self.assertIn("opencode@1.2.3", npm_call)
        self.assertTrue(any(c == ["pipx", "install", "httpie==3.2.0"]
                            for c in calls))
        cargo_call = next(c for c in calls if c[:2] == ["cargo", "install"])
        self.assertEqual(cargo_call,
                         ["cargo", "install", "ripgrep", "--version", "14.0.0"])


if __name__ == "__main__":
    unittest.main()
