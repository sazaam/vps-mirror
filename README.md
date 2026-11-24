# vps-mirror

A **declarative, self-hosted VPS cloner**. No image service, no paid transfer
service — just a small git repo that describes *what* your box should be, plus a
stdlib-only Python tool that captures it and replays it on a fresh Ubuntu install.

> Snapshots copy bytes. This copies **intent** — portable across providers,
> disk sizes and Ubuntu releases, diffable in git, and cheap enough to `scp`.

The hardening rules are deliberately aligned with the existing dotS knowledge
base (`skills/server-setup.s @sshHarden @firewall @fail2ban @verify`); that skill
remains the human-readable source of truth, this tool just makes it executable.

---

## Layout

The Git repo contains **code and docs only**:

```
vps-mirror/
  vpsclone                 # Python 3.11+ orchestrator, stdlib only
  bootstrap.sh             # scp-and-run entrypoint for a bone-stock box
  denylist.txt             # never capture/bundle anything matching these globs
  capture-allow.txt        # hash/path releases for the content secret scan
  hooks/                   # pre-apply.sh / post-apply.sh extension points
  tests/                   # unittest suite
  README.md, A-LIST.md, LICENSE
```

All machine-specific data lives in **`~/.vps-data/`** — or, when invoked through
`sudo`, in the **sudoing user's** home, never `/root`:

```
~/.vps-data/
  mirror.toml              # AUTHORED descriptor: audit facts + prompt flags + task graph
  manifest.toml            # GENERATED from mirror.toml by `audit`/`drive` (engine input)
  reports/capture-report.txt
  reports/audit-report.txt
  dotfiles/                # allowlisted dotfiles, deployed as plain files or opt-in symlinks
  ssh/authorized_keys      # PUBLIC keys only
  ssh/sshd_hardening.conf  # generated from server-setup.s @sshHarden
  system/etc/...           # captured system configs (fail2ban, nginx later...)
  vault/                   # GPG vault (secrets, never bundled)
  backups/                 # local rollback snapshots (never bundled)
  ssh-cutover.json         # rollback timer state
```

There are no `.gitignore` rules hiding this data: it is simply outside the repo.
A root-run `audit` chowns the whole data tree back to the invoking user, and
records the original `uid:gid` of each source file in `[baseline.capture_owners]`
for replay on the target. Bundles carry two top-level trees: `vps-mirror/` (code)
and `vps-mirror-data/` (the contents of `~/.vps-data`, minus vault/backups).

---

## Two-step descriptor workflow (recommended)

Instead of deciding everything on the target, use `mirror.toml` as the single
authored hand-off file. It contains audited source facts, prompt **declarations**
(not answers), the task ladder, guided actions, and an embedded baseline from
which `manifest.toml` is generated. No secrets ever go in it. Checks live in the
engine, not as per-task declarations in this file.

**Step 1 — local/source audit:**

```sh
sudo ./vpsclone audit --user <login> --users <sftpuser,deploy> \
  --out ~/.vps-data/mirror.toml
git status                  # only code/docs changes belong here
./vpsclone bundle           # ships code + ~/.vps-data, not the Git repo itself
```

`audit` writes `mirror.toml`, `manifest.toml` and `reports/audit-report.txt`
under `~/.vps-data/`. The report lists gaps, deferred decisions, and every
skipped file with its reason. Permission-denied captures become explicit audit
gaps and name both the source and staged owner. The original `uid:gid` of each
source file is recorded under `[baseline.capture_owners]`; `apply` restores that
user:group on the target (names first, numeric ids as a fallback). When `audit`
runs as root, the entire data tree is chowned back to the invoking user, so no
Git or maintenance step ever needs root-owned files.

