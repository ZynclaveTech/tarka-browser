# Task 6 report: Settings, offer and download card

Status: DONE_WITH_CONCERNS. Build-verified: pending (BUILD RULING: nothing compiled or run; Robolectric tests written, not run).

## Patches
### translate-settings-off.patch (rewritten)
- LanguageSettings.java:
  - `hideGoogleTranslateRows(PreferenceGroup)` hides `translation_settings_section` (detailed page) and `translate_switch` (basic page) always. The `--translate-script-url` check and the CommandLine import are gone.
  - `createTarkPageTranslationSwitch(Context, TarkPrefs)` adds the switch "Page translation", with summary "Translates pages on your phone with Tark's own model. Pages never leave your phone." It is non-persistent, reads and writes the profile pref `tark.page_translation.enabled`, and is added after the xlit and voice rows.
  - The helpers are static and package-private so Robolectric can test them. They sit away from voice-languages.patch's hunk contexts, so that patch still applies at -F0.
- browser_ui_prefs.cc registers `tark.page_translation.enabled`, default **true**, Android only.
- Strings: IDS_TARK_PAGE_TRANSLATION_TITLE and IDS_TARK_PAGE_TRANSLATION_SUMMARY in android_chrome_strings.grd, plus Hindi in _hi.xtb. The Hindi ids are grit fingerprints computed with tclib's algorithm (checked against xlit's existing ids).
- Test: `PageTranslationSettingsTest` (switchDefaultsOn, googleRowsStayHidden, hindiStringsPresent), added to chrome/browser/language/android:junit, which is already in chrome_junit_tests.
- The series comment is rewritten.

### page-translate-ui.patch (new)
Series slot: right **after captions-ui.patch**, which is after page-translate-wiring.patch. The slot is needed because it extends captions-ui's TarkCaptionsBridge, its java target and its strings, which don't exist at the wiring's slot. The series comment is in the file's style.
- **Pref gate (offer and menu)**, translate_manager.cc:
  - `TarkPageTranslationEnabled(prefs)` reads as on where the pref is unregistered.
  - CanManuallyTranslate returns false when the pref is off.
  - FilterIsTranslatePossible calls PreventAllTriggering when it is off.
  - Java's menu check (TranslateUtils.canTranslateCurrentTab) also goes through `TarkPageTranslationOffer.showMenu(pref, canManuallyTranslate)`.
- **Languages**:
  - TranslateLanguageList's supported list is now exactly the 22 Indian languages, en and es (`kTarkLanguages`). So the offer only appears for those languages, and the message's language menu lists only those.
  - TarkPageTranslationOffer.java:
    - `targetsFor`: es → en only; en → the 22; Indian → en plus the other 21.
    - `unitsFor` mirrors PageUnitsFor but is restricted to those targets.
    - `showOffer`: on, a supported language, and not one of the person's languages.
  - The browser's offer already skips the person's languages (upstream blocked/accept languages), so nothing new was needed there.
- **Tap → download card**:
  - New virtual `TranslateClient::TarkReadyToTranslate(source, target)`, default true.
  - TranslateManager::TranslatePage returns before PrepareToTranslatePage / ShowTranslateUI(TRANSLATING) when it answers false. Language state, the message ("Translate page?") and the page are untouched, and no error is shown.
  - ChromeTranslateClient (Android) asks Java `TarkPageTranslationCard.readyOrShowCard(webContents, source, target, offTheRecord)`.
