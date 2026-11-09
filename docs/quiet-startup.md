# Quiet Startup and Background Browser

Updated: 2026-11-09

## Starting the Panel

Double-click `启动面板.vbs` in the project directory. It starts `pythonw.exe`
directly, without a terminal or Conda activation shell. The existing
`python desktop_panel.py` entry also includes the widget fix below, but retains
the terminal from which it was launched.

The launcher checks `AUTODELIVER_PYTHONW`, the project's `.venv`, the current
machine's `autodeliver` Conda environment, and the user Miniconda environment.
Startup errors go to `%APPDATA%\AutoDeliver\panel-startup.log`.

## Why Windows Were Flashing

The main reported symptom was caused by Qt widgets, not just subprocess consoles.
`FieldBlock`, `ToggleRow`, `SectionCard`, and `EmptyState` created labels without
parents and called `setVisible(True)` before adding them to their layouts. Qt
briefly displayed each label as an independent top-level window with the default
Python application title, then hid it when the layout adopted it.

A `QEvent.Show` probe reproduced 85 extra windows during complete panel
construction: 37 field titles, 33 field notes, and 15 section subtitles. Labels
now receive their owning widget at construction, before visibility is set.
The same probe reports zero extra windows after the change.

The VBS launcher must use normal window display for `pythonw`: hiding its first
GUI window would hide the main panel once the accidental windows are removed.
`pythonw` itself does not allocate a console.

Separate process fixes prevent worker launch, `taskkill`, browser cleanup, and
dependency probes such as `platform`'s `ver` command from opening consoles.
When the panel runs under `pythonw`, its worker uses the sibling `python.exe`
with `CREATE_NO_WINDOW`, preserving log output through pipes. Explicit
`CREATE_NEW_CONSOLE` calls remain supported.

## Background Browser Behavior

`BROWSER_BACKGROUND=true` is the default and is available in advanced settings.
It uses Chromium's headless mode. Simply hiding a headed browser was rejected
after an actual test showed that opening a background tab made it visible again.

- A valid existing login stays headless, including new detail and chat tabs.
- If login is not detected, the main flow opens an interactive browser for login.
- The same isolated profile, stable user agent, and in-memory cookie snapshot
  are reused when switching modes. Cached detail tabs are invalidated.
- After login, the browser returns to headless mode and checks the rendered
  avatar again. If this check fails, it keeps a visible browser for that run
  instead of switching repeatedly. Disabling the setting always uses a visible
  browser.
- The heartbeat only signals known login/security routes. The main flow handles
  them between browser operations. The heartbeat does not restart the browser
  or alter the QR page while login is in progress.
- Login polling does not periodically reload the QR code. A positive
  `LOGIN_WAIT` stops the task on expiry; zero continues waiting.
- A verification interruption after clicking a communication button is reported
  as a chat failure; it does not automatically repeat that action.

Login checks still depend on the site's rendered `.nav-figure` element and known
login/security routes. These checks are not a guarantee of server authentication
or live-site compatibility. Session storage tied to an individual tab is not
transferred when Chromium restarts.

## Verification

```powershell
$env:PYTHONUTF8 = '1'
$env:QT_QPA_PLATFORM = 'offscreen'
& 'D:\ProgramData\miniconda3\envs\autodeliver\python.exe' -m pytest tests -q
& 'D:\ProgramData\miniconda3\envs\autodeliver\python.exe' scripts/verify_quiet_startup.py
& 'D:\ProgramData\miniconda3\envs\autodeliver\python.exe' scripts/verify_quiet_browser.py
```

- Regression suite: 356 passed, 115 subtests passed.
- Isolated VBS/pythonw startup: panel shown, zero extra top-level Qt windows,
  zero new visible console windows, 1.44 seconds to ready in the final run.
  This is one local smoke measurement, not a cold-start performance guarantee.
- Actual Chrome using a temporary profile and local HTTP fixture: no visible
  window before or after new tabs; interactive login window shown; headless mode
  restored; session cookie, local storage, and profile preserved.
- The browser smoke test intentionally shows one temporary login window. The
  panel smoke test briefly shows an isolated panel and closes it automatically.
  Both clean up only their own test instances. Neither starts a real delivery,
  sends a message, uses an AI service, or tests a real account on the platform.

The initial console-only smoke check missed the Qt label windows. The startup
checks now cover both console visibility and every top-level Qt show event.