**Package inventory.** `audit` and `capture` use a small built-in detector
(`vpsclone-inventory/1`, stdlib only, feature-inspired by ESR's `inventory` but
independently implemented) for apt, npm, pipx, cargo and mise. It writes
`[audit.inventory]` provenance to `mirror.toml` — counts, notes, warnings and a
records hash. Versioned installer records (npm, pipx, cargo, mise) are kept in
`[baseline.packages.records]` for pinned replay and convergence checks; apt is
stored as a plain name list because apt replay resolves versions from the
archive. No passwords, tokens or private keys are stored. Every candidate
capture file is also content-scanned: token, password and private-key markers
cause the file to be quarantined rather than bundled. False positives can be
released with a relative path or `sha256:<hash>` line in `capture-allow.txt`.
apt packages are filtered against `/var/log/installer/initial-status*.gz` when
available; if those logs are missing the unfiltered list is kept and reported as
a gap. npm scoped names (`@scope/pkg`) are preserved. npm/pipx/cargo/mise are
replayed at the recorded version when one exists; an unavailable installer is
reported as a warning, never guessed from binaries on disk.

**Dotfiles.** `audit` looks for an expanded allowlist: the original shell, git,
mise, OpenCode and herdr configs plus common files such as `.inputrc`,
`.tmux.conf`, `.editorconfig`, `.gitattributes`, fish/nvim/helix configs,
starship/alacritty/kitty/wezterm/foot/zellij configs, ripgrep/fd/lazygit/lsd/bat
configs, direnv, pip/cargo/gem and XDG housekeeping files. Secret-shaped configs
(`.npmrc`, `.pypirc`, `.netrc`, cloud/CLI credentials, private keys) are
intentionally **not** in the list and remain denylisted.

A source dotfile that is a symlink is handled too, as long as its final target
stays inside the source home. `audit` stores a plain-file copy in `dotfiles/`
and records the portable `~/...` link target in `[baseline.dotfile_symlinks]`.
Broken links and links pointing outside the source home are reported as skipped,
never followed. In the TUI, the **`allow_symlinks`** yes/no action asks
“Allow captured symlinks?”: `yes` recreates the recorded symlink on the target;
`no` (the default) writes a regular file instead. `verify` checks whichever mode
you chose.

**Convergence checks.** `verify` and the TUI now compare target state with the
effective manifest: package versions, repo URL/branch/commit, source binary
hashes, service enabled + active state, and file/key contents. Manual-only
items (fresh SSH login, GitHub key acceptance, vault and data sync) are reported
as `WARN`, never silently marked `PASS`. Records with no recorded version also
degrade to `WARN` rather than pretending to be verified.

Run the fixture tests with:

```sh
python3 -m unittest discover -s tests -v
```

The pain-reduction backlog is tracked in `A-LIST.md`; all listed items are now
checked off.

**Step 2 — target drive:**

```sh
cd /opt/vps-mirror
sudo ./vpsclone drive --plan "$HOME/.vps-data/mirror.toml" --tui
# resolves declared prompts, writes an effective manifest.toml, then opens the
# curses task driver: arrow keys select, Enter runs, n next pending,
# a opens the guided-actions pane, s skips, d toggles dry-run/live, q quits.
```

Without `--tui`, `drive` resolves the same prompts, writes the manifest and
prints the suggested next commands (`vpsclone plan && sudo vpsclone apply --dry-run`).

If the bundle is still on your local machine, the thin remote driver ships it
and opens the target TUI in one shot:

```sh
python3 vpsclone remote-drive --target user@new-vps --port 22
# or reuse a bundle you already built:
python3 vpsclone remote-drive --target user@new-vps --bundle ~/.vps-data/vps-mirror-*.tar.gz
```

The target command is wrapped in `sudo`, so `user` needs sudo rights; `ssh`/`scp`
own any authentication prompts and no passwords, tokens or passphrases are stored
by vpsclone. The remote copy is temporary and removed on exit unless
`--no-cleanup` is given.

Prompts are flags in `mirror.toml`, for example:

