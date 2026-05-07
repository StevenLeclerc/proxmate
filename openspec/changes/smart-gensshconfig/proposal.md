## Why

The `proxmate gensshconfig` command currently regenerates the entire SSH config block every time, asking interactively for key/user/IP for every VM — even when nothing has changed. With 10+ VMs this is tedious and error-prone. The command should analyze the existing `~/.ssh/config`, compare it with the current state of VMs in Proxmox, and only propose the necessary modifications (additions, IP changes, removals).

## What Changes

- **Parse existing SSH config**: Read and parse the ProxMate section (between `# === PROXMATE START ===` / `# === PROXMATE END ===` markers) to extract current Host entries with their HostName, User, and IdentityFile.
- **Compute desired state automatically**: Build the expected SSH config from `vms.yaml` + live Proxmox data (IPs via cache/API) without interactive prompts. Only prompt when data is missing (no IP available, no SSH key recorded).
- **Diff and classify changes**: Compare existing vs desired and classify each VM as:
  - `+` **ADD** — VM exists in ProxMate but not in SSH config
  - `~` **MODIFY** — VM exists but IP, user, or key has changed
  - `-` **REMOVE** — VM is in SSH config but no longer exists in Proxmox
  - `=` **UNCHANGED** — Already correct, no action needed
- **Opt-out selection**: Display all proposed changes in a numbered table. By default all changes are applied. The user can exclude specific changes by number (e.g., `3` or `1,3`) before confirming — same UX pattern as `delete` and `update` commands.
- **Surgical update**: Only modify the entries that were retained, preserving unchanged entries and everything outside the ProxMate markers.
- **Add `--force` flag**: Bypass diff analysis and do a full regeneration (old behavior) when needed.

## Capabilities

### New Capabilities
- `ssh-config-diff`: Parsing existing SSH config, computing diff against desired state, and applying selective changes with opt-out UI.

### Modified Capabilities

## Impact

- **proxmate/cli/sshconfig_cmd.py**: Major rewrite of `gensshconfig_command()`. New functions for parsing existing config, computing diff, displaying change table, and applying selective updates.
- **UX change**: The command becomes non-interactive by default (auto-resolves all data), which is a behavior change for existing users. The `--force` flag preserves access to the old fully-interactive flow.
- **No new dependencies**: Uses only existing stdlib + Rich for the table display.
- **Safe by design**: Only operates within the `PROXMATE_SECTION_START` / `PROXMATE_SECTION_END` markers. Other SSH config entries are never touched.
