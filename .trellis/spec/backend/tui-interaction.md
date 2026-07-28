# TUI Input and Completion Contracts

## 1. Scope / Trigger

Use these contracts when changing terminal file-drop handling or the autocomplete
window in `lion_code/tui/`. Both paths translate terminal-dependent text or Rich
rendering into user-visible prompt state, so byte-level parsing and rendered rows
must be tested rather than inferred from item counts.

## 2. Signatures

```python
def normalize_dropped_paths(text: str) -> str | None: ...

def _visible_completion_state(
    state: CompletionState,
    *,
    max_lines: int,
    width: int | None = None,
) -> CompletionState: ...
```

## 3. Contracts

### File drop

- Return normalized prompt text only when the entire paste is one or more existing
  absolute local paths.
- Try the complete paste first, then POSIX `shlex`, then non-POSIX `shlex` so
  Windows drive letters and backslashes survive quoted or multi-path input.
- Accept only local `file://` URIs and convert them with `url2pathname()`.
- Quote paths containing whitespace without rewriting their path separators.
- Return `None` for prose, relative paths, missing paths, remote URI hosts, or mixed
  valid/invalid tokens so Textual can perform normal paste handling.

### Completion window

- `max_lines` is a rendered-line budget, not an item-count budget.
- With a positive `width`, measure the complete Rich table. Measuring each item in
  isolation is invalid because the longest display value changes the shared
  description column width and therefore wrapping.
- Preserve the selected item and return an index valid for the returned slice.
- Empty input or a non-positive budget returns an empty state. If the selected item
  alone renders beyond the budget, preserving it takes precedence over the limit.

## 4. Validation and Error Matrix

| Input or state | Result |
|---|---|
| Existing absolute path | Normalized path |
| Quoted Windows paths | Quotes removed for validation; separators preserved |
| Local `file://` URI | Platform-native local path |
| Relative, missing, remote, mixed, or prose paste | `None` |
| Empty completion state or `max_lines <= 0` | Empty `CompletionState` |
| Selected index outside item bounds | Clamp before slicing |
| Positive width | Measure full rendered table |

## 5. Good / Base / Bad Cases

- Good: `"C:\\work files\\a.txt" "D:\\b.txt"` becomes two validated prompt paths.
- Base: a single existing absolute path passes through, with quotes added only when
  it contains whitespace.
- Bad: `summarize C:\\work\\a.txt` is not a drop because the whole paste is not a
  path list.
- Good: a completion table with a long command and long descriptions is sliced by
  the rows produced at the widget width.
- Bad: slicing 16 items can still render far more than 16 lines.

## 6. Tests Required

- File-drop unit tests: bare, quoted, multi-path, URI, whitespace, missing, relative,
  prose, unbalanced quote, Windows separator preservation, and PromptInput fallback.
- Completion unit tests: category headers, category gaps, selected-item visibility,
  wrapped descriptions, full-table column-width effects, invalid indexes, and zero
  budget.
- Run `tests/tui/test_tui_file_drop.py`, `tests/tui/test_tui_app.py`, and the full
  test suite before completion.

## 7. Wrong vs Correct

### Wrong

```python
tokens = shlex.split(text, posix=True)  # destroys Windows backslashes
visible = state.items[:16]              # 16 items can render as 40 lines
```

### Correct

```python
paths = _tokens_to_paths(text, posix=True)
if paths is None:
    paths = _tokens_to_paths(text, posix=False)

visible = _visible_completion_state(state, max_lines=16, width=widget_width)
```
