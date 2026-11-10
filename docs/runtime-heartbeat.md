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
- Background browser support records known login routes for the main flow to
  handle. A known security route sets a run-wide stop signal instead. The
  heartbeat does not switch browser modes and skips all checks while interactive
  login is in progress. See
  [quiet-startup.md](quiet-startup.md) for mode switching and current validation.
- This is page monitoring and cookie synchronization, not proof of successful
  authentication or a guarantee that a server-side session is renewed.
- All optional list browsing uses `_human_navigate_interlude()`. It scrolls a
  visible search page down once (320 pixels), with a shared 60-second cooldown.
  It never scrolls back up or resets to the top. Headless mode skips optional
  browsing entirely. Legacy crawler triggers use the same entry.
- `HUMANIZE_ENABLE=false` disables optional list browsing. Delivery no longer
  adds scrolling, and greeting input no longer has per-character delays, even
  when the option is enabled. Configured detail/job delays and request pacing
  remain in effect. Company-page scrolling needed for lazy-loaded data remains.
- Post-delivery browsing does not reload an existing search page. Headless mode
  keeps the configured cookie synchronization hook without extra navigation.
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

## Platform Restrictions

- HTTP 401/403/429 stop the run after one request. JSON error messages indicating
  frequent operations, restricted access, abnormal account state, verification,
  or expired login also stop the run. These signals do not prove an account ban.
- API redirects are not followed automatically. Known login/security redirects
  stop the run; other redirects end that query. Transient timeouts and server
  failures retain the bounded retry policy.
- Known security routes are checked before accepting a login avatar. Main-flow
  page checks also inspect visible alerts/dialogs/toasts, not JD text or chat
  history. Hidden messages are ignored. Selectors and routes are necessarily
  limited; unrecognized platform changes may require updates.
- `PlatformAccessStopped` propagates through detail retrieval and delivery to
  the run handler. No subsequent keyword is attempted. Pending completed results
  are saved, heartbeat exits, and the browser closes. The panel shows
  `平台限制` and exit code 3, with a categorized reason in the log. Raw restricted
  responses, credentials, and query tokens are not included in that reason.
- The task does not automatically resume. Check the official page and restart
  manually after resolving the issue. A restriction after clicking Send does
  not establish whether the message was accepted; inspect that conversation
  before restarting. This is not a full delivery-receipt implementation.

## Validation

The project Conda environment is `D:\ProgramData\miniconda3\envs\autodeliver`.

```powershell
$env:PYTHONUTF8 = '1'
$env:QT_QPA_PLATFORM = 'offscreen'
& 'D:\ProgramData\miniconda3\envs\autodeliver\python.exe' -X utf8 -B -m pytest tests -q -p no:cacheprovider
& 'D:\ProgramData\miniconda3\envs\autodeliver\python.exe' -X utf8 -B scripts/verify_platform_stop.py
```

Result after the restrained-browsing update: 425 passed, 176 subtests passed.

The local platform-stop smoke test used actual headless Chromium, a temporary
profile, and only `127.0.0.1`. Ordinary page text and hidden alerts did not stop
the task; a visible restriction alert and a known security route did, without
navigation. The test closes its own browser and server.

The earlier isolated headless Chromium check with a temporary profile verified
`Target.getTargetInfo`, `Network.getCookies`, and bounded navigation to
`about:blank`. It used the project's `_pick_free_port()` helper because
DrissionPage's `auto_port()` and `set_user_data_path()` conflict in this version.

No real-account deliveries, messages, favorites, or live-site authentication
experiments were performed. These results establish scheduling and integration
behavior, not improved delivery speed or reduced platform enforcement.
