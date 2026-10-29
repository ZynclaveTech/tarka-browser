# Task 1 spike: why YouTube doesn't float, and the hooks (Chromium 156)

2026-10-29. Throwaway. Sources are `chromium/src@156.0.8078.47`. No ungoogled or
Tark patch touches them, except ChromeActivity.java (captions-ui.patch and
speech-language-snackbar.patch, elsewhere in the file).

**Verdict: FLOATS.** Confirmed on emulator-5554 with a throwaway build of the
three hooks (job jobs/tark-build-20261029-160149, build and junit passed). YouTube
floats inline and from fullscreen, keeps playing, and the page never sees
`hidden`. No page-side tricks were used (see "Spike build result").

## (d) Why YouTube doesn't float (emulator-5554, m.youtube.com/watch)

How it was measured: remote DevTools over `localabstract:chrome_devtools_remote`.
A logging script went in through `Runtime.evaluate`; it wraps `pause`, `load`,
`removeAttribute` and the `src` setter with caller stacks.

- The `<video>` has `disablePictureInPicture === true`, and `document.pictureInPictureEnabled === true`.
- The fullscreen element is `DIV#player-container-id`, a container.

Four causes:

1. **YouTube tears the player down on `visibilitychange: hidden`, inline and fullscreen.**
   - About 30 ms after the event, its player (`base.js`, `g.fZ.ib` → `removeAttribute('src')`, `g.fZ.load` → `load()`) fires `emptied` and resets `currentTime` to 0.
   - When you come back, it sets a new blob `src`.
2. **`disablePictureInPicture` stops both PiP paths.**
   - Activity PiP needs `isPictureInPictureAllowedForFullscreenVideo()` (FullscreenVideoPictureInPictureController.java:217-218).
   - Video PiP gets `kDisabledByAttribute` (document_picture_in_picture/picture_in_picture_controller_impl.cc:129-130, checked again in `OnEnteredPictureInPicture` :247).
3. **The fullscreen activity PiP doesn't work for YouTube even when allowed.**
   - Test: visibility event swallowed, attribute cleared, fullscreen + home.
   - Android does enter `mode=pinned` (page 228x128). Then HTML fullscreen ends, YouTube calls `pauseVideo()`, and the PiP closes.
4. **Chromium pauses hidden inline video itself.**
   - With visibility swallowed in the page, inline + home still gets a `pause` that no script called. That pause is `WebMediaPlayerImpl`, chain (a).

What works (page-side emulation on stock 156-r1): visibility held, attribute cleared, and **video PiP** (`PictureInPictureActivity`) entered before home.
- Inline: it floats and plays (49 s → 66 s during 15 s at home).
- From fullscreen: video PiP exits HTML fullscreen while Tark is still in front, so YouTube doesn't pause. It floats and plays (85 s → 99 s).
- With visibility held but no PiP, inline video is paused by Chromium. So Background play needs the hold too.

## (a) What pauses hidden video

`WebContentsImpl::WasHidden` (web_contents_impl.cc:3184)
→ `UpdateVisibilityAndNotifyPageAndView` (:5285)
→ `RenderViewHostImpl::SetFrameTreeVisibility` (render_view_host_impl.cc:712)
→ `PageLifecycleStateManager::SetFrameTreeVisibility` / `SendUpdatesToRendererIfNeeded` (page_lifecycle_state_manager.cc:77, :194, :222)
→ `RendererWebMediaPlayerDelegate::OnPageVisibilityChanged` (content/renderer/media/renderer_web_media_player_delegate.cc:192, :237)
→ `WebMediaPlayerImpl::OnPageHidden` (third_party/blink/renderer/platform/media/web_media_player_impl.cc:2643)
→ `UpdateBackgroundVideoOptimizationState` (:3825)
→ `ShouldPausePlaybackWhenHidden` (:3744)
→ `PauseVideoIfNeeded(kPageHidden)` (:3859)
→ `HTMLMediaElement::PausePlayback` (html_media_element.cc:5174).

- Background suspend is on for Android: `IsBackgroundSuspendEnabled` :171, render_frame_media_playback_options.h:22.
- `allow_background_video_playback_` is cleared in `OnPageHidden` :2647.
- Video in video PiP is exempt (:3765).
- `IsPageHidden()` (:3636 → delegate :58) reads the page's visibility, the same state as `document.visibilityState`. MediaSession suspend isn't involved.

**Hook:** nothing in WMPI; the visibility hold (b) keeps `IsPageHidden()` false.

## (b) How visibility reaches Blink, and where to hold it per tab

In `UpdateVisibilityAndNotifyPageAndView` (:5285):
- `CalculatePageVisibilityState` (:5255) returns `kHidden`, or `kHiddenButPainting` while a video is in PiP (:5274). Script sees `hidden` either way, so the hold must also cover PiP.
- `update_frame_tree_visibility` (:5337-5354) → `SetFrameTreeVisibility` sets the page's (script's) visibility.
- `SetPrimaryMainFrameViewVisibility` (:5424) hides the widget, so compositing stops.

