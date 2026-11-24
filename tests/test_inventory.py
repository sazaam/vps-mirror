#!/usr/bin/env python3
"""Fixture tests for the clean-room package detector in vpsclone.

Run with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import contextlib
import gzip
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


class FakeRunner:
    def __init__(self, responses: dict[str, tuple[int, str]]):
        self.responses = responses
        self.calls: list[str] = []

    def __call__(self, args, **kwargs):
        key = " ".join(str(a) for a in args)
        self.calls.append(key)
        return self.responses.get(key, (127, ""))


@contextlib.contextmanager
def fake_cmd(responses: dict[str, tuple[int, str]]):
    original = vpsclone.cmd
    vpsclone.cmd = FakeRunner(responses)
    try:
        yield
    finally:
        vpsclone.cmd = original


def dpkg_status(*packages: str) -> str:
    blocks = []
    for name in packages:
        blocks.append(
            f"Package: {name}\n"
            "Status: install ok installed\n"
            f"Version: 1.0\n"
            "Description: base fixture\n"
        )
    return "\n".join(blocks) + "\n"


class InventoryTests(unittest.TestCase):
    def test_apt_filters_base_packages_from_gzip_log(self):
        with tempfile.TemporaryDirectory() as td:
            log_dir = Path(td)
            with gzip.open(log_dir / "initial-status.gz", "wt", encoding="utf-8") as f:
                f.write(dpkg_status("cloud-init", "python3"))
            with fake_cmd({"apt-mark showmanual": (0, "cloud-init\npython3\nhtop\nvim\n")}):
                records, warnings, notes, stats = vpsclone.inv_apt(log_dir=log_dir)
            self.assertEqual([r["name"] for r in records], ["htop", "vim"])
            self.assertEqual(warnings, [])
            self.assertTrue(any("4 manual -> 2" in n for n in notes))
            self.assertEqual(stats["apt_manual_raw"], 4)

    def test_apt_missing_logs_keeps_unfiltered_list_and_warns(self):
        with tempfile.TemporaryDirectory() as td:
            with fake_cmd({"apt-mark showmanual": (0, "cloud-init\nhtop\n")}):
                records, warnings, _notes, stats = vpsclone.inv_apt(log_dir=Path(td))
            self.assertEqual([r["name"] for r in records], ["cloud-init", "htop"])
            self.assertTrue(any("unfiltered" in w for w in warnings))
            self.assertEqual(stats["apt_manual_raw"], 2)

    def test_npm_json_keeps_scoped_names(self):
        with fake_cmd({
            "npm ls -g --json --depth=0": (
                0,
                '{"dependencies":{"@scope/pkg":{"version":"1.2.3"},'
                '"typescript":{"version":"5.0.0"}}}',
            ),
        }):
            records, warnings, notes, _stats = vpsclone.inv_npm("/home/saz")
        self.assertEqual([r["name"] for r in records], ["@scope/pkg", "typescript"])
        self.assertEqual(records[0]["version"], "1.2.3")
        self.assertEqual(warnings, [])
        self.assertTrue(any("--json" in n for n in notes))

    def test_npm_parseable_fallback_keeps_scoped_names(self):
        with fake_cmd({
            "npm ls -g --json --depth=0": (1, ""),
            "npm ls -g --depth=0 --parseable": (
                0,
                "/usr/lib/node_modules/@scope/pkg\n"
                "/usr/lib/node_modules/typescript\n",
            ),
        }):
            records, warnings, notes, _stats = vpsclone.inv_npm("/home/saz")
        self.assertEqual([r["name"] for r in records], ["@scope/pkg", "typescript"])
        self.assertEqual(warnings, [])
        self.assertTrue(any("fallback" in n for n in notes))

    def test_pipx_splits_name_and_version(self):
        with fake_cmd({"pipx list --short": (0, "black 24.1.0\nyq\n")}):
            records, warnings, _notes, _stats = vpsclone.inv_pipx("/home/saz")
        self.assertEqual(records[0], {"installer": "pipx", "name": "black",
                                      "version": "24.1.0"})
        self.assertEqual(records[1]["name"], "yq")
        self.assertEqual(warnings, [])

    def test_cargo_list_is_authoritative(self):
        with fake_cmd({
            "cargo install --list": (
                0, "ripgrep 14.1.0:\n    /home/saz/.cargo/bin/rg\n"
                   "cargo-edit 0.13.0:\n    /home/saz/.cargo/bin/cargo-add\n",
            ),
        }):
            records, warnings, notes, _stats = vpsclone.inv_cargo("/home/saz")
        self.assertEqual([r["name"] for r in records], ["ripgrep", "cargo-edit"])
        self.assertTrue(all(set(r) == {"installer", "name", "version"}
                            for r in records))
        self.assertEqual(warnings, [])
        self.assertTrue(any("install --list" in n for n in notes))

    def test_inventory_packages_projects_manifest_and_provenance(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            log_dir = root / "installer-logs"
            log_dir.mkdir()
            with gzip.open(log_dir / "initial-status.gz", "wt", encoding="utf-8") as f:
                f.write(dpkg_status("cloud-init"))
            mise_dir = root / ".config/mise"
            mise_dir.mkdir(parents=True)
            (mise_dir / "config.toml").write_text('[tools]\nnode = "20"\n', encoding="utf-8")

            with fake_cmd({
                "apt-mark showmanual": (0, "cloud-init\nhtop\n"),
                "npm ls -g --json --depth=0": (0, '{"dependencies":{"@scope/pkg":{}}}'),
                "pipx list --short": (0, "yq\n"),
                "cargo install --list": (0, "ripgrep 14.1.0:\n"),
            }):
                packages, meta = vpsclone.inventory_packages(str(root), log_dir=log_dir)
            self.assertEqual(packages["apt"], ["htop"])
            self.assertEqual(packages["npm"], ["@scope/pkg"])
            self.assertEqual(packages["pipx"], ["yq"])
            self.assertEqual(packages["cargo"], ["ripgrep"])
            self.assertEqual(packages["mise"], {"tools": ["node@20"]})
            self.assertEqual(meta["counts"]["apt"], 1)
            self.assertEqual(meta["counts"]["apt_manual_raw"], 2)
            self.assertEqual(len(meta["records_sha256"]), 64)
            self.assertEqual(meta["warnings"], [])


if __name__ == "__main__":
    unittest.main()