```toml
[desired.target.ssh_port]
from = "source.ssh_port"       # detected on the source machine
prompt_if_default = true       # only asks when source port is 22
default = "22"                 # the detected value, not an invented port

[desired.firewall.ports]
from = "source.ufw_allow"      # editable list on target
prompt = true
```

A non-default detected port (e.g. `2022`) is used as-is with no prompt. When
the source uses the literal default `22`, `drive` asks for the target port and
offers the detected value as the default; it never hardcodes a different port.

**Guided actions.** `mirror.toml` also declares `[[actions]]` for the remaining
human steps. Press `a` in the TUI to open the Actions pane:

- `acknowledge` — checklist items that can't be automated (provider snapshot)
- `prompt_value` — asks for a value and stores it in the in-memory manifest
  only, e.g. `data.paths`
- `prompt_bool` — yes/no policy question, e.g. `allow_symlinks` (Enter=yes,
  `n`=no)
- `guided_subprocess` — suspends curses and runs a known command in a real
  terminal, e.g. `vpsclone keygen` or `vault-unpack`; passphrases stay inside
  the child process

Commands are built from fixed `command_id` values in the engine, never executed
straight from the descriptor. After an action runs, its declared check is
re-evaluated and the result shown before you continue.

Every `[[binaries]]` entry with an empty `install` field also becomes a
`prompt_value` action (e.g. `binary_install_1_opencode`). With `--tui`, those
prompts happen in the Actions pane and are used from the in-memory manifest;
without `--tui`, `drive` asks them in the terminal and writes them to the
generated manifest. The entered command is executed by `step_binaries` via
`sh -c`, so review it before accepting.

The final action, `save_session`, is opt-in: it writes the effective values to
the generated `manifest.toml` with mode `0600` so a later run can resume with
the same answers. It never writes to `mirror.toml` or logs, and refuses to save
if any value looks like a token, password or private key. Since `manifest.toml`
is included in `bundle`, do not re-bundle from a target after saving.

Answers, sudo credentials and passphrases are held only in the target process
and are never written back to `mirror.toml`. `drive --apply` optionally runs
the apply step immediately; `--dry-run` passes through to `apply`.

The classic `capture` command still works if you prefer to maintain
`~/.vps-data/manifest.toml` by hand.

---

## 1. On the source box (capture once, then maintain by hand)

```sh
cd ~/vps-mirror
chmod +x vpsclone bootstrap.sh hooks/*.sh
./vpsclone doctor
./vpsclone capture                 # read-only on the source; writes ~/.vps-data/manifest.toml
./vpsclone plan                    # sanity check
git status                         # data changes are outside the repo
git remote add origin git@github.com:OWNER/vps-mirror.git
git push -u origin main
```

Read `~/.vps-data/reports/capture-report.txt` — it lists exactly what was
captured and what was skipped (secrets, history, caches). Tune `denylist.txt` and
the `DOTFILE_ALLOW` list in `vpsclone` if you want more/less.

The manifest at `~/.vps-data/manifest.toml` is meant to be **reviewed and
edited**. Parameterised fields:

```toml
[target]   user, home, shell, hostname, sudo_group, groups
[ssh]      port, hardening_file
[firewall] allow = ["2022/tcp", "80/tcp"]
[packages] apt = [...], mise.tools = [...], npm/cargo/pipx
[services] enable = [...]
[[users]]  name, home, shell, group, groups, sudo_group,
           ssh_allow, create_home, authorized_keys   # extra accounts
[[repos]]  path, url, branch           # re-cloned, never copied
[[binaries]] name, path, install       # apt-external bins; fill in `install`
[data]     paths = [], exclude = []    # rsync allowlist for non-repo data
[cloud]    preserve_hostname, manage_etc_hosts
```

### Additional users (sftp / deploy / service accounts)

