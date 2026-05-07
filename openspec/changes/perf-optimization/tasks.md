## 1. Config Singleton

- [x] 1.1 Add `_config_cache` module-level variable to `config.py` and modify `load_config()` to return cached instance on subsequent calls
- [x] 1.2 Add `_clear_config_cache()` helper and call it from `save_config()`, `set_context()`, `add_context()`, and `remove_context()`

## 2. Shared Cache Helpers

- [x] 2.1 Add `vms_from_cache(cached_data: list[dict]) -> list[VMInfo]` function to `cache.py` and add `nodes_from_cache()` helper
- [x] 2.2 Add `get_nodes_or_fetch(context, client)` to `cache.py` that checks cache validity and falls back to live API
- [x] 2.3 Add `get_vms_or_fetch(context, client, fetch_ips)` to `cache.py` with same cache-first pattern
- [x] 2.4 Add `get_storages_or_fetch(context, client, node, content_type)` to `cache.py` with cache-first pattern, filtering cached storages by node and content_type

## 3. Eliminate Redundant API Calls in Create Command

- [x] 3.1 Replace `client.get_nodes()` at line 243 with `get_nodes_or_fetch()` using cached nodes
- [x] 3.2 Replace `client.get_storages()` at line 432 with `get_storages_or_fetch()` using cached storages
- [x] 3.3 Remove redundant `client.get_vms(fetch_ips=False)` at line 574 and reuse `existing_vms` for VMID calculation
- [x] 3.4 Remove inline `_vms_from_cache` equivalent in `create_cmd.py` and use shared `vms_from_cache()` from cache.py

## 4. Consolidate Duplicated Helpers Across Commands

- [x] 4.1 Replace `_vms_from_cache` in `list_cmd.py` with import from `cache.py`
- [x] 4.2 Replace `_vms_from_cache` and `_get_vms_with_cache` in `ps_cmd.py` with shared helpers from `cache.py`
- [x] 4.3 Replace `_vms_from_cache`, `_nodes_from_cache` in `status_cmd.py` with shared helpers from `cache.py`
- [x] 4.4 Replace `_vms_from_cache` and `_get_vms_with_cache` in `update_cmd.py` with shared helpers from `cache.py`

## 5. Parallel IP Fetching

- [x] 5.1 Refactor `get_vms()` in `proxmox.py` to collect running non-template VMs first, then resolve IPs in parallel using `ThreadPoolExecutor(max_workers=10)` when 3+ VMs need resolution
- [x] 5.2 Keep sequential fallback for fewer than 3 VMs

## 6. Lazy Imports in main.py

- [x] 6.1 Lazy imports not applicable — Typer requires real function signatures at registration time; `**kwargs` wrappers break CLI parameter parsing. main.py kept as-is. The performance wins are in API call elimination (tasks 1-5), not import time.
- [x] 6.2 N/A — see 6.1
