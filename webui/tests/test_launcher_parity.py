"""The ObjC launcher must stay the same launcher as upstream's Swift one, in another language.

webui/overlays/dm/ios/Sources/DmLauncher.m is a port of dm/ios/Sources/Launcher.swift, LauncherRow.swift and
LauncherSettings.swift. These tests compare the two sources, so when an upstream sync changes the Swift
launcher (a new setting field, another label, another environment variable, a new file) they fail until the
ObjC port is changed with it. They cannot run the ObjC; that needs a Mac or the Windows cross-build.
"""
import json
import re
import unittest
from pathlib import Path

from webui import diffapply, staging

REPO = Path(__file__).resolve().parents[2]
SOURCES = REPO / 'dm/ios/Sources'
SWIFT = ('Launcher.swift', 'LauncherRow.swift', 'LauncherSettings.swift', 'GameMenu.swift', 'DmHostingController.swift')
OBJC = REPO / 'webui/overlays/dm/ios/Sources/DmLauncher.m'
SCHEMA = REPO / 'docs/launcher.schema.json'

# Swift string literals that have no counterpart in the ObjC port, with the reason. A new Swift literal that
# is not in DmLauncher.m fails the test: port it, or list it here when it is only a Swift artifact.
SWIFT_ONLY = {
    ') as? String) ?? ': 'text inside a Swift comment',
    '<VAR>=<value>': 'text inside a Swift comment',
    '))\\n': 'text inside a Swift comment',
    'basic': 'the Mac window\'s Basic/Advanced split (sections(basic:)); the iOS screen keeps one list',
}


def swift_source():
    sources = []
    for name in SWIFT:
        path = SOURCES / name
        data = path.read_bytes()
        for patch, target in staging.patch_queue():
            if target == path.relative_to(REPO).as_posix():
                data = diffapply.apply_bytes(data, patch.read_bytes(), target)
        sources.append(data.decode('utf-8'))
    return ''.join(sources)


def swift_literals():
    return list(dict.fromkeys(re.findall(r'"((?:[^"\\]|\\.)*)"', swift_source())))


class LauncherParity(unittest.TestCase):
    def setUp(self):
        self.objc = OBJC.read_text(encoding='utf-8')

    def test_every_swift_string_is_in_the_objc_port(self):
        missing = []
        for literal in swift_literals():
            key = literal.split('\\(')[0]   # a literal with an interpolation: its fixed beginning
            key = re.sub(r'\\u\{([0-9A-Fa-f]{4})\}', r'\\u\1', key)
            if len(key) >= 2 and key not in self.objc and literal not in SWIFT_ONLY:
                missing.append(literal)
        self.assertFalse(missing, 'Strings in upstream\'s Swift launcher that DmLauncher.m lacks (screen text, '
                         f'environment variables, log lines, keys): port them, or list them in SWIFT_ONLY: {missing}')

    def test_the_stale_swift_only_entries_are_gone(self):
        literals = set(swift_literals())
        stale = [item for item in SWIFT_ONLY if item not in literals]
        self.assertFalse(stale, f'SWIFT_ONLY lists strings the Swift launcher no longer has: {stale}')

    def test_the_objc_port_reads_every_field_the_swift_model_decodes(self):
        coding = re.search(r'enum CodingKeys: String, CodingKey \{ case (.*?) \}', swift_source(), re.S)
        self.assertTrue(coding, 'LauncherSettings.swift no longer has a CodingKeys enum: update this test')
        fields = []
        for item in coding.group(1).split(','):
            name = item.strip()
            literal = re.search(r'"(.*?)"', name)
            fields.append(literal.group(1) if literal else name.split('=')[0].strip())
        missing = [f for f in fields if f != 'level' and f'@"{f}"' not in self.objc]
        self.assertFalse(missing, f'Setting fields DmLauncher.m does not read: {missing}')

    def test_the_objc_port_reads_every_field_the_schema_defines(self):
        schema = json.loads(SCHEMA.read_text(encoding='utf-8'))
        fields = set(schema['$defs']['setting']['properties']) - {'level'}   # level: the Mac window only
        missing = sorted(f for f in fields if f'@"{f}"' not in self.objc)
        self.assertFalse(missing, f'docs/launcher.schema.json fields DmLauncher.m does not read: {missing}')

    def test_the_objc_stage_replaces_every_upstream_launcher_file(self):
        swift_files = {f'dm/ios/Sources/{p.name}' for p in SOURCES.glob('*.swift')}
        self.assertEqual(swift_files, set(staging.OBJC_REMOVED),
                         'The Swift files under dm/ios/Sources and staging.OBJC_REMOVED must be the same set: '
                         'an upstream Swift file left in an ObjC stage defines dm_show_launcher twice, and one removed '
                         'for nothing is a hole in the port')
        self.assertIn('dm/ios/Sources/DmLauncher.m', staging.OVERLAY_TARGETS)

    def test_both_launchers_export_the_same_entry_point(self):
        self.assertIn('@_cdecl("dm_show_launcher")', swift_source())
        self.assertRegex(self.objc, r'bool dm_show_launcher\(void \*viewController, void \(\*done\)\(void\)\)')


if __name__ == '__main__':
    unittest.main()
