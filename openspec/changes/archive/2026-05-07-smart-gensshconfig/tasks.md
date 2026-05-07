## 1. Parse existing SSH config

- [x] 1.1 Add `_parse_proxmate_section(content: str) -> dict[str, dict]` function that extracts Host entries from the ProxMate section, returning `{hostname: {ip, user, key}}`. Handle missing section, empty section, and malformed entries gracefully.

## 2. Build desired state

- [x] 2.1 Add `_build_desired_state(created_vms, current_vms) -> dict[str, dict]` function that computes the expected SSH config from `vms.yaml` data + Proxmox live/cached IPs. Auto-derives private key from public key path. Skips VMs with no resolvable IP (with warning). Prompts only for VMs missing SSH key path.

## 3. Compute and display diff

- [x] 3.1 Add `_compute_diff(existing, desired) -> list[dict]` that compares both states and classifies each entry as ADD, MODIFY, REMOVE, or UNCHANGED. For MODIFY entries, include which fields changed and old/new values.
- [x] 3.2 Add `_display_diff_table(changes) -> None` that displays the diff in a Rich table with `+`, `~`, `-`, `=` indicators. Number only actionable changes (ADD/MODIFY/REMOVE). Show UNCHANGED entries dimmed.

## 4. Opt-out selection

- [x] 4.1 Add opt-out prompt: display "Exclure (ex: 3 ou 1,3, vide = tout appliquer)" and parse the exclusion list. Reuse existing `_parse_selection` pattern from other commands. Return the list of retained changes.

## 5. Apply changes surgically

- [x] 5.1 Add `_apply_changes(existing_content, retained_changes, all_existing_entries) -> str` that produces the new ProxMate section content by adding new entries, updating modified entries, removing deleted entries, and preserving unchanged entries.
- [x] 5.2 Add backup step in `_update_ssh_config`: copy `~/.ssh/config` to `~/.ssh/config.proxmate.bak` before writing, and display the backup path to the user.
- [x] 5.3 Update `_update_ssh_config` to accept the new block and replace only the ProxMate section as before.

## 6. Rewrite gensshconfig_command

- [x] 6.1 Rewrite `gensshconfig_command()` with the new diff-based flow: parse existing → build desired → compute diff → display → opt-out → apply. Add `--force` flag that falls back to old interactive behavior.
- [x] 6.2 Update SSH connection test to only test ADD and MODIFY entries (skip UNCHANGED).

## 7. Clean known_hosts for modified IPs

- [x] 7.1 When a MODIFY change involves an IP change, automatically offer to remove the old IP from `known_hosts` (reuse existing `_remove_from_known_hosts`).
