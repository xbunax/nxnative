#!/usr/bin/env python3
"""Assemble and verify an unsigned IPA from the Windows cross-build outputs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import zipfile


def base_info_plist(*, game_id, display_name, app_version, app_category):
    """Return the bundle Info.plist shared by the Windows IPA packer.

    UILaunchScreen is deliberately an empty dictionary: it opts into a native
    full-resolution launch screen. UIRequiresFullScreen is kept for iPhone
    fullscreen behavior; iPadOS 26 deprecates it for windowing.
    """
    return dict(
        CFBundleExecutable='DmIOS',
        CFBundleIdentifier='org.nxnative.' + game_id.lower(),
        CFBundleName='DmIOS',
        CFBundleDisplayName=display_name,
        CFBundlePackageType='APPL',
        CFBundleVersion=app_version,
        CFBundleShortVersionString=app_version,
        MinimumOSVersion='26.0',
        CFBundleSupportedPlatforms=['iPhoneOS'],
        LSRequiresIPhoneOS=True,
        UIDeviceFamily=[1, 2],
        UILaunchScreen={},
        UIFileSharingEnabled=True,
        LSSupportsOpeningDocumentsInPlace=True,
        UISupportedInterfaceOrientations=['UIInterfaceOrientationLandscapeRight',
                                          'UIInterfaceOrientationLandscapeLeft'],
        **{'UISupportedInterfaceOrientations~ipad': ['UIInterfaceOrientationPortrait',
            'UIInterfaceOrientationPortraitUpsideDown', 'UIInterfaceOrientationLandscapeRight',
            'UIInterfaceOrientationLandscapeLeft']},
        UIRequiresFullScreen=True,
        UIStatusBarHidden=True,
        UIViewControllerBasedStatusBarAppearance=False,
        LSApplicationCategoryType=app_category,
        LSSupportsGameMode=True,
        GCSupportsControllerUserInteraction=True,
        GCSupportedGameControllers=[dict(ProfileName='ExtendedGamepad')],
        CADisableMinimumFrameDurationOnPhone=True,
        UIApplicationSceneManifest=dict(
            UIApplicationSupportsMultipleScenes=False,
            UISceneConfigurations=dict(
                UIWindowSceneSessionRoleApplication=[
                    dict(UISceneConfigurationName='Default',
                         UISceneDelegateClassName='SceneDelegate')],
                UIWindowSceneSessionRoleExternalDisplayNonInteractive=[
                    dict(UISceneConfigurationName='TV', UISceneDelegateClassName='DmTVSceneDelegate')],
            ),
        ),
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ('profile', 'host', 'patched', 'romfs', 'shaders', 'font', 'letter_font', 'out'):
        ap.add_argument('--' + name.replace('_', '-'), type=Path, required=True)
    ap.add_argument('--aoc', type=Path)
    ap.add_argument('--env-file', type=Path)
    ap.add_argument('--nacp', type=Path, help='control.nacp (default: beside the RomFS folder); the launcher settings use its languages')
    ap.add_argument('--language', help='the launcher\'s default game language (the Game language row)')
    ap.add_argument('--icon', type=Path)
    ap.add_argument('--prepare-only', action='store_true')
    ap.add_argument('--omit-romfs', action='store_true', help='Leave the RomFS out of the IPA (the separate archive is made by the caller)')
    ap.add_argument('--allow-incomplete-shaders', action='store_true', help='Produce an experimental IPA and record every missing shader')
    ap.add_argument('--experimental', action='store_true', help='Mark runtime features as experimental even when all shaders are present')
    a = ap.parse_args()
    repo = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(repo / 'dm/games'))
    import game
    try:
        from ios_cross_link import macho_layout
    except ImportError:
        from .ios_cross_link import macho_layout
    g = game.Game(a.profile)
    app_version = g.builds()[g.get('package')]['display']
    chain = re.search(r'#define DMSH_CHAIN "([a-f0-9]+)"', g.table('dmsh_chain.h').read_text()).group(1)
    stage = a.host / 'package_resources'
    dm = stage / 'dm'
    (dm / 'font').mkdir(parents=True, exist_ok=True)
    if a.env_file: shutil.copyfile(a.env_file, dm / 'env.txt')
    else: (dm / 'env.txt').unlink(missing_ok=True)
    # the launcher's settings for this game, as build_ipa.sh writes them (dm/games/settings.py): the ObjC launcher (overlay DmLauncher.m) reads dm/launcher.json
    nacp = a.nacp or (a.romfs.parent / 'control.nacp')
    launcher = dm / 'launcher.json'
    launcher.unlink(missing_ok=True)
    if nacp.is_file():
        env = dict(os.environ, GFXAPI='nvn', DM_GAMES_DIR=str(a.profile.resolve().parent))
        if a.language: env['DM_LANG'] = a.language
        else: env.pop('DM_LANG', None)
        subprocess.run([sys.executable, str(repo / 'dm/games/settings.py'), g.id, str(a.patched), str(nacp), str(launcher)], check=True, env=env)
    else:
        print(f'no control.nacp at {nacp}: the app has no launcher settings and starts the game at once')
    for pattern in ('*.fixups.tsv', '*.gates.tsv', '*.params.tsv', '*.cuts.tsv', '*.obs.tsv'):
        for source in a.patched.glob(pattern):
            shutil.copyfile(source, dm / source.name)
    for filename in ('shader_map.tsv', 'pso_manifest.tsv', 'c1_full.tsv'):
        if a.prepare_only and not g.table(filename).exists():
            continue
        shutil.copyfile(g.table(filename), dm / filename)
    shutil.copyfile(a.font, dm / 'font/standard.ttf')
    subprocess.run([sys.executable, str(repo / 'dm/tools/make_ext_font.py'), str(dm / 'font/nintendo_ext.ttf'), str(a.letter_font)], check=True)
    plist = base_info_plist(
        game_id=g.id,
        display_name=g.get('name'),
        app_version=app_version,
        app_category=g.get('app_category'),
    )
    if a.icon:
        from PIL import Image
        image = Image.open(a.icon).convert('RGB')
        for size in (120, 152, 167, 180):
            image.resize((size, size), Image.Resampling.LANCZOS).save(stage / f'AppIcon{size}.png')
        plist['CFBundleIcons'] = dict(CFBundlePrimaryIcon=dict(CFBundleIconFiles=['AppIcon120', 'AppIcon180']))
        plist['CFBundleIcons~ipad'] = dict(CFBundlePrimaryIcon=dict(CFBundleIconFiles=['AppIcon152', 'AppIcon167']))
    (stage / 'Info.plist').write_bytes(plistlib.dumps(plist, fmt=plistlib.FMT_BINARY))
    if a.prepare_only:
        print('Prepared font, icon and plist resources:', stage)
        return
    shader_dir = a.shaders / ('b-' + chain)
    if '# chain b-' + chain not in g.table('c1_full.tsv').read_text(encoding='utf-8').splitlines()[0]:
        raise ValueError('c1_full.tsv was not regenerated for the current shader chain')
    # The build summary lives beside the Mac sources; iOS libraries carry the same reflection.
    keys = {line.split('\t')[3] for line in g.table('shader_map.tsv').read_text(encoding='utf-8').splitlines()
            if line and not line.startswith('#') and not line.startswith('package\t')}
    missing, unresolved = [], []
    slot_kinds = {'cbuf', 'samp', 'samp_tex', 'tex', 'img', 'tbuf', 'sbuf', 'ubo_ptr', 'tex_ubo', 'samp_ubo'}
    for key in sorted(keys):
        lib, reflection = shader_dir / (key + '_b.metallib'), shader_dir / (key + '_b.json')
        if not lib.is_file() or lib.read_bytes()[:4] != b'MTLB':
            missing.append(key)
            continue
        value = json.loads(reflection.read_text(encoding='utf-8'))
        if value['chain'] != chain or value['dm_ctl'] != key:
            raise ValueError('Shader chain mismatch: ' + key)
        if 'air64-apple-ios' not in value.get('chain_metal', ''):
            raise ValueError('Expected an iOS shader compile convention: ' + key)
        unknown = [b for b in value['bindings'] if b['kind'] == '?' or
                   (b['kind'] in slot_kinds and b.get('reg') is None)]
        if unknown:
            unresolved.append({'key': key, 'bindings': unknown})
    if (missing or unresolved) and not a.allow_incomplete_shaders:
        raise ValueError(f'{len(missing)} shaders missing, {len(unresolved)} unresolved bindings; experimental packaging requires --allow-incomplete-shaders')
    executable = a.host / 'DmIOS'
    executable_bytes = executable.read_bytes()
    _, _, platforms, signed = macho_layout(executable_bytes)
    if platforms != [2] or signed:
        raise ValueError('Expected an unsigned iOS executable')
    link_report = json.loads((a.host / 'link_report.json').read_text())
    if hashlib.sha256(executable_bytes).hexdigest() != link_report['sha256']:
        raise ValueError('Executable differs from its verified link report')
    if chain.encode() + b'\0' not in executable_bytes:
        raise ValueError('Executable was not rebuilt with the current shader chain')
    if not (a.romfs / g.get('romfs_marker')).is_file():
        raise ValueError('Missing game RomFS marker')
    files = [(executable, 'DmIOS')]
    for root, prefix in ((stage, ''), (None if a.omit_romfs else a.romfs, 'romfs'), (shader_dir, 'msl/b-' + chain), (a.aoc, 'aoc')):
        if root:
            files += [(p, '/'.join(x for x in (prefix, p.relative_to(root).as_posix()) if x))
                      for p in sorted(root.rglob('*')) if p.is_file() and
                      (root != shader_dir or re.fullmatch(r'[0-9a-f]{16}_bf?\.(metallib|json)', p.name))]
    names = [n for _, n in files]
    if len(set(names)) != len(names):
        raise ValueError('Duplicate bundle path')
    a.out.parent.mkdir(parents=True, exist_ok=True)
    temporary = a.out.with_suffix('.ipa.partial')
    hashes = {}
    stored_extensions = set(g.get('zip_store', '.metallib').split(':'))
    with zipfile.ZipFile(temporary, 'w', allowZip64=True) as archive:
        for i, (source, name) in enumerate(files, 1):
            info = zipfile.ZipInfo.from_file(source, 'Payload/DmIOS.app/' + name)
            info.create_system = 3
            info.external_attr = (0o100755 if name == 'DmIOS' else 0o100644) << 16
            info.compress_type = zipfile.ZIP_STORED if source.suffix.lower() in stored_extensions else zipfile.ZIP_DEFLATED
            digest = hashlib.sha256()
            with source.open('rb') as src, archive.open(info, 'w', force_zip64=True) as dst:
                while block := src.read(4 * 1024 * 1024):
                    digest.update(block)
                    dst.write(block)
            hashes[info.filename] = digest.hexdigest()
            if i % 1000 == 0:
                print(f'Packed {i}/{len(files)} files', flush=True)
    print('Verifying every archived file against its source SHA-256', flush=True)
    with zipfile.ZipFile(temporary) as archive:
        for info in archive.infolist():
            digest = hashlib.sha256()
            with archive.open(info) as src:
                while block := src.read(4 * 1024 * 1024):
                    digest.update(block)
            if digest.hexdigest() != hashes[info.filename]:
                raise ValueError('IPA content verification failed: ' + info.filename)
    temporary.replace(a.out)
    report = dict(ipa=str(a.out.resolve()), bytes=a.out.stat().st_size, files=len(files),
                  shader_keys=len(keys), chain=chain, signed=False, minimum_ios='26.0',
                  missing_shader_keys=missing, unresolved_binding_shaders=unresolved,
                  experimental=bool(a.experimental or missing or unresolved),
                  romfs_bundled=not a.omit_romfs, romfs_marker=g.get('romfs_marker'),
                  archive_source_hashes_verified=True, runtime_tested=False, file_sha256=hashes)
    a.out.with_suffix('.verification.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'file_sha256'}, indent=2))


if __name__ == '__main__':
    main()
