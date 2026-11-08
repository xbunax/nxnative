# Upstream hook patches

These patches keep fork behavior out of the upstream working tree. They are
applied only to the staging tree created by `webui/staging.py`.

- The current base, upstream, fork, hooks and merge-base commits are recorded in
  `UPSTREAM_BASE`; `webui/tools/sync_upstream.py` updates that file and the
  `series` comments when it regenerates the queue.
- Patches are regenerated with
  `git diff --no-ext-diff --unified=3 upstream/main -- <target>` from the ported hooks branch.
  The sync CLI ports the previous queue with `git apply` (exact context, line
  offsets allowed), then requires the regenerated queue to pass the strict
  `diffapply`/staging checks.
- The 2026-10-24 sync merged upstream `fa69e20` into `main`;
  `sync/upstream-20261024` is the vendor-drop equivalent with the same tree.
  The pre-sync main (`c586dd1`) is preserved on
  `backup/main-before-upstream-20261024`. `webui/docs/sync.md` records the
  automation and manual fallback procedures.
- `series` lists the patch file and its target. The applier rejects a target
  that differs from the series entry or escapes the tree.
- Patch files are LF. The source checkout uses CRLF; `webui/diffapply.py`
  normalizes both sides and writes LF into the stage.

## 2026-10-24 port notes

Upstream's `gen_embed.py` now packs NRO modules through a `place()` helper; the
fork's POSIX paths and `no_dead_strip` section attributes are applied to both
the module and NRO section directives. The host Makefile line carries upstream's
new headers (`pad_slots.h`, `hle_haptics.h`, `haptics_apple.h`, CoreHaptics) and
no longer names the per-game `dmsh_chain.h`, while keeping `-framework MetalFX`.
`scripts/build_ipa_from_nsp.py` keeps the `--separate-romfs` and
`@NXEVENT` hooks beside upstream's new `--platform` option.

## 2026-11-08 port notes

All nine patches are regenerated against `1794a35a`. The embedded-code hook
keeps upstream's program tags, back patch areas and JIT images while preserving
POSIX paths and no_dead_strip. The extractor catalog hook runs inside upstream's
new Run wrapper, retaining its missing-key and damaged-filesystem handling.
The NSP hook retains both --work-dir and --separate-romfs. The language-picker
hook keeps the new cloud-save section, multi-program DM_APP_DM lookup and the
game-menu model instead of restoring the old launcher entry point.

## Patch 0005 notes (was 0009, then 0007)

The original fork patch added a top-level `import json` because the WebUI
launch-defaults block used `json` while the module imported it only inside
`Progress.stage`. Upstream now imports `json` itself; the port keeps the WebUI
`@NXEVENT` hooks, the
launch-defaults block and the separate-RomFS block. The rest of the patch is
rebased onto upstream's newer `build_ipa_from_nsp.py` (derived profiles,
`--prepare-xcode`, `--language`, `--show-fps`, `--progress json`).

## Separate RomFS hook (0005)

Upstream has `--romfs separate` (`DM_COPY_ROMFS=NO`, an identity file
`romfs.id`, `scripts/push_romfs.sh`). Patch 0005 keeps the WebUI's
`--separate-romfs` flag: it selects that mode and then writes the RomFS image
(or folder) to `<ipa>.romfs.zip` with `webui/build/romfs_archive.py`, as a
top-level `romfs.img` or `romfs/`, created by the upstream `pack_ipa.py`..

## Do not regenerate

`.gitignore`, `README.md` and `dm/ios/project.yml` are not part of the patch
queue. The first two are restored to upstream; `project.yml` is the single
intentional direct edit (fullscreen launch keys).

After an upstream sync, port the hooks onto a temporary hooks branch and run
`python webui/tools/patch_queue.py regenerate`. See `webui/docs/sync.md`.

## 2026-10-28 sync (upstream e06adb2)

Upstream now has MetalFX spatial upscaling (`DM_PRESENT_UPSCALE=metalfx`), a
`--platform mac-app` Mac application, a RomFS image (`RomFS.img`,
`Documents/romfs.img`) and its own launcher. The fork dropped its MetalFX
patches and overlays (old 0005/0006), and its macOS wrapper
(`webui/build/macos/`); WebUI Mac builds use `--platform mac-app`. The queue
is renumbered 0001-0007. The ObjC launch settings stay (Windows cross-builds
cannot compile the SwiftUI launcher) and map their upscaling row to
`DM_PRESENT_UPSCALE`; the output-height and interpolation rows no longer have
an effect.

## 2026-10-28 sync (upstream d0b7c84)

Upstream added `--romfs separate` (#493, #478). The fork's own
`NX_SEPARATE_ROMFS` hook in `build_ipa.sh` was removed; patch 0007 reuses
upstream's mode.

## 2026-10-28: one launcher in two languages (queue is now 0001-0005)

The fork's own launch settings (patches for `main.m` and the `build_ipa.sh` launch-defaults copy, the
`launch-defaults.json` plumbing, `DmLaunchSettings`, `DmPerfHud`, `dm_launch_options.h`,
`dm_bundle_defaults.h`) were replaced by `overlays/dm/ios/Sources/DmLauncher.m`, an ObjC port of upstream's
Swift launcher. An `objc` stage removes `Launcher.swift`, `LauncherRow.swift` and `LauncherSettings.swift`
(`staging.OBJC_REMOVED`) and adds the port; a `swiftui` stage is upstream's tree. `main.m` is not patched
(`front_ios.m` calls `dm_show_launcher`). The WebUI sets only the game language (`--language`); the other
settings are upstream's own rows. The former patch 0007 is now 0005.
