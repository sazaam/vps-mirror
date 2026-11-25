# A-List — VPS mirror pain reduction

All items below are complete. This list is kept as a record of what the tool
was deliberately taught to do.

- [x] **1. Honest, version-aware convergence checks**
  - Pin and verify npm/cargo/mise versions, not just names.
  - Verify repo URL/branch/commit, not just `.git` existence.
  - Verify binary hashes, service enablement, key/file contents.
  - Keep manual gates (vault/data/fresh SSH login) explicit WARNs, never silent PASS.

- [x] **2. Content-level secret scanning at capture**
  - Scan allowlisted captured files for tokens/passwords/private keys.
  - Quarantine suspicious files instead of bundling them.
  - Add a reviewable ship-list to `reports/capture-report.txt`.

- [x] **3. Convert the manual tail into first-class actions**
  - Deploy-key verification, extra-user `authorized_keys`, data sync, vault, fresh-login probe.
  - Keep secrets inside guided child processes / target memory only.

- [x] **4. Two-phase SSH cutover with rollback timer**
  - Open new port, validate config, reload, require a fresh-login confirmation.
  - Automatic rollback after 600s if the cutover is not committed.

- [x] **5. Thin remote driver**
  - Wrap `ssh + sudo` so `drive` can reach the target without a hand-copied bundle.
  - Never persist credentials; reuse target-local prompts.

- [x] **6. Dotfile discovery and opt-in symlinks**
  - Look for common shell/editor/tool dotfiles beyond the original small allowlist.
  - Capture in-home symlinks safely; TUI `allow_symlinks` prompt recreates them or writes plain files.

- [x] **7. Visible skips and captured ownership**
  - Permission-denied captures are audit gaps with per-file reasons in `audit-report.txt`.
  - Source `uid:gid` is preserved locally under root and replayed as user:group on the target.

- [x] **8. Clean Git worktree**
  - Only code and docs remain in the repo; all captured data, reports, bundles, vault and rollback state live in `~/.vps-data`.
  - `~/.vps-data` resolves to the invoking user's home even under `sudo`, and is chowned back to that user after root audits.

- [x] **9. Toolchain bootstrapping and project-level dependencies**
  - Mise-aware tool resolution lists npm/pipx/cargo globals even when the tool is not on plain `PATH`.
  - Manifest-driven `toolchain` task confirms and installs missing managers before dependent installs.
  - `[[project_deps]]` records detected Node/Rust managers; skipped-by-default TUI actions and CLI subcommands install per project on request.

- [x] **10. Agent config and opt-in agent state**
  - Curated OpenCode/herdr config files and the `AGENTS.md` symlink are captured like other dotfiles.
  - `~/.local/state/opencode` snapshots are opt-in via `[agent_state]`, denylisted and content-scanned like every other capture.
  - Snapshots replay through the `agent_state` step/task and are convergence-checked.
