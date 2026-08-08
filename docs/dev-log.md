# Development Log

## 2026-08-08 - Prepare v2.2.1 release package

### What changed

- Bumped the app bundle and DMG version from `2.2.0` to `2.2.1`.
- Built `dist/Local Translator.app` and `dist/LocalTranslator-2.2.1.dmg` from the screenshot latency, Service translation, and fixed-target routing changes.
- Refreshed the current user's Finder `Translate` Service from the same release source.

### Why

- GitHub already has a public `v2.2.0` release, so these backward-compatible fixes need a patch release rather than replacing an existing tag or asset.
- A full rebuild verifies that the source fixes are actually included in the downloadable app, not only in the development checkout.

### Touched areas

- Release metadata: `setup.py`, `build_app.sh`, `README.md`
- Release artifacts: `dist/Local Translator.app`, `dist/LocalTranslator-2.2.1.dmg` (git-ignored)
- Installed Service: `~/Library/Application Support/LocalTranslator/bin/translate-service.sh`
- Workflow state: `workspace.md` (git-ignored)

### Verification

- System Python 3.9 regression suite passed: 10/10 tests.
- Python compilation, shell syntax checks, and `git diff --check` passed.
- py2app build and DMG creation completed successfully.
- App bundle reports version `2.2.1`, is 1.1 GB, and passes `codesign --verify --deep --strict`.
- DMG is 538 MB, passes `hdiutil verify`, mounts read-only, contains version `2.2.1`, and its mounted app passes strict code-signature verification.
- DMG SHA-256: `b027100b73b2448412e5c7567fd26d1396f0f494296b4f25b6aa00244c68e79a`.
- Bundled `daemon.py`, `core/pipeline.py`, and `core/translate.py` match the release source byte-for-byte.
- The built app's Service bridge translated `Hello world` to `你好，世界`.
- Installed Service script hash matches the release source script.

### GitHub publication

- Functional release commit: `a862f0d28f93bb7337a0c913607ea023bb9ee21c` (`release: fix capture latency and translation routing`).
- Pushed branch: `codex/optimize-translator-memory`.
- Updated existing Draft PR #1: `https://github.com/jiaoziluanbu/translator/pull/1`.
- Published non-draft, non-prerelease GitHub Release `v2.2.1`, marked as Latest: `https://github.com/jiaoziluanbu/translator/releases/tag/v2.2.1`.
- Remote tag `v2.2.1` points to the verified functional release commit `a862f0d28f93bb7337a0c913607ea023bb9ee21c`.
- GitHub reports the DMG asset as `uploaded`, 564,091,013 bytes, with server digest `sha256:b027100b73b2448412e5c7567fd26d1396f0f494296b4f25b6aa00244c68e79a`, matching the local artifact.

### Data impact

- Gallery files remained at 10 files / 1.1 MB; preferences hash remained unchanged.
- The database stayed healthy and retained 5 gallery items, 1 group, 0 shots, 0 text blocks, and 0 edits; no user record was added or deleted by the build.
- The database file's byte hash changed during the release window while the already-installed app was running. Its last modification time (`2026-08-08 12:10:47`) predates the Service refresh (`12:15:41`); integrity and logical record counts passed, but a byte-for-byte “unchanged” claim cannot be made.
- The build did not replace `/Applications/Local Translator.app` or modify language packs.

### Backups and rollback

- The build script moved the prior `build` and `dist` directories to timestamped backup directories before rebuilding.
- Local rollback remains available through those build backups and the previously installed `v2.2.0` app backup.
- Remote rollback, after publication, is to remove the `v2.2.1` Release/tag and revert the release commits; `v2.2.0` remains available.

### Remaining risks

- The app uses ad-hoc signing and is not Apple-notarized, so first launch on another Mac may still require right-clicking the app and choosing Open.
- py2app reports many missing optional imports from transitive packages; these are existing platform/dev extras, and the bundled translation path passed runtime verification.
- Draft PR #1 remains unmerged by design; `main` was not changed during this release.

## 2026-08-08 - Build and install the screenshot/translation fixes

### What changed

- Built a new `Local Translator.app` from the 2026-08-07 source fixes.
- Replaced `/Applications/Local Translator.app` with the verified new build.
- Refreshed the installed macOS right-click Service script and its stable symlink.
- Restarted the menu-bar app; its hot worker started and reached `READY`.

### Backups and rollback

- Previous installed app: `/Applications/Local Translator.backup-20260807.app`
- Previous Service script: `~/Library/Application Support/LocalTranslator/bin/translate-service.backup-20260808.sh`
- Previous build workspace: `build.bak-20260808-113628`
- Previous dist workspace: `dist.bak-20260808-113628`
- Rollback remains possible by quitting the new app, moving the current app aside, restoring the app backup to `/Applications/Local Translator.app`, restoring the Service script backup, and reopening the app.

### Verification

- Build completed successfully and produced a 1.1 GB app bundle.
- `codesign --verify --deep --strict` passed before and after installation.
- Installed source hashes match the verified build output.
- Installed Swift helper reports all six prepared language directions as installed: `zh↔en`, `zh↔ja`, and `zh↔ko`.
- Installed app's `--service-translate` entry translated `Hello world` to `你好，世界`.
- Main app process is running, and the replacement hot worker reached `READY` in about 6 seconds.
- A controlled installed cold-worker smoke test reached `capture UI ready` in approximately 0.60 seconds; the test overlay process was then closed.
- User physically pressed `⌃⌥A` after installation and confirmed the screenshot overlay now appears noticeably faster. This closes the real global-hotkey acceptance check.
- Final accessibility status check returned `AXIsProcessTrusted=True`; the app and replacement hot worker remained running after the manual check.
- Database and preferences SHA-1 values were identical before and after installation.
- Gallery remained at 10 files and 1.1 MB before and after installation.

