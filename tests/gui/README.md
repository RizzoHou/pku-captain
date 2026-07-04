# GUI test harness

Headless end-to-end tests that build the **real** `MainWindow` and pump the three real worker `QThread`s the way the app runs — so an agent working offline can catch live-GUI breakage the captain would otherwise only see on his Mac. This is distinct from the rest of the suite, which tests leaf widgets or drives unbound handlers over hand-rolled stubs and never constructs a whole window.

Everything offline is deterministic and network-free (`EchoLLMProvider` + the offline tool subset + a tmp `secrets/`/`data/`). No new dependency: **pytest-qt is not installed and must not be added** — the harness rolls its own event-loop waiting.

## Running

```bash
.venv/bin/pytest tests/gui/                 # offline suite (online test auto-skips)
.venv/bin/pytest tests/                      # whole suite, still network-free

# opt-in ONLINE mode — real secrets/, real model (costs tokens), real PKU endpoints:
PKU_CAPTAIN_GUI_ONLINE=1 .venv/bin/pytest tests/gui/test_gui_online.py -s
```

## How it works (`tests/conftest.py`)

The harness backbone lives in the shared `tests/conftest.py`:

- **`qapp`** — one session-wide `QApplication` (offscreen; the platform is forced before any Qt import).
- **`wait_for_signal(signal, timeout_ms=5000, *, trigger=None)`** — the primitive the suite lacked. Spins a nested `QEventLoop` (with a `QTimer` timeout), returns `True` if the signal fired, `False` on timeout. Pass `trigger` to emit/click *after* the signal is connected but *before* the loop spins — that closes the connect-then-emit race for a worker that fires almost immediately. **Assert on the return value** so a worker thread that never emits fails loudly instead of passing vacuously.
- **`wait_until(predicate, timeout_ms=5000)`** — pump the loop until a non-signal condition holds (a busy flag clearing, a bubble count reaching N).
- **`assistant_texts(window)`** — the rendered body text of every assistant chat bubble (reads `QFrame#MessageBubble[messageRole=assistant] > QLabel#MessageText`). This is "what the user sees."
- **`tmp_secrets`** — redirects the app's whole on-disk state (`secrets/` **and** `data/`) to a tmp tree, so an offline run never reads real credentials nor writes a stray session/cache/inbox into the real `data/`.
- **`main_window`** — a fully-constructed **offline** `MainWindow`, startup refresh settled, torn down through `closeEvent` (which joins the worker threads). Depends on `tmp_secrets`, so it is hermetic.
- **`close_window(window, app)`** — the teardown helper (used directly by the online test, which builds its own live window rather than the offline fixture).

## How to add a GUI test when a new feature ships

Keeping this harness **actively maintained** is the point — a new user-facing feature should come with a headless test that drives it. The recipe:

1. **Find the human-input seam.** A dashboard/chat panel signal (`send_requested`, `refresh_requested`, `partial_refresh_requested`, `model_change_requested`, …) or a button `.click()`. Emitting the signal *is* clicking like a human — prefer it over calling the private handler.
2. **Find where the result lands.** A worker `finished` signal (`_agent_worker.finished`, `_dashboard_worker.finished`), a busy flag, or a rendered widget.
3. **Drive → wait → assert:**
   ```python
   def test_my_feature(main_window, qapp, wait_for_signal, assistant_texts):
       window = main_window
       fired = wait_for_signal(
           window._some_worker.finished,
           timeout_ms=15000,
           trigger=lambda: window._some_panel.some_requested.emit(payload),
       )
       assert fired, "worker never finished"
       qapp.processEvents()          # flush the final render
       assert ...                     # assert on rendered state (assistant_texts, a card, a label)
   ```
4. **Stay generic.** Assert on **stable seams** (a bubble rendered, a worker completed, a busy flag cleared), *not* on a specific header button existing or an exact label — those get added/removed/renamed by other work and make the test brittle.
5. **Keep offline deterministic.** Offline uses `EchoLLMProvider` (reply is `echo: <message>`) and the offline tool subset (networked tools are unregistered, so their cards report errors — that is expected). If your feature needs live data, cover it in the **online** test (`test_gui_online.py`) behind the `PKU_CAPTAIN_GUI_ONLINE` gate instead.
6. **New app-state sink?** If your feature wires a new disk-writing store into `MainWindow`, add one line to the `tmp_secrets` fixture redirecting it (see the note there about the default-argument binding gotcha), so tests stay hermetic.

## Files

- `test_gui_smoke.py` — offline flagship: window builds, a real chat turn renders its reply, a real dashboard refresh completes, two turns render distinct bubbles.
- `test_gui_online.py` — opt-in live round-trip; asserts online mode didn't silently fall back, then drives a real turn + refresh.