- **The card**, TarkPageTranslationCard.java, in the tark_captions java target:
  - Missing units are requested with owner page_translation (new `OWNER_PAGE_TRANSLATION = 2`; the bridge's OwnerFrom maps 2 → `Owner::kPageTranslation`) and `now=false`, so captions' Wi-Fi rule applies.
  - The card is a message with captions' strings:
    - title "Getting translation ready · 221 MB" (summed sizes of the missing units);
    - line "On Wi-Fi · stays on this phone" (with % once bytes arrive), or "Waiting for Wi-Fi" with **Download now** (now=true for waiting units), or "Couldn't download" with **Try again** (failed units, Wi-Fi).
  - A unit listener translates once every unit is ready. It calls native `translate`, which runs TranslatePage only if the tab is visible, the page is untranslated and not pending, and the source still matches. It also dismisses the card.
  - If the card is dismissed by its timer, the page still translates when the download finishes. If it is swiped away, closed or the page navigates, it does not (the download goes on).
- **Private tab** (author's call, recorded): the card shows with line "Download in a regular tab first" and no button, and never requests a download. With the models already on the phone, a Private tab translates normally.
- **Strings**: IDS_TARK_PAGE_TRANSLATION_PRIVATE plus Hindi ("पहले किसी सामान्य टैब में डाउनलोड करें"). Everything else reuses captions' strings, which already have Hindi.
- **Build**:
  - tark_captions_android/android/BUILD.gn: new sources and the jni source.
  - New deps: messages, translate's java_resources (for the message icon), androidx annotation, and ui_no_recycler_view_java.
  - New `robolectric_library("junit")` holding PageTranslationOfferTest; chrome/android/BUILD.gn lists it in chrome_junit_tests.
  - chrome/browser/translate/BUILD.gn `impl` (Android) depends on `//chrome/browser/tark_captions_android/android:jni_headers`.
- **Test**: `PageTranslationOfferTest`:
  - switchOffHidesOfferAndMenu
  - targetsAreSupportedLanguagesOnly
  - noModelShowsDownloadCardNotError (includes the Private tab)
  - mobileDataWaitsForWifiUnlessDownloadNow
  - translatesAfterDownloadFinishes
  - hindiStringsPresent

### Other
- android/aws/jobs/tark-build.sh: new run `--gtest_filter='*PageTranslationSettingsTest*:*PageTranslationOfferTest*'`; both classes added to the must-have-run loop.
- utils/tests/test_android_page_translate_ui.py (new, 12 tests). It checks:
  - the pref is registered true, and the name is the same in C++, LanguageSettings and the Offer class;
  - the series order;
  - the language lists match the engine's kIndian;
  - the grit ids in the xtb;
  - the junit filter and must-have list;
  - the owner mapping.
- utils/tests/test_android_look.py TestNoTranslateSettings is updated to the new behaviour; the old tests asserted the --translate-script-url check.

## Verification (local)
- Pre-states: `scratchpad/t6/prestate.py` (Task 5's, plus captions' /dev/null-created files and `--verbose`, so offsets and fuzz are visible), built from the 156 sources (`?format=TEXT`), ungoogled, and the Tark series.
- `patch -p1 --dry-run -F0 --verbose`:
  - translate-settings-off.patch on its pre-state: 6 files, no failure or fuzz.
  - page-translate-ui.patch on its pre-state: 16 files, no offset or fuzz.
- Full series to the end: every rc 0 and no fuzz.
  - Later patches on the same files still apply: voice-languages (LanguageSettings), voice-language-detect (TarkCaptionsBridge.java, bridge.cc), update-check, captions-ui, zynclave-*, media-* (grd/xtb), speech-language-snackbar.
  - At first my xtb/LanguageSettings insertions broke update-check and voice-languages. I moved the insertions; the hunk contexts of those patches are unchanged.
- Note: macOS `patch` prints offsets only with `--verbose`, so Task 5's "no offset" check could not see them. The series already has many offsets (normal; the build's patches.py allows them). Fuzz is 0 everywhere.
- Python:
  - `python3 -m unittest discover -s utils/tests -p "test_android_*.py"`: 468 tests OK.
  - `bash -n tark-build.sh`: ok.

## Concerns
1. Not compiled. Things to watch:
   - MessageBannerProperties keys (DISMISSAL_DURATION of 600 s may be clamped);
   - `MessageDispatcher.enqueueMessage(..., highPriority=true)` over Translate's own message, which also uses MessageIdentifier.TRANSLATE (reused; adding an identifier needs an enums.xml change);
   - the JNI signature `JavaRef<jobject>` for WebContents;
   - `GetLanguageTagFromString` accepting brx/sat/mni/doi/kok;
   - `R.drawable.message_translate_compact` resolving through the `java_resources` dep.
2. Robolectric:
   - `@Config(qualifiers="hi")` needs the junit APK to carry the Hindi resources from the grd/xtb;
   - `formatShortFileSize` must give "221 MB" (SI units) on Robolectric's SDK;
   - ChromeSwitchPreference must construct without an AppCompat theme.
   These are the likely first-build failures, and test-only.
3. The card and Translate's own message both show. The card is enqueued as high priority, and "Translate page?" stays underneath. Tapping Translate again only updates the card.
4. The message's language menu can still offer a target outside `targetsFor(source)` (e.g. Hindi → Spanish, since es is in the list for Spanish pages). The tap then does nothing; there is no card and no error. A per-source filter of the menu would need changes in TranslateMessage's C++.
5. Spike Step 2 concern ("first tap did nothing"): my path makes a tap without models a deliberate no-translate that shows the card. With models present it goes straight to TranslatePage. If the flake reappears without the card showing, it is upstream's or the snackbar's, not this gate's. Watch for it on the emulator.
6. Pref default lives in translate-settings-off.patch (an earlier slot); page-translate-ui.patch and Java read it. The offer-pref default (kOfferTranslateEnabled true) stays in page-translate-wiring.patch.
7. Upstream components_unittests for TranslateLanguageList and TranslateManager (desktop/host) would see the 24-language list; they are not run on Android.
8. No tarka-notes repo exists locally (as Task 5 found); the decisions are recorded here and in the series comments.
