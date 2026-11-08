# nxnative fork: WebUI and Windows build support

This repository is a fork of [seedds/nxnative](https://github.com/seedds/nxnative).
Upstream code lives at its original paths (`dm/`, `scripts/`, `docs/`, `README.md`)
and is kept clean so that upstream can be fetched and merged without carrying fork
changes in every file.

Game support is listed in the upstream [game gallery](README.md#games) and
[game table](dm/games/README.md#games), kept in sync with this fork. Read each
game's note for tested platforms and limitations. The Windows builder supports
the [offline NVN subset](webui/docs/webui.md#tools-and-platforms); Switch 2
gameplay is currently tested on Mac only.

Fork-owned code lives under `webui/`, with the root launchers and `FORK.md`
beside it and the upstream-sync workflow under `.github/`:

| Path | Purpose |
|---|---|
| `webui/` | Local build studio (FastAPI), task queue, launchers, tool preparation |
| `webui/build/windows/` | Windows iOS cross-compile, shader build and IPA packer |
| `webui/overlays/dm/` | Fork-only source files placed into the staged `dm/` tree (the ObjC port of the iOS launcher) |
| `webui/patches/` | Upstream hook patches applied only to the build staging tree |
| `webui/launchers/` | Canonical launchers (thin wrappers are at the repository root) |
| `webui/tools/` | Staging, patch queue, sync checks and helper CLIs |
| `webui/docs/` | WebUI guide, plan, validation data and upstream sync notes |
| `.github/workflows/upstream-sync.yml` | Fork-only upstream-sync automation; other `.github` files are upstream-owned |

## Start

Windows: double-click `start-webui.bat` (or `webui\launchers\start_webui.bat`).
macOS: run `./start-webui.sh` in a terminal (or double-click `start-webui.command`; the internal launcher is `webui/launchers/start_webui.sh`).

The browser opens automatically; otherwise, use the complete session URL printed
in the terminal. Keep that terminal open. In **Environment & tools**, install
missing supported dependencies and select **Recheck**, then upload/import the
game packages and `prod.keys`, choose the output and start a build. Download the
result from the task when it finishes.

Step-by-step startup, platform requirements, launcher languages, retry and cleanup:
[WebUI README](webui/README.md). Detailed installation and SDK discovery:
[WebUI guide](webui/docs/webui.md).

The launchers keep their data in the repository's `.webui-data/` directory. That
directory is local-only and is added to `.git/info/exclude`; the upstream
`.gitignore` is not modified.

## Builds use a stage

A build never writes into the upstream working tree. `webui/staging.py` copies
the repository into `.webui-data/stage/<key>/tree`, applies the overlays and
the hook patches under `webui/patches/`, and runs the build from that copy. The
stage is reused until a source file or patch changes.

The only intentional direct edit to an upstream file is `dm/ios/project.yml`,
which declares the iOS fullscreen launch configuration (`UIRequiresFullScreen`
and `UILaunchScreen`). Everything else is a patch or an overlay.

The optional **Separate IPA and RomFS** iOS build is off by default. When
selected, the IPA leaves out `romfs/` and the task also produces a
`<title>.romfs.zip` (top-level `romfs/`) with `webui/build/romfs_archive.py`;
the Windows builder and patch 0005 carries the hook. The app reads
`Documents/romfs` with no app-side change. macOS `.app.zip` stays self-contained.

## Upstream sync

The upstream remote is `https://github.com/seedds/nxnative.git`. The recorded
sync refs are in `webui/patches/UPSTREAM_BASE`; `webui/docs/sync.md` is the
authoritative procedure.

GitHub Actions runs `.github/workflows/upstream-sync.yml`:

- the daily scheduled run uses `auto/upstream-sync` and fast-forwards `main`
  only after the merge, hook port, patch regeneration, staging, `sync_check`
  and tests pass;
- a manual `workflow_dispatch` uses `review/upstream-sync` and opens a PR for a
  human to merge; it never moves `main`;
- `hooks/upstream-sync` is an internal audit branch;
- any failure stops the run, keeps the evidence and opens/updates an Issue or
  draft PR. There is no automatic vendor-drop fallback or conflict resolution.

Push local `main` before enabling the workflow so the remote base is current.
The workflow needs write permissions and, for review mode, permission to
create pull requests; upstream workflow-file changes also need the
`SYNC_TOKEN` Actions secret (a PAT with Contents, Workflows, Issues and Pull
requests write). See `webui/docs/sync.md`. The local CLI is
`webui/tools/sync_upstream.py`. `webui/tools/sync_check.py` reports
upstream-owned edits and patch applicability.

See `webui/README.md` for the developer overview.
