# Egress Guard

## 1. Scope / Trigger

This contract applies to the PR-S3 egress guard in `lion_code/tooling/`:
`EgressWhitelist`, `EgressGuardMiddleware` (pre phase, after
`PermissionMiddleware`), and their Composition Root bindings. The trust
domain is explicitly `{local machine + LLM Provider}`: provider traffic
never passes through this guard; the guard only controls Agent tool
egress.

Two honest promise levels:

| Level | Exit | Promise | Basis |
|-------|------|---------|-------|
| A | `web_fetch` (the only in-process exit today) | guaranteed | guard sits before execution |
| B | URLs inside `run_shell` commands | best effort | observation only, no blocking, no command-intent analysis |

## 2. Signatures

```python
class EgressWhitelist:
    def allows(self, host: str | None) -> bool: ...
    @classmethod
    def from_sources(cls, *, home, cwd, provider_hosts=frozenset()) -> EgressWhitelist

class EgressGuardMiddleware:
    phase: Literal["pre"] = "pre"
```

`ToolBindings` owns `egress_whitelist: EgressWhitelist | None` and
`enable_egress_guard: bool = True`. The Composition Root derives provider
hosts from `config.anthropic_base_url or DEFAULT_ANTHROPIC_BASE_URL` and
builds the default lazily.

## 3. Contracts

### Whitelist (deny-by-default, audit-driven growth)

- Initial set: provider endpoint hosts only. Users add hosts via
  `egress.allow_hosts` in `.claude/settings.json` (home then project, same
  discovery pattern as permission rules). High-frequency Level B
  destinations in the audit are the intended candidates for whitelisting.
- Matching is exact-host (case-insensitive). No path/query/suffix logic.

### Level A (web_fetch)

- Resolve `url` → host; not whitelisted → block before execution:
  `ToolResult(is_error=True)` with details
  `egress_blocked=True, egress_destination=<host>`; the audit row records
  `result="blocked"` and the destination.
- If whitelisted, fingerprint-scan the full URL (whole URL, whole path,
  each path segment, each query value) against the SecretStore; a hit
  blocks with `fingerprint_hit=True`. GET queries are an exfil channel.
- The S4-absence fallback is block + audit. No interim confirmation flow
  may be invented for egress.

### Level B (run_shell)

- Extract `http(s)://` URLs from the command string; record
  `destination` (unique hosts joined by `,`) and `best_effort=true` on the
  audit row. Never blocks, never parses intent.
- Adding new egress-capable tools requires extending the guard's tool
  coverage; `docs/advanced-capability-guide.md` records this as an
  architecture gate (ToolRuntime is the only tool path).

### Audit schema

`ExecutionEvent.best_effort` and `destination` (existing) are populated
from result details (`egress_destination`, `egress_best_effort`,
`fingerprint_hit`, `egress_blocked` → `result="blocked"`).

## 4. Deferred

- Direction dimension (fetch vs push) is deferred until a second
  direction-producing fact source exists (S4 sandbox or dedicated tools).
- Full shell-subprocess network blocking is deferred to the S4 sandbox;
  Level B stays observational by design, not by omission.