`capture` records the target user (now including supplementary groups such as
`docker`) and no other accounts by default. It never enumerates `/etc/passwd`,
never captures system/service accounts, and never compares against a vanilla
Ubuntu user list. Add extra accounts with an explicit allowlist:

```sh
./vpsclone capture --users sftpuser,deploy
```

Re-capturing without `--users` preserves the existing `[[users]]` entries.
Use `--clear-users` to drop them. Each extra user is captured with home, shell,
primary group, supplementary groups, sudo membership, and (public-key-only)
`~/.ssh/authorized_keys` copied to `ssh/users/<name>/authorized_keys`.

You can also add/edit them by hand:

```toml
[[users]]
name = "sftpuser"
home = "/home/sftpuser"
shell = "/usr/sbin/nologin"
group = "sftpuser"
groups = ["sftp"]
sudo_group = ""
ssh_allow = true
create_home = true
authorized_keys = "ssh/users/sftpuser/authorized_keys"
```

- `ssh_allow = false` keeps the account out of the generated `AllowUsers`.
- `create_home = false` uses `useradd -M` and skips home creation.
- `groups` are additive; missing groups are created with `groupadd`.
- No passwords or `/etc/shadow` data are ever captured.

`plan` lists missing users, and `apply` creates/fixes every entry in the
`users` step. The generated SSH drop-in includes all users with
`ssh_allow = true` (plus the target user), so you do not lock them out.

---

## 2. On a fresh Ubuntu install (two transfer paths)

### Path A — self-contained bundle (zero git-auth needed first)

From the source box:

```sh
./vpsclone bundle            # -> ~/.vps-data/vps-mirror-20261118-143000.tar.gz
scp ~/.vps-data/vps-mirror-*.tar.gz root@NEW_VPS:/opt/
```

On the fresh box:

```sh
cd /opt && tar xzf vps-mirror-*.tar.gz
cd /opt/vps-mirror && chmod +x vpsclone bootstrap.sh
./bootstrap.sh
```

The archive contains `vps-mirror/` (code) and `vps-mirror-data/`. `bootstrap.sh`
installs `python3 git rsync ca-certificates curl openssh-server`, copies
`vps-mirror-data/` into the **invoking user's** `~/.vps-data/`, runs `doctor`
(aborting if preflight fails), then applies `manifest.toml` directly. It does
**not** run `drive`, so the `mirror.toml` prompts/TUI are skipped. Use the
`drive` path above when you need those decisions. It never deletes an existing
`/opt/vps-mirror` in place: a non-fast-forwardable checkout is moved to a
timestamped `.bak.*` directory first.

### Path B — private repo

On the fresh box, after your GitHub key works:

The Git repo now contains code only, so the captured data still comes from a
bundle:

```sh
export VPS_MIRROR_REPO=git@github.com:OWNER/vps-mirror.git
# from the source box, ship the bundle too:
scp ~/.vps-data/vps-mirror-*.tar.gz root@NEW_VPS:/opt/
cd /opt/vps-mirror && sudo ./bootstrap.sh   # installs the bundled data first
```

### Always dry-run first

```sh
sudo python3 vpsclone apply --dry-run
sudo python3 vpsclone apply               # real
sudo python3 vpsclone verify
```

Ordering note baked into the tool: **UFW port is opened before sshd is
reloaded**, and `sshd -t` is validated with automatic revert. SSH now uses a
**two-phase cutover**: `apply` stages a drop-in with both the old and new ports
live, verifies both are listening, and waits. From a new local terminal, test a
fresh login on the new port, then finish with:

```sh
sudo python3 vpsclone ssh-cutover-commit --confirm-login
# or, if the new login failed:
sudo python3 vpsclone ssh-cutover-rollback
```

