## Why

The ProxMate CLI has significant latency despite a background daemon that caches Proxmox API data every 30 seconds. Commands like `create` and `list` still make redundant live API calls, ignoring available cache data. The worst user-facing issue is a multi-second delay in the `create` wizard between VM naming and the next prompt, caused by a redundant full VM listing. Additionally, `load_config()` reads and parses the YAML config file from disk on every invocation (5-6 times per command), and startup imports all modules eagerly even for trivial commands.

## What Changes

- **Eliminate redundant API calls in `create` command**: Reuse already-fetched VM list for VMID calculation instead of calling `get_vms()` a second time. Use cached nodes and storages instead of live API calls.
- **Add in-memory config singleton**: Cache the parsed config in memory after first load to avoid repeated YAML file reads within a single command execution.
- **Use cache throughout all commands**: `create_cmd.py` calls `get_nodes()` and `get_storages()` live while the daemon already caches this data. Route these through cache-aware helpers.
- **Consolidate `_vms_from_cache` into shared utility**: The same cache-to-VMInfo conversion function is duplicated in 4 command files. Extract to `proxmate/core/cache.py`.
- **Add parallel IP fetching in daemon**: The daemon fetches IPs sequentially per VM (1-2 API calls each). Use `concurrent.futures.ThreadPoolExecutor` for parallel resolution.
- **Lazy imports in `main.py`**: Defer command module imports so `proxmate version` doesn't load proxmoxer/pydantic/rich.

## Capabilities

### New Capabilities
- `cache-aware-data-access`: Unified cache-first data access layer that all commands use for nodes, VMs, templates, and storages. Eliminates ad-hoc cache checks scattered across command files.
- `config-singleton`: In-memory config caching to avoid repeated YAML disk reads within a command lifecycle.

### Modified Capabilities

## Impact

- **proxmate/core/config.py**: Add module-level config cache with invalidation.
- **proxmate/core/cache.py**: Add `vms_from_cache()` shared helper. Add cache-aware accessor functions for nodes and storages.
- **proxmate/core/proxmox.py**: Add parallel IP fetching with `concurrent.futures`. Accept optional pre-fetched nodes list in `get_vms()`.
- **proxmate/core/daemon.py**: Use parallel IP fetching during refresh.
- **proxmate/cli/create_cmd.py**: Remove redundant `get_vms()` at line 574, use cached nodes/storages, remove inline `_vms_from_cache`.
- **proxmate/cli/list_cmd.py**: Use shared `vms_from_cache()` helper.
- **proxmate/cli/ps_cmd.py**: Use shared `vms_from_cache()` helper.
- **proxmate/cli/status_cmd.py**: Use shared helpers.
- **proxmate/cli/update_cmd.py**: Use shared helpers.
- **proxmate/cli/main.py**: Lazy import command modules.
- **Dependencies**: `concurrent.futures` is stdlib, no new dependencies.
