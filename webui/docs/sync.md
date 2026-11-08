# Syncing with upstream

Upstream: <https://github.com/seedds/nxnative>

## Current state

The authoritative base, upstream, fork, hooks and merge-base commits are in
`webui/patches/UPSTREAM_BASE`; the automated sync updates it and the `series`
comments. The 2026-10-24 sync merged upstream `fa69e20` into `main`; the
vendor-drop equivalent is `sync/upstream-20261024`, the ported hooks are on
`hooks/upstream-20261024`, and the pre-sync main is preserved on
`backup/main-before-upstream-20261024`.

The 2026-11-08 manual sync merges upstream `1794a35a` (570 commits since
`39509760`) into fork main `d1ba3e97`, on `sync/upstream-20261108`. The nine
hooks were ported on `hooks/upstream-20261108`; upstream-owned sources remain
unchanged except the fullscreen key in `dm/ios/project.yml`. The ObjC launcher
now ports cloud-save folder selection, the live in-game menu, multi-program
settings paths and the hosting controller's orientation policy. ObjC stages
remove both new Swift files as well as the three original launcher files.

Windows follows upstream's new tool_lock.py checks, SQLite shader cache and
shader images (expanded for the existing Windows packer). Its host build adds
the dav1d decoder, generated host Metal libraries with the source-only fallback,
and a Foundation implementation of clang's OS-availability helper, since the
Windows LLVM bundle has no Darwin compiler-rt. The fork CI uses upstream's
Xcode 27.2. Validation: 174 WebUI tests (two platform/tool skips), 15 upstream
documentation/toolchain tests, the patched extractor build (zero warnings and
errors), 263 iOS source compiles and a verified unsigned link with synthetic
embedded modules. No game or device was run; see
`upstream-sync-20261108.json` for the recorded scope.

The README follow-up on the same day merges upstream `651369bc`, including
its --shader-files installation option and matching packer tests. The root
README, game table and gallery data match upstream; FORK.md and webui/README.md
link to them and explain platform coverage instead of maintaining another list.

Upstream-owned files are pristine except `dm/ios/project.yml`, so a normal
merge is clean: the fork tree (`webui/`, `FORK.md` and the root launchers) does not overlap
upstream. The root `.gitattributes` is shared: upstream's lines first, then a
fork block that merges with the `union` driver (the fork's other rules are in
`webui/.gitattributes`), so an upstream edit to it merges without a stop. Patch 0005 maps the
WebUI's `--separate-romfs` onto upstream's `--romfs separate` and archives the
image; keep it when porting. `webui/provisional.py` mirrors upstream
`scripts/build_ipa_from_nsp.py`'s survey and provisional-profile format for the
WebUI; recheck it when that upstream code changes. The iOS launcher exists twice and is
the same launcher in two languages: upstream's SwiftUI `Launcher.swift`,
`LauncherRow.swift`, `LauncherSettings.swift`, and the fork's ObjC port
`webui/overlays/dm/ios/Sources/DmLauncher.m` (an `objc` stage removes the Swift files and adds
the port; the Windows cross-build cannot compile Swift, so it always uses the port). Both read
`dm/launcher.json`. When a sync changes the Swift files the sync warns, and
`webui/tests/test_launcher_parity.py` fails until `DmLauncher.m` is changed with them. Mac apps use
upstream's own `dm/mac/Launcher.swift` in either case.

The 2026-10-23 sync force-pushed `main` to a vendor drop of upstream
`eab15b5`; that history is preserved on
`backup/main-before-upstream-20261024`.

## One-time setup

```sh
python webui/tools/init_fork.py --fetch
```

This adds `upstream = https://github.com/seedds/nxnative.git` (never changes
`origin`), fetches it, and writes `.webui-data/` to `.git/info/exclude`.
Use `GIT_EXE=/path/to/git` if the shell's `git` shim is broken.

## Automated sync

`.github/workflows/upstream-sync.yml` runs on GitHub Actions. It has two modes:

