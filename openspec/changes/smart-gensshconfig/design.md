## Context

The `gensshconfig` command currently works as a full-regeneration wizard: it asks the user for every VM's details (key, user, IP) and replaces the entire ProxMate SSH config block. The SSH config file (`~/.ssh/config`) may contain many other entries unrelated to ProxMate, which are delimited by `# === PROXMATE START ===` / `# === PROXMATE END ===` markers.

The rewrite converts this into a diff-based, non-interactive command that only proposes necessary changes.

## Goals / Non-Goals

**Goals:**
- Parse the existing ProxMate SSH config section into structured data
- Auto-resolve the desired state from `vms.yaml` + Proxmox cache/API (no interactive prompts when data is complete)
- Compute a diff with 4 change types: ADD, MODIFY, REMOVE, UNCHANGED
- Display changes in a Rich table with opt-out selection (same `1,3,5-7` pattern as other commands)
- Apply only the selected changes to the SSH config
- Provide `--force` for full regeneration (fallback to old behavior)

**Non-Goals:**
- Parsing or modifying SSH config entries outside the ProxMate markers
- Managing SSH keys (key generation, rotation)
- Supporting non-standard SSH config formats (Include directives, Match blocks)
- Interactive prompts for every VM (the old behavior, except via `--force`)

## Decisions

### 1. Parse ProxMate section using simple line-based parser

The ProxMate section uses a strict format:
```
Host <name>
    HostName <ip>
    User <user>
    IdentityFile <key>
```

A regex-based or line-by-line parser is sufficient. No need for a full SSH config parser since we only read our own section and ignore everything else.

**Alternative considered**: Using a library like `paramiko` for SSH config parsing. Rejected — adds a dependency for something we can do in ~20 lines, and we only need to parse our own predictable format.

### 2. Desired state resolved automatically, prompt only for missing data

For each VM in `vms.yaml`:
1. **IP**: Resolve from Proxmox (via `get_vms_or_fetch`), fallback to `vms.yaml` static IP. If neither available → prompt or skip with warning.
2. **User**: From `vms.yaml` (set at creation time). Always available.
3. **Key**: Derive private key path from `vms.yaml`'s `ssh_public_key_path` (strip `.pub`). If not recorded → prompt.

This means for well-configured VMs (the common case), zero prompts.

### 3. Diff classification

Match existing entries to desired entries by **Host name** (the VM name):

| Existing | Desired | Classification |
|----------|---------|----------------|
| absent   | present | ADD (+)        |
| present  | present, same values | UNCHANGED (=) |
| present  | present, different values | MODIFY (~) |
| present  | absent (VM deleted from Proxmox) | REMOVE (-) |

For MODIFY, detect which fields changed (IP, user, key) and show the diff clearly.

### 4. Opt-out selection UX

Display all proposed changes (ADD, MODIFY, REMOVE — not UNCHANGED) in a numbered table. By default all are selected. The user enters numbers to **exclude** from application. Empty input = apply all.

This is the same pattern as `delete` and `update` commands for UX consistency.

### 5. Surgical update instead of full block replacement

Instead of regenerating the entire block, the apply step:
1. Starts from the current ProxMate section content
2. Adds new entries for retained ADD changes
3. Updates fields in-place for retained MODIFY changes
4. Removes entries for retained REMOVE changes
5. Rewrites only the ProxMate section, preserving everything else

### 6. Backup before writing

Before any modification to `~/.ssh/config`, copy the current file to `~/.ssh/config.proxmate.bak`. This is a single rolling backup (overwritten each time). Implemented in `_update_ssh_config` so both the diff-based flow and the `--force` flow benefit from it.

**Alternative considered**: Timestamped backups (`.bak.20260507`). Rejected — accumulates files, the user only needs the last known-good state.

### 7. `--force` flag for full regeneration

When `--force` is passed, skip the diff entirely and run the old interactive wizard flow (useful when the user wants to reconfigure everything from scratch).

## Risks / Trade-offs

- **[Stale IP from cache]** → The diff might show an IP change that's actually transient (DHCP renewal). Mitigated by: user can exclude the change via opt-out.

- **[VM renamed but same VMID]** → The diff matches by Host name, not VMID. If a VM is renamed, the old name appears as REMOVE and the new name as ADD. This is correct behavior — the SSH config should reflect the current name.

- **[Parser fragility]** → If someone manually edits the ProxMate section and breaks the format, the parser might fail. Mitigated by: fall back to full regeneration if parsing fails, with a warning.
