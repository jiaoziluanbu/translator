# Development Log

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
