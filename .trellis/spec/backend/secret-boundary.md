# Secret Boundary (Output Redaction)

## 1. Scope / Trigger

This contract applies to the PR-S2 secret boundary in `lion_code/tooling/`:
`SecretStore`, `OutputSanitizerMiddleware`, and their Composition Root
bindings. The trigger is a data-flow invariant: every tool result passes the
sanitizer before its content becomes model-visible, enters the `ResultStore`,
or is written to the execution audit.

The plane is redact-only. It does not block tool calls, does not inject
credentials into subprocesses (deferred until dedicated tools exist), and adds
no permission semantics.

## 2. Signatures

```python
class SecretStore:
    def __init__(self, values: Mapping[str, str], key: bytes) -> None: ...
    def fingerprints(self) -> frozenset[str]: ...
    def matches(self, text: str) -> bool: ...

def load_secret_store(
    *, workspace: Path, key_file: Path,
    environ: Mapping[str, str] | None = None,
) -> SecretStore: ...

class OutputSanitizerMiddleware:
    phase: Literal["post"] = "post"
```

`ToolBindings` owns the optional concrete service and switch:
`secret_store: SecretStore | None`, `enable_secret_boundary: bool = True`.
The Composition Root creates the default lazily from `foundation.cwd` plus
`~/.lion_code/sanitizer.key`.

## 3. Contracts

### Registration

- Sources: the workspace `.env` file (full body) and process-environment
  entries whose names end with `_KEY`, `_TOKEN`, `_SECRET`, or `_PASSWORD`
  (case-insensitive). Registering process env is load-bearing: without it
  `printenv` on the agent's own API key is a live T1 hole.
- Only `.env` itself is parsed, never `.env.example`-style templates:
  placeholder values would cause mass false-positive redaction.
- Values shorter than `MIN_SECRET_LENGTH` (8) are not registered; short
  values would redact ordinary tokens.

### Fingerprints

- Each registered value produces `HMAC-SHA256(value)` and
  `HMAC-SHA256(base64(value))`, keyed by `~/.lion_code/sanitizer.key`
  (auto-generated once, permissions tightened best-effort; no rotation, no
  configuration surface).
- Plaintext values never leave `SecretStore`: only fingerprints and the
  boolean `matches` query are exposed.

### Sanitization

- Position: first post-phase middleware, so redaction precedes
  `ResultPolicyMiddleware` persistence and `AuditMiddleware` recording.
- Granularity: line-level candidates first (bare value on its own line,
  `KEY="value with spaces"`), then token-level candidates. Tokens split on
  whitespace, quotes, backticks, and angle brackets; delimiters `"/"` and
  `"="` are excluded because both occur in the base64 alphabet/padding and
  splitting on them would break whole-form fingerprint matches.
- Candidate forms per chunk: the raw chunk, the chunk stripped of edge
  punctuation, and the value after the last `=`. Comparison is one HMAC per
  candidate; whole-output sliding-window hashing is forbidden.
- Hits are counted into `result.details["sanitizer_hits"]` and flow into
  `ExecutionEvent.sanitizer_hits`.
- An empty store short-circuits: unchanged result, no `sanitizer_hits` key.

### Honesty boundary

Redaction is closed only for registered secrets. Discovery completeness
(unregistered hardcoded credentials) is an explicit residual risk recorded in
`docs/security-design.md`; the scanner layer is an audit signal, not a
boundary.

## 4. Architecture

- All code lives in `lion_code/tooling/` (Kernel tooling subsystem); the
  middleware rewrites content only and never participates in allow/deny
  decisions.
- Forbidden: plaintext secret values in `ToolResult` content, audit rows, or
  any model-visible channel.
