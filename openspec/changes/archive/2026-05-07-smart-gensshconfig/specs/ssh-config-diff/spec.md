## ADDED Requirements

### Requirement: Parse existing ProxMate SSH config section
The system SHALL parse the content between `# === PROXMATE START ===` and `# === PROXMATE END ===` markers in `~/.ssh/config` and extract a dict of existing Host entries with their HostName, User, and IdentityFile fields.

#### Scenario: ProxMate section exists with entries
- **WHEN** `~/.ssh/config` contains a ProxMate section with Host entries
- **THEN** the parser SHALL return a dict keyed by Host name, each value containing `ip`, `user`, and `key` fields

#### Scenario: ProxMate section is empty or absent
- **WHEN** `~/.ssh/config` has no ProxMate section, or the section is empty
- **THEN** the parser SHALL return an empty dict

#### Scenario: ProxMate section has malformed entries
- **WHEN** the ProxMate section contains entries that don't match the expected format
- **THEN** the parser SHALL skip malformed entries and parse the rest, logging a warning

### Requirement: Auto-resolve desired SSH state
The system SHALL compute the desired SSH config state from `vms.yaml` and Proxmox data without interactive prompts when all required data is available.

#### Scenario: VM with complete data
- **WHEN** a VM in `vms.yaml` has a recorded user, ssh_public_key_path, and a resolvable IP (from Proxmox or static config)
- **THEN** the system SHALL include it in the desired state without prompting, deriving the private key path by stripping the `.pub` extension

#### Scenario: VM with missing IP
- **WHEN** a VM has no resolvable IP (stopped VM with DHCP, no agent)
- **THEN** the system SHALL skip it with a warning message and not include it in the desired state

#### Scenario: VM with missing SSH key
- **WHEN** a VM has no `ssh_public_key_path` in `vms.yaml`
- **THEN** the system SHALL prompt the user for the key path for that VM only

### Requirement: Compute diff between existing and desired state
The system SHALL compare existing SSH config entries against the desired state and classify each entry into one of four categories: ADD, MODIFY, REMOVE, or UNCHANGED.

#### Scenario: New VM not in SSH config
- **WHEN** a VM is in the desired state but not in the existing SSH config
- **THEN** it SHALL be classified as ADD

#### Scenario: VM with changed IP
- **WHEN** a VM exists in both states but the IP address differs
- **THEN** it SHALL be classified as MODIFY with the IP change shown

#### Scenario: VM with changed user or key
- **WHEN** a VM exists in both states but the user or IdentityFile differs
- **THEN** it SHALL be classified as MODIFY with the changed fields shown

#### Scenario: VM unchanged
- **WHEN** a VM exists in both states with identical ip, user, and key
- **THEN** it SHALL be classified as UNCHANGED

#### Scenario: VM removed from Proxmox
- **WHEN** a Host entry exists in the SSH config but the VM no longer exists in `vms.yaml` or Proxmox
- **THEN** it SHALL be classified as REMOVE

### Requirement: Display changes with opt-out selection
The system SHALL display all proposed changes (ADD, MODIFY, REMOVE) in a numbered table. UNCHANGED entries SHALL be shown but not numbered. The user SHALL be able to exclude specific changes by entering their numbers before confirmation.

#### Scenario: User applies all changes
- **WHEN** the user presses Enter without excluding any changes
- **THEN** all proposed changes SHALL be applied

#### Scenario: User excludes specific changes
- **WHEN** the user enters numbers to exclude (e.g., "3" or "1,3")
- **THEN** only the non-excluded changes SHALL be applied

#### Scenario: No changes detected
- **WHEN** the diff shows all entries as UNCHANGED
- **THEN** the system SHALL display a message that the SSH config is up to date and exit without prompting

### Requirement: Backup SSH config before modification
The system SHALL create a backup of `~/.ssh/config` before applying any changes, saving it as `~/.ssh/config.proxmate.bak`.

#### Scenario: Backup created before writing
- **WHEN** the system is about to write changes to `~/.ssh/config`
- **THEN** it SHALL first copy the current file to `~/.ssh/config.proxmate.bak`, overwriting any previous backup

#### Scenario: Backup path displayed to user
- **WHEN** the backup is created successfully
- **THEN** the system SHALL display the backup file path so the user knows where to find it if needed

### Requirement: Apply selected changes surgically
The system SHALL update only the ProxMate section of `~/.ssh/config`, applying only the changes the user retained. Content outside the ProxMate markers SHALL NOT be modified.

#### Scenario: Mixed changes applied
- **WHEN** the user retains ADD, MODIFY, and REMOVE changes
- **THEN** new entries SHALL be added, modified entries SHALL have their fields updated, and removed entries SHALL be deleted from the ProxMate section

#### Scenario: Unchanged entries preserved
- **WHEN** some entries are UNCHANGED
- **THEN** those entries SHALL remain exactly as they were in the SSH config

### Requirement: Force flag for full regeneration
The system SHALL accept a `--force` flag that bypasses diff analysis and runs the full interactive configuration flow (original behavior).

#### Scenario: Force flag used
- **WHEN** the user runs `proxmate gensshconfig --force`
- **THEN** the system SHALL skip diff analysis and run the interactive wizard that prompts for every VM's details, replacing the entire ProxMate section

### Requirement: SSH connection test after changes
After applying changes, the system SHALL offer to test SSH connections, but only for VMs that were added or modified (not unchanged VMs).

#### Scenario: Test only changed entries
- **WHEN** the user accepts to test connections after applying
- **THEN** the system SHALL only test VMs that were part of ADD or MODIFY changes, not UNCHANGED ones