### Data impact

- Existing gallery records, saved images, database contents, preferences, and language packs were not changed.
- Long-lived installed app and Service files were changed with explicit user approval and recoverable backups.

### Remaining risks / user action

- The right-click Service's bundled translation bridge was verified directly; the final Finder/Services dialog interaction still needs a quick manual user check.

## 2026-08-07 - Faster capture launch, reliable Service fallback, fixed target language

### What changed

- Reordered the cold screenshot worker so it imports and displays the capture overlay before loading OCR, argostranslate, and torch.
- Kept the image-only editor launch ahead of heavy processing, so the selected screenshot and loading state appear before cold translation initialization finishes.
- Added an app-bundled `--service-translate` entry point for the macOS right-click Service. It tries the Swift helper first and lazily uses the argos package bundled in the app, without requiring an external compatible Python.
- Added backward compatibility detection so an updated Service script will not pass the new flag to an older installed app.
- Changed explicit target-language routing so the selected target is never flipped. Mixed screenshots detect the source language per visual paragraph while keeping one fixed target.
- Applied the same per-paragraph target-aware routing to the reusable OCR pipeline.
- Added 10 focused regression tests covering target locking, mixed-language routing, cold-worker ordering, and the Service bridge.

### Why

- After the hot worker's 180-second idle timeout, the old cold path imported the full translation stack before showing the capture overlay. Local measurements showed the capture UI import takes about 0.14-0.51 seconds, while the translation import adds about 1.90-5.89 seconds; installed worker logs showed 7-10 second warmups.
- The right-click Service fell back to `translate_cli.py` inside the installed app bundle, but that file was not bundled. The final generic error incorrectly claimed that the Swift helper was uncompiled even when the helper existed and worked.
- Explicitly choosing Chinese with mixed text such as `Hello 你好` previously produced the pair `zh -> en`, because matching the detected source caused the code to change the target language.

### Touched areas

- `daemon.py`
- `core/translate.py`
- `core/pipeline.py`
- `scripts/translate-service.sh`
- `tests/test_translation_fixes.py`
- `README.md`

### Verification

- Python syntax compilation passed for the changed Python modules and test file.
- Shell syntax validation passed for `scripts/translate-service.sh`.
- `python3 -m unittest -v tests.test_translation_fixes`: 10/10 tests passed.
- Built-in service entry translated `Hello world` to `你好，世界` through the Swift helper.
- Forced the Swift path unavailable and confirmed the bundled argos fallback also translated `Hello world` to `你好，世界`.
- Existing English screenshot pipeline probe passed: 14 OCR blocks, 10 aligned paragraphs, non-empty Chinese output.
- Mixed screenshot sample passed: 55 OCR blocks, 24 paragraphs, all 55 block translations non-empty; already-Chinese paragraphs stayed Chinese while English paragraphs translated to Chinese.
- Three fresh-process timing samples after reordering showed capture-module readiness at 0.166-0.231 seconds; the 2.382-3.969 second heavy import now occurs after capture/editor visibility.
- `git diff --check` passed.

### Data impact

- No gallery records, saved images, database rows, preferences, language packs, or other existing user data were changed.
- The installed `/Applications/Local Translator.app`, installed Service copy, and running background process were not replaced or restarted in this task phase.

### Remaining risks

- The source changes still need a new app build and an installed-app hotkey smoke test before the user can experience the fixes.
- The app build/install and Service refresh affect long-lived local state and require separate user approval.
- The environment still emits an existing urllib3/LibreSSL compatibility warning while importing argostranslate; translation tests pass despite the warning.

## 2026-06-10 - Publish v2.2.0 to GitHub Releases

### What changed

- Created GitHub Release `v2.2.0`.
- Uploaded `LocalTranslator-2.2.0.dmg` to the release.
- GitHub now marks `v2.2.0` as the Latest release.

### Why

- The installed local app was already version `2.2.0`, but GitHub Releases still pointed users to `v2.1.1`.
- Publishing the `2.2.0` package makes the public download link match the current installed package.

### Touched areas

- GitHub remote tag: `v2.2.0`
- GitHub Release: `https://github.com/jiaoziluanbu/translator/releases/tag/v2.2.0`
- Release asset: `LocalTranslator-2.2.0.dmg`

### Verification

- Confirmed `gh release view v2.2.0` returns a non-draft, non-prerelease release.
- Confirmed release asset state is `uploaded`.
- Confirmed asset digest is `sha256:6d98d110887cb76070e0f0ae98b4e391c7f868462fb17f59e5a7740221793515`.
- Confirmed `gh release list` shows `v2.2.0` as `Latest`.
- Confirmed remote tag `refs/tags/v2.2.0` points to commit `b821e6fb6effc6f8693e05abfd5144270fe773cf`.

### Data impact

- No local user data was changed.
- Existing gallery data, saved images, app settings, language packs, and installed app files were not touched.

### Remaining risks

- The app is still not formally signed with an Apple Developer ID, so first launch may require right-click Open.
- The default `main` branch still points at `v2.1.1`; the release tag points at the `2.2.0` branch commit.
