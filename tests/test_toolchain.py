#!/usr/bin/env python3
"""Tests for mise-aware tool resolution, toolchain recipes and project deps."""

from __future__ import annotations

import argparse
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


class ToolResolutionTests(unittest.TestCase):
    def tearDown(self):
        vpsclone._TOOL_CACHE.clear()

    def test_npm_is_resolved_through_mise_when_not_on_path(self):
        def which(name):
            return "/usr/bin/mise" if name == "mise" else None

        with mock.patch.object(vpsclone.shutil, "which", side_effect=which), \
             mock.patch.object(vpsclone, "cmd", return_value=(0, "")) as cmd:
            argv = vpsclone.tool_argv("npm", ["ls", "-g", "--json"],
                                      "/home/saz", prefer_mise=True)

        self.assertEqual(argv, ["mise", "exec", "--", "npm", "ls", "-g", "--json"])
        cmd.assert_any_call(["mise", "exec", "--", "npm", "--version"],
                            quiet=True, env={"HOME": "/home/saz"})

    def test_plain_path_is_used_when_mise_cannot_run_tool(self):
        def which(name):
            return "/usr/bin/mise" if name == "mise" else f"/usr/bin/{name}"

        with mock.patch.object(vpsclone.shutil, "which", side_effect=which), \
             mock.patch.object(vpsclone, "cmd", return_value=(1, "")):
            argv = vpsclone.tool_argv("cargo", ["install", "--list"],
                                      "/home/saz", prefer_mise=True)

        self.assertEqual(argv, ["cargo", "install", "--list"])


class ToolchainTests(unittest.TestCase):
    def test_required_managers_come_from_manifest(self):
        m = {
            "packages": {
                "records": [
                    {"installer": "npm", "name": "x", "version": "1"},
                    {"installer": "pipx", "name": "y", "version": "1"},
                ],
                "mise": {"tools": ["node@26"]},
            },
            "project_deps": [
                {"repo": "~/p", "kind": "rust", "manager": "cargo"},
                {"repo": "~/q", "kind": "node", "manager": "yarn"},
            ],
        }
        self.assertEqual(vpsclone.required_managers(m),
                         ["mise", "node", "npm", "pipx", "cargo", "yarn"])

    def test_toolchain_installs_missing_manager_then_rechecks(self):
        m = {
            "target": {"user": "saz", "home": "/home/saz"},
            "packages": {"records": [{"installer": "pipx"}]},
        }
        steps = [{"label": "apt", "argv": ["apt-get", "install", "-y", "pipx"]}]
        calls = []

        with mock.patch.object(vpsclone, "required_managers", return_value=["pipx"]), \
             mock.patch.object(vpsclone, "manager_available",
                               side_effect=[False, True]), \
             mock.patch.object(vpsclone, "manager_install_steps",
                               return_value=steps), \
             mock.patch.object(vpsclone, "_confirm", return_value=True), \
             mock.patch.object(vpsclone, "cmd",
                               side_effect=lambda argv, **kw: (calls.append(argv), (0, ""))[1]), \
             contextlib.redirect_stdout(io.StringIO()):
            rc = vpsclone.op_ensure_toolchain(argparse.Namespace(yes=False))

        self.assertEqual(rc, 0)
        self.assertEqual(calls, [steps[0]["argv"]])


class ProjectDepTests(unittest.TestCase):
    def test_detect_project_deps_reads_lockfiles(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            node = home / "web"
            rust = home / "cli"
            node.mkdir()
            rust.mkdir()
            (node / "package-lock.json").write_text("{}")
            (rust / "Cargo.toml").write_text("[package]")
            (rust / "Cargo.lock").write_text("# lock")
            repos = [{"path": "~/web"}, {"path": "~/cli"}]

            deps = vpsclone.detect_project_deps(str(home), repos)

        self.assertEqual(deps, [
            {"repo": "~/cli", "kind": "rust", "manager": "cargo",
             "lockfile": "Cargo.lock"},
            {"repo": "~/web", "kind": "node", "manager": "npm",
             "lockfile": "package-lock.json"},
        ])

    def test_project_install_commands_use_lockfiles(self):
        cases = [
            ({"manager": "npm", "lockfile": "package-lock.json", "repo": "~/p"},
             ["npm", "ci"]),
            ({"manager": "npm", "lockfile": "package.json", "repo": "~/p"},
             ["npm", "install"]),
            ({"manager": "yarn", "lockfile": "yarn.lock", "repo": "~/p"},
             ["yarn", "install", "--frozen-lockfile"]),
            ({"manager": "pnpm", "lockfile": "pnpm-lock.yaml", "repo": "~/p"},
             ["pnpm", "install", "--frozen-lockfile"]),
            ({"manager": "cargo", "lockfile": "Cargo.lock", "repo": "~/p"},
             ["cargo", "build", "--locked"]),
        ]
        with mock.patch.object(vpsclone, "_tool_prefix", return_value=[]):
            for dep, expected in cases:
                with self.subTest(manager=dep["manager"]):
                    self.assertEqual(
                        vpsclone.project_install_argv(dep, "/home/saz"), expected)


if __name__ == "__main__":
    unittest.main()
