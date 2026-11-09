# Browser Scheduling and Heartbeat

Updated: 2026-11-09

## Root Cause Analysis

**Error:** The heartbeat performed random navigation, filtering, and favorites
while the main delivery pipeline also scheduled browsing. A shared browser lock
serialized actions but did not coordinate their purpose, frequency, or page
context. Cookie replacement could overlap an HTTP request, and shutdown could
close the browser while its heartbeat thread was still active.

**Expected:** Delivery and detail extraction own the browser during their
operations. Maintenance should yield when busy. Optional browsing should happen
only at known points in the main flow, without modifying search filters or
favorites.

**Cause:** Two independent action schedulers, no shared browsing cooldown, no
session synchronization, and no heartbeat join before browser shutdown.

**Fix:**

- `BossDP._heartbeat_once()` checks the current target and synchronizes cookies.
  The default interval is 60 seconds; the existing urgent event can wake it early.
- It acquires the browser and session locks without waiting. A busy lock skips
  that round. Both locks are released on exceptions.
- CDP target/cookie reads use a two-second timeout. A redirect to the platform
  homepage restores the configured search URL with no retry and a five-second
  navigation timeout. Known login/verification routes and external pages are
  left alone. Normal detail/chat pages are not navigated by heartbeat.
- Background browser support additionally records known login/verification routes
  for the main flow to handle. The heartbeat does not switch browser modes and
  skips all checks while interactive login is in progress. See
  [quiet-startup.md](quiet-startup.md) for mode switching and current validation.
- This is page monitoring and cookie synchronization, not proof of successful
  authentication or a guarantee that a server-side session is renewed.
- All optional list browsing uses `_human_navigate_interlude()`. It only scrolls
  search pages and observes a shared 60-second cooldown after a browsing action.
  Legacy crawler triggers use the same entry. Random detail visits, filter
  changes, and automatic favorites have been removed.
- `HUMANIZE_ENABLE=false` disables optional list browsing, delivery scrolling,
  and simulated typing delays. Required page loading and company-page scrolling
  for lazy-loaded data remain part of extraction.
- `HUMAN_EVERY_N=0` disables the post-delivery browsing hook. It does not disable
  heartbeat or the independently scheduled search-batch browsing hook.
- Session requests and cookie/header replacement share one lock. Per-job referers
  are merged into each request and do not overwrite subsequent list requests.
- Heartbeat startup is idempotent. Shutdown sets the stop event, wakes and joins
  the worker, then closes the browser. Result-saving errors still close it.
- The panel no longer offers an automatic-favorite threshold. Existing
  `FAVORITE_SCORE` values remain readable for compatibility but have no effect.

**Prevention:** `tests/test_runtime_coordination.py` covers busy locks, urgent
wakeup, idempotent startup, stop ordering, exception cleanup, cookie synchronization,
request-local headers, page guards, cooldown sharing, and disabled browsing.

## Validation

The project Conda environment is `D:\ProgramData\miniconda3\envs\autodeliver`.

```powershell
$env:PYTHONUTF8 = '1'
$env:QT_QPA_PLATFORM = 'offscreen'
& 'D:\ProgramData\miniconda3\envs\autodeliver\python.exe' -m pytest tests -q
```

Result: 341 passed, 114 subtests passed.

An isolated headless Chromium instance with a temporary profile also verified
`Target.getTargetInfo`, `Network.getCookies`, and bounded navigation to
`about:blank`. It used the project's `_pick_free_port()` helper because
DrissionPage's `auto_port()` and `set_user_data_path()` conflict in this version.

No real-account deliveries, messages, favorites, or live-site authentication
experiments were performed. These results establish scheduling and integration
behavior, not improved delivery speed or reduced platform enforcement.
