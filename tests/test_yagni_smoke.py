#!/usr/bin/env python3
"""Small post-YAGNI smoke tests: bundle, vault, TUI mapping, validators, SSH, git.

Run with: python3 -m unittest discover -s tests -q
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.machinery
import importlib.util
import io
import tarfile
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).resolve().parents[1] / "vpsclone"
_loader = importlib.machinery.SourceFileLoader("vpsclone", str(MODULE_PATH))
_spec = importlib.util.spec_from_loader("vpsclone", _loader)
vpsclone = importlib.util.module_from_spec(_spec)
_loader.exec_module(vpsclone)


class YagniSmokeTests(unittest.TestCase):
    def test_bundle_includes_core_files_and_skips_secret_dirs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            data = root / "data"
            repo.mkdir()
            data.mkdir()
            (repo / "vpsclone").write_text("# smoke fixture\n", encoding="utf-8")
            for name in ("mirror.toml", "manifest.toml"):
                (data / name).write_text("# smoke fixture\n", encoding="utf-8")
            for secret in ("vault/keys/passphrase.txt", "vault/inventory.toml",
                           "secrets/token.txt", "backups/old.tar.gz"):
                p = data / secret
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("secret\n", encoding="utf-8")
            out = root / "bundle.tar.gz"

            with mock.patch.object(vpsclone, "REPO", repo), \
                 mock.patch.object(vpsclone, "VPS_DATA", data), \
                 mock.patch.object(vpsclone, "MANIFEST", data / "manifest.toml"), \
                 mock.patch.object(vpsclone, "DENYLIST", root / "denylist.txt"), \
                 contextlib.redirect_stdout(io.StringIO()):
                vpsclone.op_bundle(argparse.Namespace(output=str(out)))

            self.assertTrue(out.is_file())
            with tarfile.open(out, "r:gz") as tf:
                names = tf.getnames()
            for name in ("vpsclone", "BUNDLE_README.txt"):
                self.assertIn(f"vps-mirror/{name}", names)
            for name in ("mirror.toml", "manifest.toml"):
                self.assertIn(f"vps-mirror-data/{name}", names)
            for bad in ("vault", "keys", "secrets", "backups"):
                self.assertFalse(any(bad in Path(n).parts for n in names), bad)

    def test_vault_force_keeps_passphrase_and_inventory_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            vdir = root / "vault"
            args = argparse.Namespace(dir=str(vdir), force=False)

            def fake_which(name):
                return "/usr/bin/gpg" if name == "gpg" else None

            with mock.patch.object(vpsclone.shutil, "which", fake_which), \
                 mock.patch.object(vpsclone, "REPO", root / "repo"), \
                 contextlib.redirect_stdout(io.StringIO()):
                vpsclone.op_vault_scaffold(args)

                passfile = vdir / "keys/passphrase.txt"
                invfile = vdir / "inventory.toml"
                cfgfile = vdir / "vault.toml"
                self.assertTrue(passfile.is_file())
                self.assertTrue(invfile.is_file())

                cfg_text = cfgfile.read_text(encoding="utf-8")
                cfg = tomllib.loads(cfg_text)
                inv = tomllib.loads(invfile.read_text(encoding="utf-8"))
                self.assertNotIn("age", cfg)
                self.assertNotIn("backend", cfg)
                self.assertNotIn("profile", inv)
                self.assertNotIn("backend", cfg_text)

                # Simulate user-owned data: force must not rotate or reset it.
                original_pass = passfile.read_bytes()
                edited_inv = invfile.read_bytes() + b"# user edit\n"
                invfile.write_bytes(edited_inv)

                vpsclone.op_vault_scaffold(
                    argparse.Namespace(dir=str(vdir), force=True))

            self.assertEqual(passfile.read_bytes(), original_pass)
            self.assertEqual(invfile.read_bytes(), edited_inv)

    def test_tui_task_mapping_and_verify_check_does_not_run_op_verify(self):
        tasks = set(vpsclone.default_task_defs())
        # firewall is currently checked live (ufw status) in _tui_check_task
        # rather than through a check_convergence prefix.
        covered = set(vpsclone.CONVERGENCE_FOR_TASK) | {"firewall"}
        expected = tasks - {"preflight", "verify"}
        self.assertLessEqual(expected, covered)

        with mock.patch.object(vpsclone, "check_convergence", return_value=[]), \
             mock.patch.object(vpsclone, "cmd", return_value=(1, "")), \
             mock.patch.object(vpsclone, "op_verify") as verify:
            result = vpsclone._tui_check_task("verify", {}, False)
            firewall = vpsclone._tui_check_task("firewall", {}, False)
        self.assertEqual(result, [])
        verify.assert_not_called()
        self.assertTrue(any(label == "ufw status" and state == "WARN"
                            for label, state, _ in firewall))

    def test_keygen_validators_reject_unsafe_names_and_targets(self):
        for name in ("config", "authorized_keys", "known_hosts", "..",
                     "foo.pub"):
            with self.subTest(name=name), \
                 contextlib.redirect_stderr(io.StringIO()), \
                 self.assertRaises(SystemExit):
                vpsclone.validate_key_name(name)
        self.assertEqual(vpsclone.validate_key_name("deploy-github"),
                         "deploy-github")

        for target in ("", "   ", "user @host", "\thost"):
            with self.subTest(target=target), \
                 contextlib.redirect_stderr(io.StringIO()), \
                 self.assertRaises(SystemExit):
                vpsclone.validate_ssh_target(target)
        self.assertEqual(vpsclone.validate_ssh_target("user@host"), "user@host")

    def test_revert_ssh_restores_dropins_and_reloads_after_sshd_test_error(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            final = root / "99-vpsclone.conf"
            cutover = root / "99-vpsclone-cutover.conf"
            final.write_text("Port 22\n", encoding="utf-8")
            cutover.write_text("Port 2022\n", encoding="utf-8")
            calls = []

            def fake_cmd(args, **kwargs):
                argv = [str(a) for a in args]
                calls.append(argv)
                if argv == ["sshd", "-t"]:
                    return 3, "sshd config invalid\n"
                return 0, ""

            with mock.patch.object(vpsclone, "FINAL_DROPIN", final), \
                 mock.patch.object(vpsclone, "CUTOVER_DROPIN", cutover), \
                 mock.patch.object(vpsclone, "ssh_unit", lambda: "sshd"), \
                 mock.patch.object(vpsclone, "cmd", fake_cmd):
                rc, out = vpsclone._revert_ssh(b"Port 2222\n", None)
                self.assertEqual(final.read_bytes(), b"Port 2222\n")
                self.assertFalse(cutover.exists())

                calls.clear()
                rc2, out2 = vpsclone._revert_ssh(None, None)

            self.assertEqual((rc, out), (3, "sshd config invalid\n"))
            self.assertEqual(calls, [["sshd", "-t"],
                                     ["systemctl", "reload", "sshd"]])
            self.assertEqual((rc2, out2), (rc, out))
            self.assertFalse(final.exists())
            self.assertFalse(cutover.exists())

    def test_add_git_excludes_is_idempotent_and_creates_no_gitignore(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / ".git/info").mkdir(parents=True)
            with mock.patch.object(vpsclone, "REPO", repo):
                vpsclone.add_git_excludes()
                exclude = repo / ".git/info/exclude"
                first = exclude.read_text(encoding="utf-8").splitlines()
                vpsclone.add_git_excludes()
                second = exclude.read_text(encoding="utf-8").splitlines()

            self.assertIn("/vault/", first)
            self.assertIn("*.gpg", first)
            self.assertEqual(first.count("/vault/"), 1)
            self.assertEqual(first.count("*.gpg"), 1)
            self.assertEqual(second, first)
            self.assertFalse((repo / ".gitignore").exists())

    def test_capture_allow_sha256_release_overrides_content_scan(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "cli.json"
            src.write_text("password=hunter2\n", encoding="utf-8")
            dst = root / "captured" / "cli.json"
            allow = root / "capture-allow.txt"
            allow.write_text("# none\n", encoding="utf-8")

            with mock.patch.object(vpsclone, "CAPTURE_ALLOW", allow):
                self.assertFalse(vpsclone.capture_allowed(src, ".config/cli.json"))
                self.assertTrue(vpsclone.content_secret_hits(src, ".config/cli.json"))

                digest = vpsclone.sha256_file(src)
                allow.write_text(f"sha256:{digest}\n", encoding="utf-8")
                self.assertTrue(vpsclone.capture_allowed(src, ".config/cli.json"))
                self.assertEqual(
                    vpsclone.content_secret_hits(src, ".config/cli.json"), [])
                copied = []
                skipped = []
                self.assertTrue(vpsclone.capture_copy(
                    src, ".config/cli.json", dst, [], copied, skipped))
                self.assertEqual(dst.read_bytes(), src.read_bytes())

    def test_audit_surfaces_permission_skips_as_gaps_and_reasons(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            repo.mkdir()
            out = root / "mirror.toml"
            data = {
                "meta": {"schema": 1, "name": "fixture", "captured_at": "now",
                         "source_host": "src", "source_os": "Fixture"},
                "target": {"user": "saz", "home": "/home/saz",
                           "hostname": "src"},
                "system": {"timezone": "UTC"},
                "ssh": {"port": "2022",
                        "hardening_file": "ssh/sshd_hardening.conf",
                        "authorized_keys_file": "ssh/authorized_keys",
                        "allow_users": ["saz"]},
                "firewall": {"allow": ["2022/tcp"]},
                "packages": {"apt": []},
                "services": {"enable": []},
                "repos": [], "binaries": [], "data": {"paths": []},
                "dotfiles": {}, "system_files": {},
            }
            inv_meta = {"method": "fixture", "counts": {}, "notes": [],
                        "warnings": []}
            skipped = [
                (".config/opencode/cli.json", "permission denied - rerun with sudo"),
                ("cache", "denylist"),
            ]
            with mock.patch.object(vpsclone, "collect_baseline",
                                   return_value=(data, ["ok"], skipped, inv_meta)), \
                 mock.patch.object(vpsclone, "REPO", repo), \
                 mock.patch.object(vpsclone, "MANIFEST", root / "manifest.toml"), \
                 mock.patch.object(vpsclone, "REPORTS", root / "reports"), \
                 contextlib.redirect_stdout(io.StringIO()):
                vpsclone.op_audit(argparse.Namespace(out=str(out), name=None))

            plan = tomllib.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(any("permission denied" in g
                                for g in plan["audit"]["gaps"]))
            report = (root / "reports/audit-report.txt").read_text(encoding="utf-8")
            self.assertIn("Skipped files", report)
            self.assertIn(".config/opencode/cli.json  "
                          "[permission denied - rerun with sudo]", report)

    def test_capture_copy_preserves_source_owner_and_records_it(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            src = root / "source.conf"
            src.write_text("owner me\n", encoding="utf-8")
            dst = repo / "dotfiles" / "source.conf"
            st = src.stat()
            owners = {}
            with mock.patch.object(vpsclone, "VPS_DATA", repo), \
                 mock.patch.object(vpsclone, "is_root", return_value=True), \
                 mock.patch.object(vpsclone.os, "chown") as chown, \
                 contextlib.redirect_stdout(io.StringIO()):
                ok = vpsclone.capture_copy(src, "source.conf", dst, [], [], [],
                                           owners=owners)
            self.assertTrue(ok)
            chown.assert_called_once_with(dst, st.st_uid, st.st_gid)
            self.assertEqual(owners["dotfiles/source.conf"]["uid"], st.st_uid)
            self.assertEqual(owners["dotfiles/source.conf"]["gid"], st.st_gid)

    def test_capture_copy_permission_skip_names_both_owners(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "source.conf"
            src.write_text("x\n", encoding="utf-8")
            dst = root / "staged.conf"
            dst.write_text("x\n", encoding="utf-8")
            skipped = []
            with mock.patch.object(vpsclone.shutil, "copy2",
                                   side_effect=PermissionError("nope")), \
                 contextlib.redirect_stdout(io.StringIO()):
                ok = vpsclone.capture_copy(src, "source.conf", dst, [], [],
                                           skipped)
            self.assertFalse(ok)
            self.assertEqual(len(skipped), 1)
            self.assertIn("source ", skipped[0][1])
            self.assertIn("staged ", skipped[0][1])

    def test_restore_capture_owner_prefers_name_and_keeps_group_id(self):
        spec = {"user": "nobody", "group": "", "uid": 12345, "gid": 23456}
        m = {"capture_owners": {"dotfiles/.zshrc": spec}}
        with mock.patch.object(vpsclone.os, "chown") as chown, \
             contextlib.redirect_stdout(io.StringIO()):
            vpsclone._restore_capture_owner(Path("/fake/.zshrc"), m,
                                            "dotfiles/.zshrc")
        chown.assert_called_once()
        self.assertEqual(chown.call_args.args[1],
                         vpsclone.pwd.getpwnam("nobody").pw_uid)
        self.assertEqual(chown.call_args.args[2], 23456)
        self.assertTrue(chown.call_args.kwargs["follow_symlinks"])


if __name__ == "__main__":
    unittest.main()
