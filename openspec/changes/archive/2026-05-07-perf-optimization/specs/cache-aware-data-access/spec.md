## ADDED Requirements

### Requirement: Shared VM cache converter
The system SHALL provide a single `vms_from_cache(cached_data: list[dict]) -> list[VMInfo]` function in `proxmate/core/cache.py` that converts cached dict data into VMInfo objects. All command modules SHALL use this shared function instead of maintaining their own copies.

#### Scenario: Cache data conversion
- **WHEN** a command module needs to convert cached VM dicts to VMInfo objects
- **THEN** it SHALL call `vms_from_cache()` from `proxmate.core.cache` and receive a list of VMInfo instances with all fields populated including `ip_address` and `template`

#### Scenario: Duplicated helpers removed
- **WHEN** the change is complete
- **THEN** the `_vms_from_cache` functions in `list_cmd.py`, `ps_cmd.py`, `status_cmd.py`, and `update_cmd.py` SHALL be removed and replaced with imports from `proxmate.core.cache`

### Requirement: Cache-first node access
The system SHALL provide a `get_nodes_or_fetch(context: str, client: ProxmoxClient) -> list[NodeInfo]` function that returns cached nodes when cache is valid (age <= 60s), and falls back to a live API call otherwise.

#### Scenario: Cache hit for nodes
- **WHEN** a command calls `get_nodes_or_fetch()` and the nodes cache is valid
- **THEN** the function SHALL return nodes from cache without making any API call

#### Scenario: Cache miss for nodes
- **WHEN** a command calls `get_nodes_or_fetch()` and the nodes cache is expired or missing
- **THEN** the function SHALL call `client.get_nodes()`, update the cache, and return the result

### Requirement: Cache-first VM access
The system SHALL provide a `get_vms_or_fetch(context: str, client: ProxmoxClient, fetch_ips: bool = False) -> list[VMInfo]` function that returns cached VMs when cache is valid, and falls back to a live API call otherwise.

#### Scenario: Cache hit for VMs
- **WHEN** a command calls `get_vms_or_fetch()` and the VMs cache is valid
- **THEN** the function SHALL return VMs from cache without making any API call

#### Scenario: Cache miss for VMs
- **WHEN** a command calls `get_vms_or_fetch()` and the VMs cache is expired or missing
- **THEN** the function SHALL call `client.get_vms(fetch_ips=fetch_ips)`, update the cache, and return the result

### Requirement: Cache-first storage access
The system SHALL provide a `get_storages_or_fetch(context: str, client: ProxmoxClient, node: str, content_type: str = "images") -> list[dict]` function that returns cached storages for the given node when cache is valid, and falls back to a live API call otherwise.

#### Scenario: Cache hit for storages
- **WHEN** a command calls `get_storages_or_fetch()` and the storages cache is valid
- **THEN** the function SHALL return storages filtered by node and content_type from cache without making any API call

#### Scenario: Cache miss for storages
- **WHEN** a command calls `get_storages_or_fetch()` and the storages cache is expired or missing
- **THEN** the function SHALL call `client.get_storages(node, content_type)`, and return the result

### Requirement: Create command eliminates redundant API calls
The `create` command SHALL NOT call `client.get_vms()` more than once. The VMID calculation at the preparation step SHALL reuse the VM list already fetched during the name-conflict check.

#### Scenario: VMID calculation reuses existing data
- **WHEN** the create command reaches the VM preparation step
- **THEN** it SHALL compute `existing_vmids` from the `existing_vms` list already fetched earlier, not from a new API call

#### Scenario: Nodes fetched from cache in create
- **WHEN** the create command needs the list of online nodes
- **THEN** it SHALL use `get_nodes_or_fetch()` instead of a direct `client.get_nodes()` call

#### Scenario: Storages fetched from cache in create
- **WHEN** the create command needs storage information
- **THEN** it SHALL use `get_storages_or_fetch()` instead of a direct `client.get_storages()` call

### Requirement: Parallel IP fetching
The `ProxmoxClient.get_vms()` method SHALL fetch IP addresses in parallel using `concurrent.futures.ThreadPoolExecutor` when `fetch_ips=True` and there are 3 or more running non-template VMs.

#### Scenario: Parallel resolution with many VMs
- **WHEN** `get_vms(fetch_ips=True)` is called and there are 3+ running non-template VMs
- **THEN** IP addresses SHALL be resolved concurrently with a max of 10 worker threads

#### Scenario: Sequential resolution with few VMs
- **WHEN** `get_vms(fetch_ips=True)` is called and there are fewer than 3 running non-template VMs
- **THEN** IP addresses SHALL be resolved sequentially (no thread overhead)

### Requirement: Lazy command imports
The `main.py` module SHALL defer importing command modules until the corresponding command is invoked. Running `proxmate version` SHALL NOT import `proxmoxer`, `pydantic`, or command modules.

#### Scenario: Fast startup for version command
- **WHEN** a user runs `proxmate version`
- **THEN** only `typer` and `proxmate.__init__` SHALL be imported; command modules like `create_cmd`, `list_cmd`, and `proxmoxer` SHALL NOT be loaded

#### Scenario: Full imports on command use
- **WHEN** a user runs `proxmate list`
- **THEN** the `list_cmd` module and its dependencies SHALL be imported at that point
