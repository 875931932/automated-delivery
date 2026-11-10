# Quiet Startup and Background Browser

Updated: 2026-11-10

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
- The heartbeat signals known login routes for the main flow to handle between
  browser operations. Known security routes stop the run. The heartbeat does
  not restart the browser or alter the QR page while login is in progress.
- Login polling does not periodically reload the QR code. A positive
  `LOGIN_WAIT` stops the task on expiry; zero continues waiting.
- A known security route or visible restriction alert interrupts the run with
  exit code 3. Results already completed are saved; the panel shows `平台限制`.
  The task does not automatically repeat the action or resume. Review the
  official page before restarting. See [runtime-heartbeat.md](runtime-heartbeat.md).

Login checks still depend on the site's rendered `.nav-figure` element and known
login/security routes. These checks are not a guarantee of server authentication
or live-site compatibility. Session storage tied to an individual tab is not
transferred when Chromium restarts.

## Result Links

The results table includes a job-link icon beside the job title. Both that icon
and the drawer's open-link action launch the project browser discovered by
`resolve_browser_path`, honoring saved `BROWSER_PATH`, with the corresponding
platform's existing profile and `Default` profile directory. BOSS also reuses
its saved user agent. No cookies are copied to another directory or the system
default browser. Old records without a platform infer it from the official job
URL; missing, unsupported, or mismatched links do not launch a browser.

This requires `KEEP_LOGIN=true`. A task using a temporary profile cannot provide
the same login after it ends, so the panel reports that condition instead of
silently opening a different profile. An active task blocks the open action.
The launcher also detects an externally started headless browser using that
exact platform profile. A visible project browser can accept further windows
with the same profile. Before the next task starts, the panel checks that its
selected platforms' profile directories are free and asks the user to close
those browser windows; it does not kill the manual browser.

Persistent task profiles and manually opened result windows use
`--restore-last-session` to preserve session cookies across a normal browser
exit. Previous tabs may also be restored. This is Chromium session restoration,
not a guarantee that the platform has not expired or revoked the login. The
behavior follows Chromium's [user data directory documentation](https://chromium.googlesource.com/chromium/src/+/main/docs/user_data_dir.md),
which specifies `--user-data-dir` and notes that two browser instances cannot
share a user data directory concurrently.

Manual result links do not start scoring, sending, or application workflows.
Liepin automation remains paused; a user can still explicitly open its historical
job links in that platform's existing browser profile.

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

For the result-link change (2026-11-10), `scripts/verify_result_browser.py` uses a
temporary browser profile and localhost to check persistent cookies, session
cookies, local storage, a visible result window, and profile-conflict detection.
It also checks reopening the same profile in background mode after manual
viewing. It does not access recruiting sites or personal browser profiles.
Screenshots at 1420 x 900 and 1180 x 760 cover the new column and missing-link
disabled state. Focused Qt tests cover sorting, filtering, the drawer action,
and error messages.

Final result-link validation: 475 tests and 202 subtests passed; all 8 localhost
browser checks passed, including return to the actual task browser opener.
Sensitive-data scan and `git diff --check` passed. The existing `psutil`
dependency from DrissionPage is now declared directly because result opening
uses its process inspection API. No EXE or installer was rebuilt.
