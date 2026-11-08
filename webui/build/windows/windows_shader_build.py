#!/usr/bin/env python3
"""Materialize and run an isolated Windows port of the pinned shader chain.

The generated sources, native translator and real tool fingerprints define a separate chain ID.
The repository's Mac chain and its lock are never overwritten.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys


def replace(source, old, new):
    if old not in source:
        raise ValueError('Upstream shader source changed: ' + old[:100])
    return source.replace(old, new)


def metal_command(source, name, metal, target, cache):
    """Port the command prefix while retaining upstream shader semantics."""
    assignments = [node for node in ast.parse(source).body
                   if isinstance(node, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == name for t in node.targets)]
    if len(assignments) != 1:
        raise ValueError('Expected one upstream Metal command: ' + name)
    value = assignments[0].value
    command = ast.literal_eval(value)
    if (not isinstance(command, list) or len(command) < 5
            or command[:2] != ['xcrun', '-sdk'] or command[3:5] != ['metal', '-c']
            or not all(isinstance(arg, str) for arg in command)):
        raise ValueError('Unsupported upstream Metal command: ' + name)
    flags = []
    for arg in command[4:]:
        if arg.startswith('-mios-version-min='):
            target = 'air64-apple-ios' + arg.split('=', 1)[1]
        else:
            flags.append(arg)
    result = [metal, '-target', target, *flags, '-fmodules-cache-path=' + str(cache)]
    return replace(source, ast.get_source_segment(source, value), repr(result))



def filesystem_path(path):
    """Use extended paths for Python IO; external tools keep normal paths."""
    path = str(Path(path).resolve())
    if os.name == 'nt' and not str(path).startswith('\\\\?\\'):
        path = '\\\\?\\UNC\\' + path[2:] if path.startswith('\\\\') else '\\\\?\\' + path
    return path


def cache_directory(output, directory=None):
    """Keep the upstream SQLite shader cache usable beyond Windows MAX_PATH."""
    path = Path(directory or Path(output) / 'mac/cas')
    return filesystem_path(path if path.suffix == '.db' else path / 'cas.db')


def publish_chain_header(output, profile):
    """Expose the isolated chain version to the host compiler and IPA packer."""
    profile = Path(profile)
    profile.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(Path(output) / 'chain/gfx/nvn/dmsh_chain.h', profile / 'dmsh_chain.h')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ('profile', 'packages', 'out', 'metal', 'spirv_cross', 'dotnet'):
        ap.add_argument('--' + name.replace('_', '-'), type=Path, required=True)
    ap.add_argument('--cache-dir', type=Path, help='Shared content-addressed shader cache')
    ap.add_argument('--jobs', type=int, default=4)
    ap.add_argument('--prepare-only', action='store_true')
    ap.add_argument('keys', nargs='*')
    a = ap.parse_args()
    repo = Path(__file__).resolve().parents[3]
    root = a.out.resolve()
    tools = root / 'chain/gfx/tools'
    tools.mkdir(parents=True, exist_ok=True)
    original = repo / 'dm/gfx/tools'
    # Include every source hashed by the upstream chain, including Metal helpers
    # and vendored translator changes, without maintaining a second file list.
    chain = runpy.run_path(str(original / 'dmsh_chain.py'))
    for name in chain['FILES']:
        dest = tools.parent / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original.parent / name, dest)
    (tools.parent / 'nvn').mkdir(exist_ok=True)
    for p in original.glob('dmsh_*.py'):
        shutil.copyfile(p, tools / p.name)
    for name in ('c1_guard.py', 'cb_extent.py', 'tool_lock.py', 'shader_regressions.py'):
        shutil.copyfile(original / name, tools / name)
    # Cache and shader images now use the shared tool modules.
    shared = root / 'chain/tools'
    shared.mkdir(parents=True, exist_ok=True)
    for p in (repo / 'dm/tools').glob('*.py'):
        shutil.copyfile(p, shared / p.name)
    romfs = shared / 'romfs.py'
    src = replace(romfs.read_text(encoding='utf-8'), '_os.pread(self.fd, size, self.start + self.pos)',
                  '_windows_pread(self.fd, size, self.start + self.pos)')
    src += '''

def _windows_pread(fd, size, offset):
    # A separate mapping preserves each reader's position without a shared seek.
    size = min(size, max(0, _os.fstat(fd).st_size - offset))
    if not size:
        return b''
    delta = offset % _mmap.ALLOCATIONGRANULARITY
    with _mmap.mmap(fd, size + delta, access=_mmap.ACCESS_READ, offset=offset - delta) as view:
        return view[delta:delta + size]
'''
    romfs.write_text(src, encoding='utf-8')
    for folder in ('dmsh_xlate',):
        shutil.copytree(filesystem_path(original / folder), filesystem_path(tools / folder), dirs_exist_ok=True)
    # Some Ryujinx.Common filenames exceed MAX_PATH under real task folders.
    # Prefix both ends: shutil's recursive copies inherit extended path handling.
    shutil.copytree(filesystem_path(repo / 'dm/third_party/ryujinx'),
                    filesystem_path(root / 'chain/third_party/ryujinx'),
                    dirs_exist_ok=True, ignore=shutil.ignore_patterns('bin', 'obj'))
    # Git's Windows checkout uses CRLF; the pinned translator embeds LF sources.
    for name in ('Program.cs', 'dmsh_xlate.csproj'):
        p = tools / 'dmsh_xlate' / name
        p.write_bytes(p.read_bytes().replace(b'\r\n', b'\n'))
    for folder, filename in (('games', 'game.py'), ('ios/tools', 'ios_metal.py')):
        dest = root / 'chain' / folder
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repo / 'dm' / folder / filename, dest / filename)
    metal = str(a.metal.resolve())
    metallib = str(a.metal.resolve().with_name('metallib.exe'))
    dotnet = str(a.dotnet.resolve())
    dll = str(tools / 'dmsh_xlate_bin/dmsh_xlate.dll')
    sc = str(a.spirv_cross.resolve())
    cache = root / 'module_cache'
    cache.mkdir(exist_ok=True)
    build = (tools / 'dmsh_build.py').read_text(encoding='utf-8')
    build = metal_command(build, 'MAC_METAL', metal, 'air64-apple-macos14.0', cache)
    build = replace(build, "'; xcrun -sdk macosx metallib'", repr('; ' + metallib))
    build = replace(build, "[xcrun_out('-f', 'metal'), '-isysroot', xcrun_out('--show-sdk-path'), *MAC_METAL[4:]]", 'MAC_METAL')
    build = replace(build, "[xcrun_out('-f', 'metallib')]", repr([metallib]))
    build = replace(build, '[XLATE, jp, w]', repr([dotnet, dll]) + ' + [jp, w]')
    (tools / 'dmsh_build.py').write_text(build, encoding='utf-8')
    ip = root / 'chain/ios/tools/ios_metal.py'
    src = ip.read_text(encoding='utf-8')
    src = metal_command(src, 'METAL', metal, 'air64-apple-ios18.0', cache)
    src = replace(src, "['xcrun', '-sdk', 'iphoneos', 'metallib']", repr([metallib]))
    ip.write_text(src, encoding='utf-8')
    cp = tools / 'dmsh_mtlcache.py'
    src = cp.read_text(encoding='utf-8')
    line = next(x for x in src.splitlines() if x.startswith('_clonefile ='))
    src = replace(src, line, '_clonefile = None')
    start, end = src.index('def compiler_id('), src.index('\n\nclass Cache:')
    identity = json.dumps({str(Path(x).name): hashlib.sha256(Path(x).read_bytes()).hexdigest()
                           for x in (metal, metallib, sc)}, sort_keys=True)
    src = src[:start] + 'def compiler_id(sdk):\n    return sdk + ' + repr(identity) + '\n' + src[end:]
    cp.write_text(src, encoding='utf-8')
    cp = tools / 'tool_lock.py'
    src = cp.read_text(encoding='utf-8')
    src = replace(src, "[os.path.join(XLATE_DIR, 'dmsh_xlate'), '--source-sha']", repr([dotnet, dll, '--source-sha']))
    src = replace(src, "['xcrun', '-sdk', sdk, 'metal', '--version']", repr([metal, '--version']))
    src = replace(src, '    return t\n', '    t["windows_tools"] = ' + repr(identity) + '\n    return t\n')
    cp.write_text(src, encoding='utf-8')
    cp = tools / 'dmsh_chain.py'
    src = replace(cp.read_text(encoding='utf-8'), "'tools/dmsh_chain.lock']",
                  "'tools/dmsh_chain.lock', 'tools/windows_shader_build.py', 'tools/dmsh_mtlcache.py']")
    cp.write_text(src, encoding='utf-8')
    # Windows indexers can briefly hold a newly written cache file without
    # delete sharing. Retry the same atomic operation; never discard a failure.
    retry = '''
import time
def windows_replace(source, destination):
    for attempt in range(40):
        try:
            os.replace(source, destination)
            return
        except PermissionError as error:
            if getattr(error, 'winerror', None) not in (5, 32, 33) or attempt == 39:
                raise
            time.sleep(0.1)

'''
    for name in ('dmsh_build.py', 'dmsh_mtlcache.py'):
        p = tools / name
        src = p.read_text(encoding='utf-8').replace('os.replace(', 'windows_replace(')
        # Place the helper before top-level build/cache initialization.
        anchor = 'DM_ROOT = ' if name == 'dmsh_build.py' else 'FORMAT = '
        position = src.index(anchor)
        p.write_text(src[:position] + retry + src[position:], encoding='utf-8')
    shutil.copyfile(__file__, tools / 'windows_shader_build.py')
    env = dict(os.environ, DM_GAME=str(a.profile.resolve()), XLATE=str(Path(dll).with_suffix('')),
               SPIRV_CROSS=sc, PYTHONUTF8='1', J=str(a.jobs), IOSOUT=str(root / 'ios'), WORK=str(root / 'work'),
               DOTNET_ROOT=str(a.dotnet.resolve().parent), DMSH_PCH='0',
               DOTNET_CLI_UI_LANGUAGE='en', DOTNET_CLI_TELEMETRY_OPTOUT='1',
               DOTNET_SKIP_FIRST_TIME_EXPERIENCE='1', DOTNET_GENERATE_ASPNET_CERTIFICATE='false',
               DOTNET_CLI_HOME=os.environ.get('DOTNET_CLI_HOME', str(root / '.dotnet')),
               NUGET_PACKAGES=os.environ.get('NUGET_PACKAGES', str(a.dotnet.resolve().parents[1] / 'nuget')))
    # CAS holds only Python-managed files; external compilers use WORK and IOSOUT.
    # Prefix the cache root so atomic copies and JSON writes can exceed MAX_PATH.
    env['DMSH_CAS'] = cache_directory(root, a.cache_dir or env.get('DMSH_CAS'))
    print('Shader cache: ' + env['DMSH_CAS'], flush=True)
    (root / 'work').mkdir(exist_ok=True)
    # Verify the original translator before generating a distinct Windows lock.
    lock = dict(x.split('\t', 1) for x in (original / 'dmsh_chain.lock').read_text(encoding='utf-8').splitlines() if '\t' in x and not x.startswith('#'))
    for name in ('dmsh_xlate.dll', 'Ryujinx.Graphics.Shader.dll', 'Ryujinx.Common.dll'):
        if hashlib.sha256((original / 'dmsh_xlate_bin' / name).read_bytes()).hexdigest()[:16] != lock[name]:
            raise ValueError('Pinned translator differs: ' + name)
    # Upstream's macOS ARM64 ReadyToRun assemblies cannot load in Windows x64
    # dotnet. Build the same sources as portable IL; fingerprint these outputs in
    # the isolated Windows lock rather than changing the upstream binaries/lock.
    subprocess.run([dotnet, 'publish', str(tools / 'dmsh_xlate/dmsh_xlate.csproj'),
                    '-c', 'Release', '-o', str(Path(dll).parent), '--self-contained', 'false',
                    '-p:PublishReadyToRun=false', '-p:UseAppHost=false'], env=env, check=True)
    subprocess.run([sys.executable, str(tools / 'tool_lock.py'), '--update-lock'], env=env, check=True)
    subprocess.run([sys.executable, str(tools / 'tool_lock.py'), '--check-tools'], env=env, check=True)
    subprocess.run([sys.executable, str(cp), '--header'], env=env, check=True)
    publish_chain_header(root, a.profile.resolve())
    (root / 'windows_tools.json').write_text(identity + '\n', encoding='utf-8')
    if not a.prepare_only:
        subprocess.run([sys.executable, str(tools / 'dmsh_build.py'), str(a.packages.resolve()), str(root / 'mac'), *a.keys], env=env, check=True)
        # Keep the Windows packer's folder input; upstream builds shader images.
        chain = runpy.run_path(str(cp))['version']()
        for target in ('mac', 'ios'):
            subprocess.run([sys.executable, str(shared / 'shader_lib.py'), 'expand',
                            str(root / target / ('b-' + chain))], env=env, check=True)


if __name__ == '__main__':
    main()
