# A-List — VPS mirror pain reduction

These are all active priorities. We work top-down but do not drop later items.

- [x] **1. Honest, version-aware convergence checks**
  - Pin and verify npm/cargo/mise versions, not just names.
  - Verify repo URL/branch/commit, not just `.git` existence.
  - Verify binary hashes, service enablement, key/file contents.
  - Keep manual gates (vault/data/fresh SSH login) explicit WARNs, never silent PASS.

- [x] **2. Content-level secret scanning at capture**
  - Scan allowlisted captured files for tokens/passwords/private keys.
  - Quarantine suspicious files instead of bundling them.
  - Add a reviewable ship-list to `reports/audit-report.txt`.

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
