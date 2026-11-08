#!/usr/bin/env python3
"""Build an unsigned IPA for an existing NVN game profile on Windows.

Run from a terminal or edit Settings and use Spyder F5. The original Mac
profile is copied into the game's build folder before adapting the chain.
With --provisional, the profile may be a WebUI survey: build IDs and shader
evidence are generated from this extraction instead of compared with it.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

# ---- Settings (command-line options override these) ----
NSP_DIR = ''
GAME = ''
PROD_KEYS = ''
OUT_IPA = ''
TOOL_DIR = ''
METAL = ''
JOBS = 12


def main():
    repo = Path(__file__).resolve().parents[3]
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('folder', nargs='?', default=NSP_DIR)
    ap.add_argument('--game', default=GAME)
    ap.add_argument('--keys', type=Path, default=Path(PROD_KEYS) if PROD_KEYS else None)
    ap.add_argument('--out', type=Path, default=Path(OUT_IPA) if OUT_IPA else None)
    ap.add_argument('--tools', type=Path, default=Path(TOOL_DIR) if TOOL_DIR else None)
    ap.add_argument('--metal', type=Path, default=Path(METAL) if METAL else None)
    ap.add_argument('--jobs', type=int, default=JOBS)
    ap.add_argument('--sdk', type=Path, help='User-supplied iPhoneOS SDK')
    ap.add_argument('--env-file', type=Path)
    ap.add_argument('--language', help='the launcher\'s default game language')
    ap.add_argument('--separate-romfs', action='store_true', help='Leave the RomFS out of the IPA and write <ipa>.romfs.zip')
    ap.add_argument('--provisional', action='store_true', help='Build from a provisional profile (build IDs and shader evidence are generated from this extraction)')
    ap.add_argument('--font', type=Path, default=Path('C:/Windows/Fonts/msyh.ttc'))
    ap.add_argument('--letter-font', type=Path, default=Path('C:/Windows/Fonts/arialbd.ttf'))
    a = ap.parse_args()
    if not a.folder:
        if not sys.stdin.isatty():
            ap.error('Set NSP_DIR or provide an NSP folder')
        a.folder = input('NSP folder: ').strip().strip('"')
    if not a.keys or not a.tools: ap.error('Supply --keys and --tools, or fill the settings block')
    folder, tools = Path(a.folder).resolve(), a.tools.resolve()
    a.metal = a.metal or Path(os.environ.get('METAL_EXE') or tools / 'metal/metal.exe')
    if not a.metal.is_file(): ap.error('Supply --metal with your installed Metal compiler')
    sys.path.insert(0, str(repo / 'dm/games'))
    import game
    nsps = sorted(folder.rglob('*.nsp'))
    ids = {}
    for p in nsps:
        match = re.search(r'(?i)(?<![0-9a-f])([0-9a-f]{16})(?![0-9a-f])', p.name)
        if match:
            ids.setdefault(int(match[1], 16), []).append(p)
    candidates = [g for g in game.all_games() if g.title_id in ids]
    if a.game:
        original = game.load(a.game)
    elif len(candidates) == 1:
        original = candidates[0]
    else:
        ap.error('Specify --game with one existing game profile ID')
    version = original.get('package')
    if original.get('graphics', 'nvn') != 'nvn' or any(original.get(k, 'off') == 'on' for k in ('shader_glslc_capture', 'shader_vk_capture')):
        ap.error('This workflow needs an offline NVN profile without runtime shader capture')
    if original.words('shader_versions') != [version]:
        ap.error('This workflow currently requires one shader version matching package')
    bases = ids.get(original.title_id, [])
    updates = [p for p in ids.get(original.title_id + 0x800, []) if version.lower() in p.name.lower()]
    if len(bases) != 1 or (version != 'v0' and len(updates) != 1):
        ap.error(f'Expected one base NSP and the registered {version} update NSP')
    build = folder / (original.id + '_build')
    logs, temporary = build / 'logs', build / 'tmp'
    logs.mkdir(parents=True, exist_ok=True)
    temporary.mkdir(exist_ok=True)
    profile = build / 'profile' / original.id
    shutil.copytree(original.dir, profile, dirs_exist_ok=True)
    g = game.Game(profile)
    env = dict(os.environ, DOTNET_ROOT=str(tools / 'dotnet'), PYTHONUTF8='1', PYTHONPATH=str(tools / 'python-packages'),
               DM_GAME=str(profile), DM_ROOT=str(build), DM_RULESET='native',
               J=str(a.jobs), TEMP=str(temporary), TMP=str(temporary),
               DOTNET_CLI_HOME=str(tools / '.dotnet'))
    env['PATH'] = str(tools / 'dotnet') + os.pathsep + env.get('PATH', '')
    python = sys.executable
    started = time.monotonic()
    def count_files(root, suffix):
        total = 0
        if not Path(root).is_dir(): return 0
        for _, _, names in os.walk(root):
            total += sum(1 for name in names if name.endswith(suffix))
        return total
    def run(label, command, output=None, progress=None):
        if os.environ.get('NX_PROGRESS'):
            print('@NXEVENT ' + json.dumps({'name': label}), flush=True)
        print(f'[{time.strftime("%H:%M:%S")}] {label}', flush=True)
        log = logs / (label + '.log')
        step_started = time.monotonic()
        with log.open('w', encoding='utf-8') as stream:
            process = subprocess.Popen([str(x) for x in command], env=env, cwd=repo,
                                       stdout=stream, stderr=subprocess.STDOUT)
            last = step_started
            while process.poll() is None:
                time.sleep(0.5)
                now = time.monotonic()
                if now - last < 10: continue
                last = now
                line = None
                if progress:
                    try: line = progress()
                    except Exception: line = None
                if not line:
                    elapsed = int(now - step_started)
                    line = f'{label} running {elapsed // 60}:{elapsed % 60:02d}'
                print(f'[{time.strftime("%H:%M:%S")}] {line}', flush=True)
                if os.environ.get('NX_PROGRESS'):
                    print('@NXEVENT ' + json.dumps({'name': line}), flush=True)
            code = process.wait()
        elapsed = time.monotonic() - step_started
        if code:
            print('\n'.join(log.read_text(encoding='utf-8', errors='replace').splitlines()[-40:]), flush=True)
            raise RuntimeError(f'{label} failed ({code}) after {elapsed:.1f}s; see {log}')
        print(f'[{time.strftime("%H:%M:%S")}] {label} finished in {elapsed:.1f}s', flush=True)
        if output:
            shutil.copyfile(log, output)

    extracted = build / 'extract' / version
    sentinel = extracted / '.extraction_complete'
    inputs = [{'path': str(p), 'bytes': p.stat().st_size, 'mtime_ns': p.stat().st_mtime_ns}
              for p in bases + updates]
    if not sentinel.exists() or json.loads(sentinel.read_text()) != inputs:
        run('extract_' + version, [tools / 'nx_extract/nx_extract.exe', a.keys.resolve(), bases[0],
                                   updates[0] if updates else '-', extracted])
        sentinel.write_text(json.dumps(inputs, indent=2), encoding='utf-8')
    wanted = g.builds()[version]
    if not a.provisional:
        for module in g.words('modules'):
            got = (extracted / 'ExeFS' / module).read_bytes()[0x40:0x50].hex()
            if got != wanted[module]:
                raise ValueError(f'{module} build ID differs: {got} / expected {wanted[module]}')
    import profile_guess
    sources = profile_guess.build_sources(extracted / 'ExeFS', extracted / 'RomFS', g.words('modules'))
    if sources['graphics'][0] != 'nvn' or any(sources[k][0] for k in ('glslc_capture', 'vk_capture', 'ue_decode', 'oodle_packs')):
        raise ValueError('This game requires the Mac build workflow: ' + str(sources))
    env['MAIN'] = str(extracted / 'ExeFS/main')
    aoc = build / 'aoc'
    for tid, paths in sorted(ids.items()):
        index = tid - original.title_id - 0x1000
        if 0 <= index < 0x1000:
            if len(paths) != 1:
                raise ValueError('Multiple DLC NSPs for one title ID')
            target = aoc / str(index)
            marker = build / ('aoc_' + str(index) + '.complete')
            identity = {'path': str(paths[0]), 'bytes': paths[0].stat().st_size, 'mtime_ns': paths[0].stat().st_mtime_ns}
            if not marker.exists() or json.loads(marker.read_text()) != identity:
                run('aoc_' + str(index), [tools / 'nx_extract/nx_extract.exe', a.keys.resolve(), '--aoc', paths[0], target])
                # Keep the sentinel outside the shipped DLC data.
                marker.write_text(json.dumps(identity, indent=2), encoding='utf-8')
    patched = build / ('patched_' + version)
    patched.mkdir(exist_ok=True)
    for module in g.words('modules'):
        run('rewrite_' + module, [python, repo / 'dm/tools/patch_nso.py', extracted / 'ExeFS' / module, patched, module])
    run('verify_rewrite', [python, repo / 'webui/build/windows/verify_nso_rewrite.py', extracted / 'ExeFS', patched,
                           *g.words('modules'), '--report', build / 'rewrite_verification.json'])
    shader = build / 'shader'
    tables = shader / 'tables'
    tables.mkdir(parents=True, exist_ok=True)
    names = ('shader_map.tsv', 'shader_facts.tsv', 'shader_pairs.tsv')
    split_marker = shader / 'verified_sources.json'
    nso_sha = hashlib.sha256((extracted / 'ExeFS/main').read_bytes()).hexdigest()
    saved = json.loads(split_marker.read_text()) if split_marker.exists() else {}
    reusable = (saved.get('inputs') == inputs and saved.get('main_sha256') == nso_sha and
                bool(saved.get('files')) and all((shader / name).is_file() and
                    hashlib.sha256((shader / name).read_bytes()).hexdigest() == digest
                    for name, digest in saved.get('files', {}).items()))
    if not reusable:
        run('shader_split', [python, repo / 'dm/gfx/tools/shader_split.py', extracted / 'RomFS', extracted / 'ExeFS/main',
                             shader / 'packages', *[tables / name for name in names]])
    def rows(p):
        return [line for line in p.read_bytes().splitlines() if not line.startswith(b'#')]
    if a.provisional:
        for name in names:
            shutil.copyfile(tables / name, profile / name)
    else:
        for name in names:
            if rows(tables / name) != rows(original.table(name)):
                raise ValueError(f'{name} differs from the existing profile; refusing to replace its evidence')
    files = sorted((shader / 'packages').glob('*.bin')) + [tables / name for name in names]
    split_marker.write_text(json.dumps(dict(inputs=inputs, main_sha256=nso_sha,
        files={p.relative_to(shader).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}), indent=2), encoding='utf-8')
    print('Shader evidence tables generated from this extraction' if a.provisional
          else 'All shader evidence tables match the existing profile exactly', flush=True)
    windows = build / 'windows_shaders'
    shader_rows = [line.split('\t') for line in (tables / 'shader_map.tsv').read_text(encoding='utf-8').splitlines()
                   if line and not line.startswith('#')]
    shader_total = len({row[3] for row in shader_rows if len(row) > 3})
    def shader_progress():
        done = min(count_files(windows / 'ios', '_b.json'), shader_total)
        return (f'windows_shaders {done}/{shader_total} shaders ({100 * done / shader_total:.1f}%)'
                if shader_total else None)
    run('windows_shaders', [python, repo / 'webui/build/windows/windows_shader_build.py', '--profile', profile,
                            '--packages', shader / 'packages', '--out', windows, '--metal', a.metal.resolve(),
                            '--spirv-cross', tools / 'spirv-cross-build/spirv-cross.exe',
                            '--dotnet', tools / 'dotnet/dotnet.exe', '--cache-dir', tools / 'shader-cache', '--jobs', a.jobs],
        progress=shader_progress)
    chain = re.search(r'#define DMSH_CHAIN "([a-f0-9]+)"', g.table('dmsh_chain.h').read_text())[1]
    run('c1_guard', [python, repo / 'dm/gfx/tools/c1_guard.py', windows / ('mac/b-' + chain), g.table('c1_full.tsv')])
    host = build / 'windows_host'
    clang = tools / 'ios-cross/toolchain/windows/iphone/bin/clang.exe'
    sdk = a.sdk.resolve() if a.sdk else tools / 'ios-cross/iPhoneOS26.5.sdk'
    sys.path.insert(0, str(Path(__file__).parent))
    try:
        import ios_cross_compile
        host_total = len(ios_cross_compile.source_list(repo))
    except Exception:
        host_total = 0
    host_started = time.time()
    def host_progress():
        if not host_total: return None
        done = sum(1 for p in (host / 'objects').glob('*.o') if p.stat().st_mtime >= host_started - 5)
        return f'host_compile {done}/{host_total} sources'
    run('host_compile', [python, repo / 'webui/build/windows/ios_cross_compile.py', '--clang', clang, '--sdk', sdk,
                         '--metal', a.metal.resolve(), '--profile', profile, '--out', host, '--jobs', min(a.jobs, 8)], progress=host_progress)
    run('embed_generate', [python, repo / 'dm/ios/tools/gen_embed.py', patched, host / 'embed.S', *g.words('modules')], host / 'embed_link_flags.txt')
    run('embed_assemble', [clang, '-target', 'arm64-apple-ios26.0', '-isysroot', sdk, '-mcpu=apple-a16',
                           '-x', 'assembler', '-c', host / 'embed.S', '-o', host / 'embed.o'])
    run('host_link', [python, repo / 'webui/build/windows/ios_cross_link.py', '--lld', clang.with_name('lld.exe'), '--sdk', sdk, '--build', host])
    from_font = a.font.resolve()
    if from_font.suffix.lower() == '.ttc':
        sys.path.insert(0, str(tools / 'python-packages'))
        from fontTools.ttLib import TTFont
        font = TTFont(from_font, fontNumber=0)
        from_font = build / 'standard.ttf'
        font.save(from_font)
        font.close()
    ipa = a.out.resolve() if a.out else folder / g.get('ipa')
    command = [python, repo / 'webui/build/windows/ios_cross_pack.py', '--profile', profile, '--host', host,
               '--patched', patched, '--romfs', extracted / 'RomFS', '--shaders', windows / 'ios',
               '--font', from_font, '--letter-font', a.letter_font.resolve(), '--out', ipa]
    if aoc.exists():
        command += ['--aoc', aoc]
    if a.env_file: command += ['--env-file', a.env_file.resolve()]
    if a.language: command += ['--language', a.language]
    if (extracted / 'control.nacp').exists():
        command += ['--nacp', extracted / 'control.nacp']
    if a.separate_romfs: command += ['--omit-romfs']
    if (extracted / 'icon.jpg').exists():
        command += ['--icon', extracted / 'icon.jpg']
    run('ipa_pack', command)
    with ipa.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    archive_digest = None
    archive = None
    if a.separate_romfs:
        sys.path.insert(0, str(repo))
        from webui.build.romfs_archive import (archive_path, pack_command, prepare_archive,
                                               verify_archive, verify_no_romfs)
        romfs = extracted / 'RomFS'
        marker = g.get('romfs_marker')
        archive = archive_path(ipa)
        prepare_archive(archive, romfs, marker)
        run('romfs_archive', pack_command(python, repo / 'dm/ios/tools/pack_ipa.py',
                                          archive, romfs, g.get('zip_store', '')))
        verify_archive(archive, marker)
        verify_no_romfs(ipa)
        with archive.open('rb') as stream:
            archive_digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    report_path = ipa.with_suffix('.verification.json')
    report = json.loads(report_path.read_text(encoding='utf-8'))
    report['ipa_sha256'] = digest
    report['shader_evidence_matches_existing_profile'] = not a.provisional
    report['provisional_profile'] = bool(a.provisional)
    report['provisional_profile_path'] = str(original.dir) if a.provisional else None
    report['may_not_boot'] = bool(a.provisional)
    if archive is not None:
        report.update(romfs_separate=True, romfs_bundled=False,
                      romfs_archive=str(archive.resolve()), romfs_archive_sha256=archive_digest)
    report['elapsed_seconds'] = round(time.monotonic() - started, 1)
    report_path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(f'Completed: {ipa}\nSHA-256: {digest}', flush=True)
    if archive is not None:
        print(f'RomFS archive: {archive}\nSHA-256: {archive_digest}', flush=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError) as error:
        print('【红】' + str(error), file=sys.stderr)
        raise SystemExit(1)
