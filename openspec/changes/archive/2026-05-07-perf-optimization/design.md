## Context

ProxMate is a Python CLI (Typer + Rich) for managing Proxmox VE clusters. A background daemon refreshes a JSON file cache every 30 seconds, but commands still bypass it for many data fetches. The Proxmox API runs over HTTPS with a 60-second timeout, and each HTTP roundtrip can take 200-800ms depending on network latency and cluster load. A single `create` command currently makes 8-12 API calls where 2-3 would suffice.

The config is stored in `~/.proxmate/config.yaml` and parsed with PyYAML + Pydantic. Each `load_config()` call reads from disk and validates, which is redundant within a single CLI invocation.

## Goals / Non-Goals

**Goals:**
- Eliminate all redundant API calls in the `create` command (target: 2-3 API calls max before the clone operation)
- Route all read operations through cache-first helpers so commands are fast when the daemon is running
- Cache the parsed config in memory to avoid repeated YAML reads within a command
- Consolidate duplicated `_vms_from_cache` into a single shared function
- Parallelize IP fetching in the daemon to reduce refresh cycle time
- Lazy-load command modules in `main.py` to speed up startup for simple commands

**Non-Goals:**
- Rewriting the daemon architecture (e.g., switching to socket-based IPC)
- Adding a persistent connection pool for the Proxmox API (proxmoxer manages its own sessions)
- Changing the cache storage format (JSON files are fine)
- Modifying the CLI UX or command interfaces
- Adding new CLI commands or features

## Decisions

### 1. In-memory config singleton with explicit invalidation

The `load_config()` function will cache its result in a module-level variable `_config_cache`. Subsequent calls within the same process return the cached instance. `save_config()` and `set_context()` will clear the cache after writing.

**Why not functools.lru_cache**: The config can be mutated by `save_config()`, so we need explicit invalidation rather than a pure cache.

**Alternative considered**: Passing config objects through function arguments. Rejected because it would require changing dozens of function signatures across the codebase.

### 2. Cache-aware accessor functions in cache.py

Add high-level functions that encapsulate the cache-check-then-fallback pattern:
- `get_nodes_or_fetch(context, client)` → returns `list[NodeInfo]`
- `get_vms_or_fetch(context, client, fetch_ips)` → returns `list[VMInfo]`
- `get_storages_or_fetch(context, client, node, content_type)` → returns `list[dict]`
- `vms_from_cache(cached_data)` → shared converter (replaces 4 duplicates)

These live in `cache.py` and import `ProxmoxClient` lazily to avoid circular imports.

**Why in cache.py, not in ProxmoxClient**: The client is a stateless API wrapper. Cache logic is a separate concern. Putting it in cache.py keeps the client clean and avoids making the client depend on config/context details.

### 3. Reuse existing_vms in create_cmd.py for VMID calculation

Line 574 (`client.get_vms(fetch_ips=False)`) will be replaced with the `existing_vms` list already fetched at line 330-351. The `existing_vms` variable is already populated (from cache or API) and contains all VMs including templates, which is sufficient for VMID calculation.

### 4. Parallel IP fetching with ThreadPoolExecutor

In `proxmox.py`, when `fetch_ips=True`, collect all running non-template VMs first, then resolve their IPs in parallel using `concurrent.futures.ThreadPoolExecutor(max_workers=10)`. This is safe because each IP fetch is an independent read-only API call.

**Why threads, not asyncio**: proxmoxer is synchronous, and the rest of the codebase is synchronous. Threads are the simplest way to parallelize without rewriting the HTTP layer.

### 5. Lazy imports in main.py via Typer callback

Replace direct imports of command modules with lazy imports inside the command registration. Use a pattern where each `app.command()` wraps a function that imports the real handler on first call.

**Alternative considered**: Using `importlib.import_module` with a custom decorator. Rejected as over-engineered; simple inline imports in wrapper functions are clearer.

### 6. Cache-aware nodes and storages in create_cmd.py

The create command will use `get_nodes_or_fetch()` and `get_storages_or_fetch()` instead of direct `client.get_nodes()` and `client.get_storages()` calls. This means when the daemon is running and cache is fresh, these calls return instantly.

## Risks / Trade-offs

- **[Stale cache data]** → Commands may display slightly outdated information (up to 60s). Mitigated by: cache is already the default behavior for `list`; users can `--refresh` for live data; after mutations (`create`, `delete`), cache is invalidated.

- **[Config singleton and multi-context switching]** → If a user switches context mid-command (impossible in current CLI design but theoretically possible), the cached config would be stale. Mitigated by: `set_context()` clears the cache explicitly.

- **[ThreadPoolExecutor overhead for few VMs]** → For 1-2 running VMs, thread overhead may exceed sequential time. Mitigated by: only use threads when there are 3+ VMs to resolve; fall back to sequential for fewer.

- **[Circular imports from cache.py importing ProxmoxClient]** → Mitigated by: using lazy imports (`from proxmate.core.proxmox import ProxmoxClient` inside function bodies, not at module level).
