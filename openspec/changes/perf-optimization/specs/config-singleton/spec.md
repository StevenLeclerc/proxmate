## ADDED Requirements

### Requirement: Config loaded once per process
The `load_config()` function SHALL cache its result in a module-level variable after the first successful load. Subsequent calls within the same process SHALL return the cached instance without reading from disk.

#### Scenario: First call reads from disk
- **WHEN** `load_config()` is called for the first time in a process
- **THEN** it SHALL read and parse `~/.proxmate/config.yaml` and store the result in memory

#### Scenario: Subsequent calls return cached config
- **WHEN** `load_config()` is called a second or subsequent time in the same process
- **THEN** it SHALL return the previously cached `AppConfig` instance without reading from disk

### Requirement: Cache invalidated on config write
The config cache SHALL be cleared whenever configuration is written to disk, so that subsequent reads reflect the latest state.

#### Scenario: save_config clears cache
- **WHEN** `save_config(config)` is called
- **THEN** the in-memory config cache SHALL be set to `None`, forcing the next `load_config()` to read from disk

#### Scenario: set_context clears cache
- **WHEN** `set_context(name)` is called and successfully changes the context
- **THEN** the in-memory config cache SHALL be cleared

#### Scenario: add_context clears cache
- **WHEN** `add_context(name, context)` is called
- **THEN** the in-memory config cache SHALL be cleared

#### Scenario: remove_context clears cache
- **WHEN** `remove_context(name)` is called
- **THEN** the in-memory config cache SHALL be cleared