The prepare/commit/rollback sequence is also exposed as TUI actions
(`ssh_prepare`, `fresh_login`, `ssh_commit`). A detached watchdog rolls back
automatically after 600 seconds if the cutover is not committed; override with
`ssh-cutover-prepare --rollback-seconds N`. The rollback state lives in
`~/.vps-data/ssh-cutover.json` (mode `0600`) and is excluded from bundles. The old firewall
rule is deliberately left for manual cleanup after a successful commit.
`--ssh-port` rewrites the captured `Port` line so the firewall, drop-in and
verifier always agree.

---

## 3. The deploy key (your chosen flow)

Private keys are **never** in the repo or bundle. Generate locally with a
passphrase prompt, ship the private half, paste the public half into GitHub:

```sh
# from your local machine (not the VPS)
python3 vpsclone keygen --target example-user@NEW_VPS --name deploy-github

# ssh-keygen prompts hidden; the script prints the public key and scp's
# the private key + ~/.ssh/config entry to the target.
```

Then paste the printed key into GitHub → Settings → SSH and GPG keys → New SSH
key, and on the VPS:

```sh
ssh -T git@github.com          # "Hi <you>!" = success
cd /opt/vps-mirror
sudo python3 vpsclone apply --only=repos   # clones dotS et al as `example-user`
```

If repos fail on the first apply, that's expected — re-run `--only=repos` after
adding the GitHub key. It is idempotent.

---

## 4. Day-to-day

| Task | Command |
|---|---|
| See drift on a box | `./vpsclone plan` |
| Re-apply after editing manifest | `sudo ./vpsclone apply` |
| Just packages | `sudo ./vpsclone apply --only=packages` |
| Just firewall + ssh | `sudo ./vpsclone apply --only=firewall,ssh` |
| Health check | `sudo ./vpsclone verify` |
| Copy non-repo data | `./vpsclone sync-data --destination user@host:/path` |
| Undo last apply | `sudo ./vpsclone rollback` |
| Refresh capture from source | `./vpsclone capture` (review the diff before committing!) |

Partial applies via `--only` are safe: backups are still written for any file
that gets replaced, and the backup index is saved immediately so `rollback`
still works even if a later step fails. `rollback` restores **files only** —
packages, services, firewall rules and cloned repos are not undone.

Hooks are an explicit step named `hooks`. A normal `apply` includes it (running
`pre-apply.sh` first and `post-apply.sh` last); `--only=packages,ssh` skips both
hooks unless you add `hooks` to the list. Hooks run as root from the repo root,
and a non-zero exit aborts the apply.

---

## 5. Extending it (the "later" parts)

- **nginx reverse proxy**: add site files under `system/etc/nginx/sites-available/`,
  add mappings to `[system_files]`, add port 80/443 to `[firewall].allow`, and
  add `nginx` to `[services].enable`. Use `dots get skills/nginx.s @reverseProxy`
  and `@ssl` to author them; the SSL playbook can be wired into a post-apply hook.
- **Projects / oh-my-zsh / p10k**: add a `[[repos]]` block per checkout. Git repos
  are re-cloned, not rsync'd — that's the lazy bit that keeps transfers tiny.
  `capture` finds these automatically (shallow scan, depth 4).
- **External binaries** (e.g. `opencode`, `herdr` in `~/.local/bin`): recorded in
  `[[binaries]]` with their size but **not copied**. Fill in the `install` field
  once with the upstream one-liner and `apply --only=binaries` will reproduce
  them on any fresh box. Until then it warns instead of pretending.
- **Bulk data / DBs**: list directories in `[data].paths` and excludes in
  `[data].exclude`; use `sync-data`. For databases, add a dump step to
  `hooks/pre-apply.sh` on the source and a restore step on the target.
- **New hostname/user**: pass `--hostname` / override `[target]`; nothing is
  hardcoded to a particular user or hostname in the logic.

---

## 6. What it deliberately does *not* do

- No bit-for-bit disk image, kernel, partition layout or provider metadata.
- No running-process memory state.
- No database consistency guarantees unless you add dumps to hooks.
- No auto-discovery of every `/etc/passwd` account or vanilla-user diff. Extra
  users must be named explicitly with `--users` or `[[users]]`.