- `auto/upstream-sync`: every scheduled run (daily, 03:17 UTC). The workflow
  builds a merge commit, applies the existing hook queue with `git apply`
  (exact context, line offsets allowed, no fuzz), regenerates the queue and
  re-verifies it with the strict `diffapply`/staging checks, runs the tests,
  pushes the branch, and then fast-forwards `origin/main`. `main` is never
  force-pushed.
- `review/upstream-sync`: `workflow_dispatch` only, default mode `review`.
  It does the same preparation and pushes the branch, but opens or updates a
  PR for a human to merge. It never moves `main`.
- `hooks/upstream-sync` is an internal audit branch holding the upstream tree
  with the ported hooks; it makes the `hooks` commit in `UPSTREAM_BASE`
  reachable. It is not a third sync mode.

Scheduled runs always use `auto`. Run a manual dispatch from `main`; the job
ignores a dispatch from any other branch. A manual dispatch defaults to
`review` but can select `auto` or set `dry_run` to prepare and test without
pushing. Use one mode at a time: an `auto` run that updates `main` can make an
open `review` PR redundant. The workflow records `main` and upstream before running, and only
publishes when:

- the merge has exactly the expected parents;
- the existing seven patches applied to the new upstream with `git apply`
  (exact context, offsets allowed);
- the regenerated patches are non-empty, pass the strict `diffapply`/staging
  checks and the metadata was committed;
- `patch_queue check`, staging verification, `sync_check` and the WebUI tests
  all pass;
- the tests did not modify tracked files;
- the candidate does not change `.github/workflows/upstream-sync.yml` or the
  root fork launchers, and the only `webui/` changes are under
  `webui/patches/`.

Upstream changes to fork-owned paths (`webui/`, the fork-owned
`.github/workflows/upstream-sync.yml`, `FORK.md` or the root launchers) or to the directly edited `dm/ios/project.yml` stop the run
before any merge and require a human. Other upstream `.github` files, such as
its own test workflows, merge normally. Any failure stops the sync. It leaves
the branch/commit, logs and `.webui-data/upstream-sync/report` evidence, and
creates or updates an Issue (`auto`) or a draft PR/Issue (`review`). There is no
automatic vendor-drop fallback and no fuzzy or 3-way patch application.

### GitHub setup

The workflow needs repository settings that code cannot change:

- Actions allowed to run; enable the workflow in the Actions tab on first use.
- **Settings → Actions → General → Workflow permissions**: read and write.
- Enable **Allow GitHub Actions to create and approve pull requests** for
  `review` mode.
- If `main` is protected, allow the GitHub Actions app to push it (or use a
  ruleset bypass). Required PR reviews, required status checks or linear-history
  rules block the `auto` fast-forward. Without a bypass, use `review` mode.
- Do not protect `auto/upstream-sync`, `review/upstream-sync` or
  `hooks/upstream-sync` against force pushes; the workflow updates automation
  branches with `--force-with-lease`. Do not commit to these branches by hand;
  the next run replaces their history.
- Add an Actions secret named `SYNC_TOKEN` before syncing an upstream change
  that touches `.github/workflows/`. GitHub's `GITHUB_TOKEN` is not allowed to
  create or update workflow files. Use a fine-grained PAT limited to this
  repository with **Contents: Read and write**, **Workflows: Read and write**,
  **Issues: Read and write** and **Pull requests: Read and write** (a classic
  PAT with `repo` and `workflow` also works). The secret is referenced only by
  the push, PR and Issue steps, never by the tests; checkout credentials are
  not persisted. Without it, syncs that do not change workflow files still use
  `GITHUB_TOKEN`, but a workflow change fails with a clear message.
- The workflow otherwise uses only `GITHUB_TOKEN`; no other secret is required.
  Its tests run before the token is given to any push/PR/Issue step.
- GitHub may disable scheduled workflows after long repository inactivity;
  re-enable the workflow if the Actions page reports that.

The first run must be based on a current `origin/main`; push local `main` first.
A scheduled run with no upstream change is a successful no-op. The automation
runs structural, staging and unit checks only, not a real Windows/macOS build
or a game; use `review` mode and a full build when that validation is needed.