**Hook (narrowest):**
- Bind `kVisible` into `update_frame_tree_visibility` when `tark_media::ShouldHoldVisibility(this)` (audible, setting on).
- Leave the view, observers and `SetActive` on the real value.
- **Release:** `WebContentsImpl::OnAudioStateChanged` (:3124) re-runs the update when the tab goes quiet. The spike doesn't do this; Task 2 must.

## (c) Entering video PiP from Java; inline `<video>`

There are two paths in 156:

- **Activity PiP (fullscreen only):**
  - `ChromeActivity.onUserLeaveHint` (ChromeActivity.java:1545) → `FullscreenVideoPictureInPictureController.attemptPictureInPicture` (:314), gated at :208/:217.
  - On Android 12+ it also uses `setAutoEnterEnabled` (:642).
  - It doesn't cover inline video and fails for YouTube (cause 3).
- **Video PiP (what `requestPictureInPicture()` uses):**
  - `PictureInPictureControllerImpl::EnterPictureInPicture` (:138) → `EnterPictureInPictureInternal` (:151), which exits fullscreen first (:175) → `StartSession` (:209) → `PictureInPictureActivity`.
  - Works for inline.
  - Browser-initiated route: `MediaSessionImpl::EnterPictureInPicture` (media_session_impl.cc:1326). It routes to the page's handler if there is one, and otherwise needs exactly one player (:1340).
  - From there: `MediaSessionController::OnEnterPictureInPicture` (media_session_controller.cc:100) → `HTMLVideoElement::RequestEnterPictureInPicture` (html_video_element.cc:737, :750, with no promise).
  - Java `MediaSession.didReceiveAction` (media_session_android.cc:197) only reaches page handlers.

**Hooks:**
- **Java:** `ChromeActivity.onUserLeaveHint`, before the fullscreen controller (:1562). When the tab plays media with sound, call Tark's PiP and return. Use this on every Android version: `setAutoEnterEnabled` only applies to activity PiP.
- **C++ (new JNI, e.g. `TarkPictureInPicture.enter(WebContents)`):**
  - Pick the playing video player in `MediaSessionImpl::normal_players_` (`HasVideo && !IsPaused`) and call `observer->OnEnterPictureInPicture(id, nullopt)`.
  - This skips the page handler and the one-player rule.
- **Blink:** in `OnEnteredPictureInPicture` (:247), treat `kDisabledByAttribute` as enabled when `!resolver && !is_immersive`. Page-initiated requests still honour the attribute.

## Prototype and build

- `android/pip/spike/pip-spike.patch` (not in `series`) has the three hooks, unconditional.
  - Files: web_contents_impl.cc, media_session_impl.cc (via `DidReceiveAction(kEnterPictureInPicture, null details)`, to avoid JNI), picture_in_picture_controller_impl.cc, ChromeActivity.java.
  - It dry-runs clean on the 156 pre-state.
- It's built from the local throwaway branch `spike/pip-build`. Base hash checked: machine stamp = prep_hash --base with the 156 submodule = 0b14435744fc.
- **Main can't build Android today**, which is a finding apart from PiP:
  - `android/desktop-only-patches.txt` lacks `tarka/linux/`, so `tarka/linux/captions.patch` fails.
  - `adblock-desktop.patch`'s `chrome.release` hunk (from #58) assumes the Windows patches, which Android skips.
  - The spike branch works around both.
- The 16:01 job ran after the Linux `--fresh` build finished. The base stamp was re-checked first and still read 0b14435744fc. The APK installed over 156-r1 (same key).

## Spike build result (emulator-5554, m.youtube.com, video unmuted, then home)

- **Inline:**
  - The `<video>` still has `disablePictureInPicture=true`.
  - On home: `enterpictureinpicture`, `PictureInPictureActivity` pinned, no `visibilitychange`, no `emptied`.
  - Playing 14.3 s → 29.6 s during 15 s at home. `visibilityState` is still `visible`.
  - `Tark PiP spike: entering video PiP` was logged once.
- **Fullscreen** (YouTube's `DIV#player-container-id`):
  - On home: `enterpictureinpicture`, then `fullscreenchange el=null`, and YouTube doesn't pause.
  - It floats and plays 41.1 s → 56.4 s.
- **Not covered by the spike, so Tasks 2–4 must test:**
  - Releasing the hold when the tab goes quiet (no `OnAudioStateChanged` re-run yet).
  - A page with nothing playing still getting `hidden`.
  - Background play with PiP off (sound only).
  - The Esc toast. Activity PiP is no longer used for media tabs, so it may simply not appear.
  - Android 12+ `setAutoEnterEnabled`. Not needed: `onUserLeaveHint` worked on API 36.
  - Settings gating.

## What a phone run would add (not run: needs the user's OK)

- **The user's actual failing case:** real youtube.com and m.youtube.com, signed in, with ads (a pre-roll changes the player count).
- **Real home gestures:** gesture navigation's swipe-home, which can skip or delay `onUserLeaveHint` compared with the emulator's keyevent.
- **The lock screen:** the release-gate item.
- **Background survival:** the media notification's play/pause, and whether the foreground service keeps playback alive under the OEM's battery management.
- **Network:** QUIC, which fails on the emulator.
- **Signing:** a release-key-signed APK.
