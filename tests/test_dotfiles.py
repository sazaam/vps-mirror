#!/usr/bin/env python3
"""Tests for the expanded dotfile allowlist and opt-in symlink handling."""

from __future__ import annotations

import contextlib
import importlib.machinery
import importlib.util
import io
import os
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "vpsclone"
_loader = importlib.machinery.SourceFileLoader("vpsclone", str(MODULE_PATH))
_spec = importlib.util.spec_from_loader("vpsclone", _loader)
vpsclone = importlib.util.module_from_spec(_spec)
_loader.exec_module(vpsclone)


class DotfileTests(unittest.TestCase):
    def test_common_dotfiles_are_declared_once_and_not_denied(self):
        self.assertTrue(vpsclone.COMMON_DOTFILES)
        self.assertEqual(len(vpsclone.DOTFILE_ALLOW),
                         len(set(vpsclone.DOTFILE_ALLOW)))
        self.assertTrue(set(vpsclone.BASE_DOTFILES) <= set(vpsclone.DOTFILE_ALLOW))
        self.assertTrue(set(vpsclone.COMMON_DOTFILES) <= set(vpsclone.DOTFILE_ALLOW))
        pats = vpsclone.load_denylist()
        for rel in vpsclone.COMMON_DOTFILES:
            self.assertFalse(vpsclone.is_denied(rel, pats), rel)

    def test_symlink_link_target_is_portable_and_bounded(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            real = home / ".config/dots/zshrc"
            real.parent.mkdir(parents=True)
            real.write_text("bindkey -e\n", encoding="utf-8")

            inside = home / ".zshrc"
            inside.symlink_to(real)
            got, why = vpsclone.symlink_link_target(inside, str(home))
            self.assertEqual(got, "~/.config/dots/zshrc")
            self.assertIsNone(why)

            outside = Path(td) / "etc" / "shadow"
            outside.parent.mkdir(parents=True)
            outside.write_text("secret\n", encoding="utf-8")
            bad = home / ".shadow"
            bad.symlink_to(outside)
            got, why = vpsclone.symlink_link_target(bad, str(home))
            self.assertIsNone(got)
            self.assertIn("outside home", why)

            broken = home / ".broken"
            broken.symlink_to(home / "missing")
            got, why = vpsclone.symlink_link_target(broken, str(home))
            self.assertIsNone(got)
            self.assertIn("broken or looping", why)

    def test_safe_link_target_rejects_absolute_paths(self):
        with tempfile.TemporaryDirectory() as td:
            for link in ("/etc/passwd", "~/.config/../../etc/passwd",
                         "~/ok\n/etc/passwd"):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        vpsclone.safe_link_target(link, td)

    def test_write_managed_symlink_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            (home / ".config/dots").mkdir(parents=True)
            dest = home / ".zshrc"
            link = "~/.config/dots/zshrc"
            self.assertTrue(vpsclone.write_managed_symlink(
                link, dest, home=str(home), owner=""))
            self.assertTrue(dest.is_symlink())
            self.assertEqual(os.readlink(dest), str(home / ".config/dots/zshrc"))
            self.assertFalse(vpsclone.write_managed_symlink(
                link, dest, home=str(home), owner=""))

    def test_convergence_checks_symlink_when_allowed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = root / "home"
            real = home / ".config/dots/zshrc"
            real.parent.mkdir(parents=True)
            real.write_text("bindkey -e\n", encoding="utf-8")
            link = home / ".zshrc"
            link.symlink_to(real)

            repo = root / "repo"
            src = repo / "dotfiles/.zshrc"
            src.parent.mkdir(parents=True)
            src.write_text(real.read_text(), encoding="utf-8")
            dropin = root / "99-vpsclone.conf"
            dropin.write_text(
                "PasswordAuthentication no\nPubkeyAuthentication yes\n"
                "AllowUsers saz\n", encoding="utf-8")

            m = {
                "target": {"user": "saz", "home": str(home)},
                "dotfiles": {"~/.zshrc": "dotfiles/.zshrc"},
                "baseline": {
                    "dotfile_symlinks": {"~/.zshrc": "~/.config/dots/zshrc"},
                },
                "policy": {"allow_symlinks": True},
                "packages": {"apt": []},
                "services": {"enable": []},
                "ssh": {"port": "22"},
                "firewall": {"allow": []},
                "system_files": {},
                "repos": [],
                "binaries": [],
                "data": {},
            }

            def runner(args, **kwargs):
                return 0, ":22 "

            originals = (vpsclone.REPO, vpsclone.FINAL_DROPIN,
                         vpsclone.CUTOVER_DROPIN)
            vpsclone.REPO = repo
            vpsclone.FINAL_DROPIN = dropin
            vpsclone.CUTOVER_DROPIN = root / "missing-cutover.conf"
            try:
                out = vpsclone.check_convergence(m, runner=runner)
                results = {name: ok for name, ok, _, _ in out}
                self.assertTrue(results["dotfile:~/.zshrc"])

                link.unlink()
                link.write_text("plain file\n", encoding="utf-8")
                out = vpsclone.check_convergence(m, runner=runner)
                results = {name: ok for name, ok, _, _ in out}
                self.assertFalse(results["dotfile:~/.zshrc"])

                m["policy"]["allow_symlinks"] = False
                out = vpsclone.check_convergence(m, runner=runner)
                results = {name: ok for name, ok, _, _ in out}
                self.assertFalse(results["dotfile:~/.zshrc"])
            finally:
                (vpsclone.REPO, vpsclone.FINAL_DROPIN,
                 vpsclone.CUTOVER_DROPIN) = originals


if __name__ == "__main__":
    unittest.main()