- No plaintext secrets in git, ever: capture quarantines denylisted paths,
  content-scanned files and unsafe symlinks (safe in-home symlinks are copied as
  plain files), and `bundle` validates every member before creating the archive
  (all SSH material is denied except `config`, `authorized_keys` and `*.pub`).
  Captured data is outside git now, so review `~/.vps-data/reports/` and the
  bundle listing directly — filename rules are a guardrail, not a content
  scanner.
- No secret backup/restore in the mirror either. That is a separate vault
  workflow (section 7) whose inventory, keys and archives live outside git.

For a same-provider, same-disk exact image you can still `dd`/`tar` the rootfs
separately and store it wherever you already have space — but for "fresh Ubuntu
install, reproduce my setup" the manifest path is faster, smaller and safer.

---

## 7. Vault — secrets, API keys and usernames (outside git)

This is deliberately a **separate lane**. The repo never sees an inventory, a
key, an archive, or a secret value. The vault defaults to `~/.vps-data/vault`
and `bundle` skips it entirely (along with `backups/`, `keys/`, `secrets/` and
`*.gpg`). There is no pre-commit hook and no gitignore rule hiding secrets — the
whole data tree simply lives outside the checkout.

### One-time setup

```sh
./vpsclone vault-scaffold --dir ~/.vps-data/vault
```

It uses GPG symmetric encryption and creates:

```
~/.vps-data/vault/
  vault.toml          # relative paths only, no secrets
  inventory.toml      # REAL paths and identity values — keep it here
  keys/passphrase.txt # GPG passphrase (mode 0600)
  archives/           # encrypted *.gpg tarballs
  backups/            # overwritten files are copied here before restore
  bin/pack.sh         # generated wrapper, no embedded secrets
  bin/unpack.sh       # generated wrapper, no embedded secrets
  README.md
```

Edit `inventory.toml`. It uses **aliases** for safe labels:

```toml
version = 1

[targets."github-deploy"]
path = "~/.ssh/deploy-github"
mode = "0600"

[identities."vps-login"]
path = "~/.vps-data/vault/identity/vps-login"
value = "example-user"      # real username/API key lives here, outside git
mode = "0600"
```

### Backup / restore

```sh
VAULT=~/.vps-data/vault

"$VAULT/bin/pack.sh" --dry-run       # aliases only, no contents
"$VAULT/bin/pack.sh"                 # writes archives/secrets-<stamp>.gpg

"$VAULT/bin/unpack.sh" --dry-run     # validate archive, show aliases
"$VAULT/bin/unpack.sh" --yes         # restore real paths from THIS inventory
```

Equivalent direct commands:

```sh
./vpsclone vault-list   --vault-dir "$VAULT"
./vpsclone vault-verify --vault-dir "$VAULT"
./vpsclone vault-pack   --vault-dir "$VAULT"
./vpsclone vault-unpack --vault-dir "$VAULT" --archive "$VAULT/archives/<file>"
```

### Safety properties

- Keys/passphrases are never passed on the command line and never logged.
- `vault-scaffold --force` refreshes only generated wrappers and README; it
  never rotates the passphrase, rewrites `vault.toml`, or overwrites
  `inventory.toml`.
- Archives contain only `meta.json` plus alias-named files. Real paths and
  values are **not** stored in the archive; they come from the local inventory.
- Extract is never done to disk: members are read into memory after traversal,
  symlink, device and size checks.
- Restore refuses symlinks, backs up existing files into `backups/`, restores
  modes, and asks for confirmation unless `--yes` is given.
- Generated scripts are thin wrappers that locate the vault relative to
  themselves and call `vpsclone`; they contain no secrets.

Copy only `archives/*.gpg` to offline media or a separate private store. Copy
`keys/passphrase.txt` separately. Never copy `inventory.toml` into the mirror
repo.