### Local use

The same CLI can prepare a branch locally without touching the workflow:

```sh
python webui/tools/sync_upstream.py --mode review --fetch
python webui/tools/sync_upstream.py --mode review --dry-run --fetch --json
python webui/tools/sync_upstream.py --mode review --fetch --push
```

`--push` pushes only the `review/upstream-sync` and internal
`hooks/upstream-sync` branches; it never pushes `main`. Runs require a clean
working tree. On failure the worktrees stay under `.webui-data/auto-*` and the
report is in `.webui-data/upstream-sync/report/`. A failed sync must be
repaired by hand (merge conflicts or patch context) and rerun; do not bypass
`diffapply`.

## Manual fallback

Use the procedure below when the automated port stops on a patch conflict or
when a change needs review before it reaches `main`.

## Recommended sync: merge upstream/main

Because `main` already descends from upstream through the previous vendor drop,
a normal merge is the smallest change while upstream-owned files stay pristine.

```sh
git fetch upstream --prune
git switch -c sync/upstream-$(date +%Y%m%d) main
git merge --no-ff upstream/main
```

Then port the hooks onto a temporary branch from upstream:

```sh
git switch -c hooks/upstream-$(date +%Y%m%d) upstream/main
# Replay the previous hooks commit onto the new upstream, or apply
# webui/patches/*.patch, and resolve the hunks upstream changed:
#   git rebase --onto upstream/main <old upstream> <old hooks branch>
# Keep the fork-only behaviour (POSIX paths, no_dead_strip, the ObjC
# launch settings, --separate-romfs and @NXEVENT).
git commit -am "port fork hooks onto upstream main"
```

Regenerate the patches from the sync branch (which has `webui/`), then run the
checks:

```sh
git switch sync/upstream-$(date +%Y%m%d)
python webui/tools/patch_queue.py regenerate --base upstream/main --hooks hooks/upstream-$(date +%Y%m%d)
git add webui/patches && git commit -m "regenerate hook patches against upstream main"
python webui/tools/patch_queue.py check
python webui/tools/stage.py ensure --rebuild
python webui/tools/stage.py verify
python webui/tools/sync_check.py --base upstream/main --ref upstream/main
python -m unittest discover -s webui/tests -t . -v
```

Then move `main` (fast-forward, no force needed because the sync branch starts
at `main`) and push:

```sh
git switch main && git merge --ff-only sync/upstream-$(date +%Y%m%d)
git push origin main
```

If a hook no longer exists upstream (for example `nvn_mtl.m` was rewritten),
port it by hand and record the new context in the patch; do not force the old
hunk. `sync_check.py --ref upstream/main` applies every patch with
`git apply --check` in a temporary worktree and reports failures.

## Alternative: vendor drop

When the histories have diverged too far for a clean merge, start from
upstream and copy the fork tree:

```sh
git fetch upstream --prune
git switch -c sync/upstream-$(date +%Y%m%d) upstream/main
git checkout main -- webui FORK.md start-webui.bat start-webui.command start-webui.sh
# Re-apply the fullscreen edit to the new dm/ios/project.yml:
#   remove UILaunchStoryboardName, add UILaunchScreen: {}, keep UIRequiresFullScreen: true
git commit -am "vendor drop: upstream main + fork webui"
```

Port the hooks as above, regenerate the patches, run the same checks, then move
`main` to the vendor-drop branch. That rewrite needs a force push: create a
fresh backup branch first and push only a verified branch.

## Publishing the fork

`origin` is `https://github.com/xbunax/nxnative.git`. Push verified branches
normally:

```sh
git push origin main
```

Do not force-push without first creating a fresh backup branch.

## Rollback

- The stage lives only in `.webui-data/stage/`; delete it to rebuild.
- The fork-only layout is a set of new/moved files; `git restore`/`git revert`
  on the refactor commit restores the old layout.
- Patches are plain text; keep the previous `webui/patches/` directory in git
  history so a failed sync can be reverted without re-deriving the diff.
