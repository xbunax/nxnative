# WebUI: startup and usage

The WebUI is the fork-owned local build studio. Upstream nxnative code stays at
its original paths; everything here is safe to change without touching upstream.

## Game support

The [game gallery](../README.md#games) and [detailed game table](../dm/games/README.md#games)
are synchronized from upstream. Each game links its tested builds, platforms,
progress and known issues; a Mac gameplay test does not imply an iPhone test.

Windows builds support the offline NVN subset described in the
[platform limits](docs/webui.md#tools-and-platforms). Switch 2 games listed by
upstream are tested on Mac only; use the upstream [Switch 2 build instructions](../README.md#switch-2-games).
The WebUI package picker currently accepts NSP/XCI/NSZ, not NUP containers.

## Start the WebUI

Clone or download this fork, then open its repository folder:

```sh
git clone https://github.com/xbunax/nxnative.git
cd nxnative
```

| Host | Start from the repository root | Requirements |
|---|---|---|
| Windows | Double-click `start-webui.bat`, or run `.\start-webui.bat` in PowerShell | The launcher downloads a local Python runtime and installs missing Python dependencies on first use. |
| macOS | Run `./start-webui.sh`, or double-click `start-webui.command` | Apple Silicon, Python 3.11 or newer, and a configured full Xcode installation for builds. |

The browser opens automatically. Keep the launcher terminal open while using the
WebUI. If the browser does not open, use the complete **Open in your browser** URL
printed by the launcher, including its session token. The default address is
`127.0.0.1:8765`; each launch creates a new browser session.

First-time setup needs network access. Windows startup errors are recorded in
`.webui-data/startup.log`. Existing compatible tools and Python environments are
reused on later launches. This is a local, single-user service.

For an existing Python installation, the direct entry point is
`python3 webui/launchers/start_webui.py`. It accepts `--data-dir`, `--tools`,
`--port` and `--no-browser`; the root launch shortcuts forward these options.
For Spyder, open [launchers/start_webui.py](launchers/start_webui.py), adjust the
settings at the top if needed, and run it with F5.

## Build or inspect a game

1. Open **Environment & tools**, choose a tools directory and click
   **Install all supported missing dependencies**. Finish any manual entries,
   then click **Recheck**. Windows builds need the iPhoneOS SDK and Apple's
   Windows Metal Developer Tools; macOS builds need full Xcode and its Metal
   compiler. Detailed setup: [Windows](docs/webui.md#windows-installation) and
   [macOS](docs/webui.md#macos-installation).
2. Upload your game packages and `prod.keys`, or import their existing absolute
   paths. Include the base game and any required updates or DLC. Saved uploads
   can be selected again from the upload history.
3. Choose **Build an app**, **Convert XCI/NSZ to NSP**, or **Inspect game metadata**.
   For builds, select the target platform and default game language. Windows
   supports unsigned iOS builds for the offline NVN subset; macOS supports iOS
   and Mac app output. See the [platform limits](docs/webui.md#tools-and-platforms).
4. For iOS, choose the launcher. Windows uses ObjC; Mac builds can use ObjC or
   SwiftUI. Optionally enable **Separate IPA and RomFS** to produce a smaller IPA
   and a separate `.romfs.zip`; extract its top-level `romfs` folder into the
   installed app's `Documents` directory.
5. Start the task and follow its progress and **Log**. Download the IPA or Mac
   app ZIP from the completed task. IPAs are unsigned: sideload them using your
   preferred tool. A failed target keeps any successful output available.

The browser's header language selector changes WebUI text. Inside either iOS
launcher, **Interface language** beside Play switches English / Simplified Chinese
and remembers the choice. These interface preferences are separate from the
**Game language** setting. Rebuild the IPA to include launcher UI changes.

## Logs, retry and cleanup

Each task has its own ID, timestamp and log. After updating the source, create a
new build task; an old task's log continues to show its original failure. Retry
needs the original inputs and keys; import keys again if the task requests them.
Changes to the WebUI server itself require restarting the launcher process;
refreshing the browser alone does not reload Python code.

Data defaults to `.webui-data/`, including uploads, task inputs, outputs, tools
and caches. Use `--data-dir` or `--tools` to choose another directory when needed.
**Clear cache** is available when the queue is idle and removes staged sources,
the shader cache and task inputs while keeping completed task outputs and logs.
Deleting a task removes its entire task directory, including its outputs; download
anything you want to keep first.

For SDK discovery, offline tools, installation details and troubleshooting, see
the [full WebUI guide](docs/webui.md).

## Layout

- `server.py`, `jobs.py`, `worker.py`: loopback FastAPI service and serial tasks.
- `capabilities.py`, `dependencies.py`, `apple_tools.py`, `windows_tools.py`:
  environment checks and tool installation.
- `packages.py`, `file_tools.py`: NSP/XCI inspection, XCI conversion and NSZ decompression helpers.
- `repo.py`: repository root, upstream game module import and git exclude helper.
- `staging.py`: materializes the build staging tree (source snapshot + overlays + patches).
- `diffapply.py`: line-ending-normalizing unified-diff applier used by staging and tests.
- `build/windows/`: Windows cross-compile, shader build and IPA packer.
- `overlays/dm/`: fork-only source files copied into the staged `dm/` tree (`DmLauncher.m`, the ObjC port of upstream's iOS launcher).
- `patches/`: ordered upstream hook patches (`series`).
- `launchers/`: canonical Python/PowerShell/shell launchers.
- `tools/`: staging CLI, patch queue, sync check, upstream sync CLI, tool preparation and XCI helper.
- `tests/`: unittest suite (`python -m unittest discover -s webui/tests -t . -v`).

## Build flow

1. The worker calls `staging.ensure()` to create or reuse a stage tree under
   `.webui-data/stage/<key>/tree`.
2. The stage is a full copy of the repository excluding generated/local folders.
   Overlay files are written into `dm/`, then the patch queue is applied with the
   pure-Python applier. The working tree is never modified.
3. The Windows builder runs the staged
   `webui/build/windows/build_ipa_windows.py`; macOS runs the staged
   `scripts/build_ipa_from_nsp.py` with upstream's `--platform mac-app` for the Mac app (zipped
   as `.app.zip`) and the patched launch defaults for iOS. nx_extract is built from the staged, patched C# project.
4. With the optional `--separate-romfs` (WebUI: **Separate IPA and RomFS**,
   default off), the iOS IPA omits `Payload/DmIOS.app/romfs` and
   `webui/build/romfs_archive.py` uses the upstream `pack_ipa.py` to write
   `<ipa>.romfs.zip` with a top-level `romfs/`. The worker verifies both and
   publishes the IPA, archive and their SHA-256 files.
5. Stage reuse is keyed by the source file manifest, platform, patch bytes and
   overlay bytes. `NX_STAGE_REBUILD=1` forces a rebuild; `NX_STAGE_KEEP`
   controls garbage collection.

The Windows shader adapter reads the upstream Metal command lists and preserves
their flags (including `-O1`, invariant positions and iOS relaxed math), replacing
only the tool prefix, target and module cache location. It copies the sources in
the chain's `FILES` manifest and the full-build table generators. SPIRV-Cross uses
the upstream `SPIRV_CROSS` environment override.

Upstream's macOS ARM64 translator assemblies cannot load in Windows x64 .NET.
After checking the pinned upstream DLL hashes, the adapter publishes the current
translator and vendored Ryujinx sources as portable IL in the isolated chain.
The Windows lock records those DLLs and the actual Windows compiler fingerprints;
the repository's translator binaries, lock and chain header stay unchanged.
The first build needs NuGet access; packages are reused from the tools directory's
`nuget` cache (or `NUGET_PACKAGES` when configured).
Recursive translator source copies use Windows extended paths for Python IO;
the longest Ryujinx.Common filenames exceed 260 characters under task folders.
External compiler commands retain ordinary paths.
Cache clearing and task deletion also use extended paths, so those source trees
can be removed through the WebUI without changing Windows system settings.
The generated chain header is published into the build profile for the packer.
Host compilation uses a clang VFS overlay to resolve NVN's quoted chain-header
include to that same file, ahead of the macOS header beside `nvn_mtl.m`, while
leaving the staged upstream sources unchanged.

## Adding an upstream hook

1. Add a patch file to `webui/patches/` and an entry to `series` (patch file and
   repository-relative target).
2. If the hook adds a new source file to an upstream directory, put it under
   `webui/overlays/dm/...` instead and list its target in the overlay allowlist.
3. Add a marker assertion to `tests/test_patch_queue.py`.
4. Run `python webui/tools/sync_check.py` and the full test suite.

See `docs/sync.md` and `docs/webui.md` for the user-facing workflow.

## Launcher interface language

Both iOS launchers offer **Interface language** beside Play: English and Simplified
Chinese. The initial language follows the device language; an explicit choice is
saved immediately in `launcher.uiLanguage` and applies on the next launch too.
This preference controls launcher text only. Game language remains the separate
`DM_LANG` setting, and resetting game settings preserves the interface language.

`localization/launcher.zh-Hans.json` supplies the shared translations. Hook patches
embed them as the optional `uiTranslations` field in `dm/launcher.json` and add the
SwiftUI language picker and translated rows. The ObjC overlay reads the same data.
Unknown text falls back to English. Swift UI patches apply only to Swift stages;
the working tree's upstream files stay untouched.

## Tests

```sh
python -m pip install -r webui/requirements-sync-ci.txt
python -m unittest discover -s webui/tests -t .
```

A module whose package is missing is skipped; `NX_REQUIRE_TEST_DEPS=1` (set in the
sync workflow) turns that into an error. `test_sync_e2e.py` runs the sync tool against a
throwaway upstream and fork, and `test_patched_scripts.py` runs the patched upstream
scripts in a stage; both need `git` / `bash` and skip without them.
