"""Materialize a build staging tree from the working tree.

The stage is a full copy (never a writable hardlink) of the repository with the
fork's source overlays and the upstream hook patches applied; for the 'objc' launcher the ObjC port replaces
upstream's Swift launcher files; 'swiftui' keeps them with the UI hook patches. Builds run
only from the stage, so the working tree's upstream files stay untouched.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import time
import uuid

from . import diffapply
from .repo import REPO

STAGING_VERSION = 1
OVERLAY_ROOT = REPO / 'webui' / 'overlays'
PATCH_ROOT = REPO / 'webui' / 'patches'

LAUNCHERS = ('objc', 'swiftui')   # which iOS launcher a stage carries: the fork's ObjC port, or upstream's Swift one
# Fork-only source files placed into an 'objc' stage (webui/overlays/<target>): the ObjC port of the launcher ...
OVERLAY_TARGETS = {
    'dm/ios/Sources/DmLauncher.m',
}
# ... and the upstream files it replaces (both define dm_show_launcher): removed from an 'objc' stage
OBJC_REMOVED = (
    'dm/ios/Sources/Launcher.swift',
    'dm/ios/Sources/LauncherRow.swift',
    'dm/ios/Sources/LauncherSettings.swift',
    'dm/ios/Sources/GameMenu.swift',
    'dm/ios/Sources/DmHostingController.swift',
)

SKIP_DIR_NAMES = {'.git', '.webui-data', '.claude', '__pycache__', '.venv', 'venv', 'node_modules'}
SKIP_DIR_PREFIXES = ('.iosdd',)
SKIP_REL_PREFIXES = (
    'dm/ios/Gen',
    'dm/ios/DmIOS.xcodeproj',
    'dm/host/gen',
    'dm/tools/nx_extract/bin',
    'dm/tools/nx_extract/obj',
)
SKIP_FILES = {'dm/ios/Sources/Info.plist'}


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _skipped_dir(rel: str, name: str) -> bool:
    if name in SKIP_DIR_NAMES or name.startswith(SKIP_DIR_PREFIXES):
        return True
    return any(rel == prefix or rel.startswith(prefix + '/') for prefix in SKIP_REL_PREFIXES)


def _skipped_file(rel: str, name: str) -> bool:
    if name.endswith('.pyc') or name == '.git' or rel in SKIP_FILES:
        return True
    return any(rel.startswith(prefix + '/') for prefix in SKIP_REL_PREFIXES)


def iter_files(root: Path = REPO, stage_root: Path | None = None):
    """Yield source files in a deterministic order, excluding generated/local data."""
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = sorted(os.scandir(current), key=lambda e: e.name)
        except OSError:
            continue
        for entry in entries:
            path = Path(entry.path)
            if stage_root is not None and (path == stage_root or str(path).startswith(str(stage_root) + os.sep)):
                continue
            rel = _rel(path, root)
            if entry.is_dir(follow_symlinks=False):
                if _skipped_dir(rel, entry.name):
                    continue
                stack.append(path)
            elif entry.is_file(follow_symlinks=False):
                if _skipped_file(rel, entry.name):
                    continue
                yield path


def patch_queue(root: Path = PATCH_ROOT):
    series = (root / 'series').read_text(encoding='utf-8').splitlines()
    queue = []
    for line in series:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split()
        if len(parts) != 2:
            raise ValueError(f'malformed patch series line: {line!r}')
        patch, target = parts
        if target.startswith('/') or '..' in Path(target).parts:
            raise ValueError(f'unsafe patch target: {target!r}')
        queue.append((root / patch, target))
    return queue


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _overlay_targets(launcher: str):
    return sorted(OVERLAY_TARGETS) if launcher == 'objc' else []


def compute_key(root: Path = REPO, stage_root: Path | None = None, launcher: str = 'objc') -> str:
    if launcher not in LAUNCHERS:
        raise ValueError(f'unknown launcher: {launcher!r}')
    digest = hashlib.sha256()
    digest.update(f'{STAGING_VERSION}\0{platform.system()}\0{launcher}\0'.encode())
    for path in iter_files(root, stage_root):
        stat = path.stat()
        digest.update(f'{_rel(path, root)}\0{stat.st_size}\0{stat.st_mtime_ns}\n'.encode())
    for patch, target in patch_queue():
        digest.update(patch.relative_to(root).as_posix().encode() + b'\0')
        digest.update(target.encode() + b'\0')
        digest.update(patch.read_bytes())
    for target in _overlay_targets(launcher):
        source = OVERLAY_ROOT / target
        if not source.is_file():
            raise ValueError(f'missing overlay: {source}')
        digest.update(target.encode() + b'\0')
        digest.update(source.read_bytes())
    return digest.hexdigest()[:16]


@contextmanager
def _lock(path: Path, timeout: float = 300.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open('a+b')
    try:
        handle.seek(0)
        if os.name == 'nt':
            import msvcrt
            deadline = time.monotonic() + timeout
            while True:
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f'cannot lock {path}')
                    time.sleep(0.1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX)
        yield
    finally:
        try:
            if os.name == 'nt':
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_UN)
        except OSError:
            pass
        handle.close()


def _write(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f'.stage-{os.getpid()}-{uuid.uuid4().hex[:8]}')
    temporary.write_bytes(data)
    os.replace(temporary, path)


def _copy_tree(root: Path, tree: Path, stage_root: Path):
    for source in iter_files(root, stage_root):
        destination = tree / source.relative_to(root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def ensure(root: Path = REPO, stage_root: Path | None = None, force: bool = False, keep: int | None = None,
           launcher: str = 'objc') -> Path:
    """Create or reuse a stage; return the tree directory inside it.

    launcher 'objc' puts the ObjC port in place of Swift; 'swiftui' keeps Swift with the UI hooks."""
    stage_root = Path(stage_root or os.environ.get('NX_STAGE_ROOT') or root / '.webui-data' / 'stage')
    stage_root = stage_root.expanduser().resolve()
    stage_root.mkdir(parents=True, exist_ok=True)
    if keep is None:
        keep = int(os.environ.get('NX_STAGE_KEEP', '4'))
    with _lock(stage_root / '.lock'):
        key = compute_key(root, stage_root, launcher)
        final = stage_root / key
        manifest = final / 'stage.json'
        if not force and manifest.is_file():
            try:
                value = json.loads(manifest.read_text(encoding='utf-8'))
                if value.get('status') == 'complete' and value.get('key') == key:
                    return final / 'tree'
            except (OSError, ValueError):
                pass
        if final.exists():
            shutil.rmtree(final, ignore_errors=True)
        building = stage_root / f'.building-{uuid.uuid4().hex}'
        tree = building / 'tree'
        try:
            tree.mkdir(parents=True)
            _copy_tree(root, tree, stage_root)
            overlays = []
            if launcher == 'objc':
                for target in OBJC_REMOVED:
                    (tree / target).unlink(missing_ok=True)
            for target in _overlay_targets(launcher):
                source = OVERLAY_ROOT / target
                if not source.is_file():
                    raise ValueError(f'missing overlay: {source}')
                destination = tree / target
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                overlays.append({'target': target, 'sha256': _hash(source.read_bytes())})
            patches = []
            log = []
            for patch, target in patch_queue():
                if launcher == 'objc' and target in OBJC_REMOVED:
                    continue   # Swift-only UI hooks; the ObjC overlay implements them.
                target_path = tree / target
                if not target_path.is_file():
                    raise ValueError(f'patch target missing: {target}')
                before = target_path.read_bytes()
                after = diffapply.apply_bytes(before, patch.read_bytes(), target)
                _write(target_path, after)
                rows = {'file': patch.name, 'target': target,
                        'before_sha256': _hash(before), 'sha256': _hash(after)}
                patches.append(rows)
                log.append(f'{patch.name} -> {target} ({len(before)} -> {len(after)} bytes)')
            record = {
                'version': STAGING_VERSION,
                'status': 'complete',
                'key': key,
                'created': time.time(),
                'platform': platform.system(),
                'launcher': launcher,
                'removed': list(OBJC_REMOVED) if launcher == 'objc' else [],
                'repo': str(root),
                'patches': patches,
                'overlays': overlays,
            }
            (building / 'patch.log').write_text('\n'.join(log) + '\n', encoding='utf-8')
            (building / 'stage.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
            try:
                os.replace(building, final)
            except OSError:
                if not manifest.is_file():
                    raise
                shutil.rmtree(building, ignore_errors=True)
            _gc(stage_root, key, keep)
            return final / 'tree'
        except Exception:
            shutil.rmtree(building, ignore_errors=True)
            raise


def _gc(stage_root: Path, current: str, keep: int):
    keep = max(1, keep)
    complete = []
    for entry in stage_root.iterdir():
        if not entry.is_dir():
            continue
        if entry.name.startswith('.building-'):
            continue
        if (entry / 'stage.json').is_file():
            complete.append(entry)
    complete.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    preserved = {current}
    for entry in complete:
        if len(preserved) >= keep:
            break
        preserved.add(entry.name)
    for entry in complete:
        if entry.name not in preserved:
            shutil.rmtree(entry, ignore_errors=True)


def verify(stage: Path) -> dict:
    stage = Path(stage)
    if (stage / 'tree').is_dir():
        tree = stage / 'tree'
        record_path = stage / 'stage.json'
    else:
        tree = stage
        record_path = stage.parent / 'stage.json'
    record = json.loads(record_path.read_text(encoding='utf-8'))
    if record.get('status') != 'complete':
        raise ValueError('stage is not complete')
    for item in record.get('overlays', []):
        target = tree / item['target']
        if not target.is_file() or _hash(target.read_bytes()) != item['sha256']:
            raise ValueError(f'overlay changed: {item["target"]}')
    for name in record.get('removed', []):
        if (tree / name).exists():
            raise ValueError(f'removed file is back: {name}')
    for item in record.get('patches', []):
        target = tree / item['target']
        if not target.is_file() or _hash(target.read_bytes()) != item['sha256']:
            raise ValueError(f'patched target changed: {item["target"]}')
    project = (tree / 'dm/ios/project.yml').read_text(encoding='utf-8')
    if 'UILaunchScreen:' not in project or 'UIRequiresFullScreen: true' not in project:
        raise ValueError('stage project.yml lacks fullscreen keys')
    return record


def stage_path(stage_root: Path | None = None, launcher: str = 'objc') -> Path:
    root = Path(stage_root or os.environ.get('NX_STAGE_ROOT') or REPO / '.webui-data' / 'stage')
    return ensure(REPO, root, launcher=launcher)
