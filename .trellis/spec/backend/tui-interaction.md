# TUI Input, Completion, and Streaming Transcript Contracts

## 1. Scope / Trigger

Use these contracts when changing terminal file-drop handling, the autocomplete
window, or streamed transcript rendering in `lion_code/tui/`. These paths translate
terminal-dependent input or session events into user-visible state, so parsing,
rendered rows, and mounted-widget identity must be tested directly.

## 2. Signatures

```python
def normalize_dropped_paths(text: str) -> str | None: ...

def _visible_completion_state(
    state: CompletionState,
    *,
    max_lines: int,
    width: int | None = None,
) -> CompletionState: ...

async def LionTuiApp._apply_streaming_transcript_event(
    event: LionSessionEvent,
    *,
    previous_item_count: int,
) -> None: ...
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

### Streaming transcript

- Apply every event to `TuiEventAdapter` first; `TuiState` remains the canonical
  projection used to reconcile final messages and tool results.
- Append text and thinking deltas through `TranscriptView`'s streaming methods so
  each fragment reaches `MarkdownStream.write()` without rebuilding transcript
  history.
- Reconcile a normal `MessageEndEvent` against canonical items by finalizing the
  active widget or replacing only the provisional assistant tail. Tool start,
  update, and end events append or update their row in place.
- When finalizing a single text block, bind the streamed widget to its canonical
  `ChatItem` and advance `TranscriptView._window_end` to include that item. Leaving
  the boundary behind makes the next turn look off-window and drops its live deltas.
- A terminal error or abort may perform one full state redraw so partial output and
  the error row cannot be lost. Normal streaming events must not call
  `TranscriptView.update_from_state()`.

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
| Text/thinking delta | Append only to the active streaming tail; no full redraw |
| Normal single-text `MessageEndEvent` | Bind canonical item and advance window end |
| Structured assistant message | Replace only this turn's provisional tail |
| Tool progress/result | Update the mounted tool row in place |
| Error or aborted message end | One terminal full-state reconciliation is allowed |

## 5. Good / Base / Bad Cases

- Good: `"C:\\work files\\a.txt" "D:\\b.txt"` becomes two validated prompt paths.
- Base: a single existing absolute path passes through, with quotes added only when
  it contains whitespace.
- Bad: `summarize C:\\work\\a.txt` is not a drop because the whole paste is not a
  path list.
- Good: a completion table with a long command and long descriptions is sliced by
  the rows produced at the widget width.
- Bad: slicing 16 items can still render far more than 16 lines.
- Good: two provider fragments call `MarkdownStream.write()` twice while every
  historical widget keeps its identity.
- Base: a normal message end finalizes the active widget, binds its canonical item,
  and leaves the transcript window at `len(state.items)`.
- Bad: calling `update_from_state()` for each fragment remounts history; binding the
  canonical item without advancing `_window_end` suppresses the next turn's stream.

## 6. Tests Required

- File-drop unit tests: bare, quoted, multi-path, URI, whitespace, missing, relative,
  prose, unbalanced quote, Windows separator preservation, and PromptInput fallback.
- Completion unit tests: category headers, category gaps, selected-item visibility,
  wrapped descriptions, full-table column-width effects, invalid indexes, and zero
  budget.
- Streaming Textual test: two consecutive text deltas reach `MarkdownStream` as
  separate fragments, a mounted history widget keeps its identity, no full redraw
  occurs, `MessageEndEvent` matches the canonical assistant item, and the mounted
  window end equals the canonical item count.
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

```python
# Wrong: remounts every historical message for each provider fragment.
adapter.apply(event)
transcript.update_from_state(state)

# Correct: update canonical state, then mutate only the active transcript tail.
adapter.apply(event)
await app._apply_streaming_transcript_event(
    event,
    previous_item_count=previous_item_count,
)
```
