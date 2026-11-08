import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from webui import staging


REPO = Path(__file__).resolve().parents[2]
CATALOG = REPO / 'webui/localization/launcher.zh-Hans.json'


class LauncherLocalization(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.swift = staging.ensure(REPO, cls.root / 'stages', launcher='swiftui')
        cls.objc = staging.ensure(REPO, cls.root / 'stages', launcher='objc')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_translation_catalog_covers_all_settings_and_language_names(self):
        translations = json.loads(CATALOG.read_text(encoding='utf-8'))
        required = {'Play', 'Version', 'Interface language', 'Memory available',
                    'Reset to tested defaults', 'Brings back all settings this game was tested with.',
                    'Set at launch', 'Set by an env file'}
        for line in (REPO / 'dm/games/settings.tsv').read_text(encoding='utf-8').splitlines():
            if not line.strip() or line.startswith('#'):
                continue
            columns = line.split('\t')
            required.update(value for value in columns[5:8] if value)
            if columns[1] == 'choice' and columns[2] != 'languages':
                required.update(option.split('?', 1)[0].split('=', 1)[1] for option in columns[2].split(','))
        # Importing nacp only reads the repository's language names; no game data.
        spec = importlib.util.spec_from_file_location('ui_nacp', REPO / 'dm/tools/nacp.py')
        nacp = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(nacp)
        required.update(name for code, name in nacp.LANGUAGES)
        self.assertFalse(required - translations.keys(), sorted(required - translations.keys()))
        self.assertTrue(all(isinstance(v, str) and v for v in translations.values()))
        self.assertTrue(CATALOG.read_bytes().isascii())

    def test_both_packers_embed_translations_without_changing_game_settings(self):
        script = '''
import importlib.util, json, os, sys
from unittest.mock import patch
from pathlib import Path
source, patched, control = map(Path, sys.argv[1:])
spec = importlib.util.spec_from_file_location('ui_settings', source)
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
with patch.dict(os.environ, {'DM_LANG': 'en-US', 'GFXAPI': 'nvn', 'SETTINGS_PLATFORM': 'ios'}), patch.object(module.nacp, 'languages', return_value=['en-US', 'zh-Hans']):
    data = module.build('0100A00019DE0000', patched, control)
print(json.dumps(data))
'''
        patched = self.root / 'patched'
        patched.mkdir(exist_ok=True)
        results = []
        for tree in (REPO, self.swift, self.objc):
            result = subprocess.run([sys.executable, '-c', script, str(tree / 'dm/games/settings.py'),
                                     str(patched), str(self.root / 'control.nacp')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            results.append(json.loads(result.stdout))
        baseline, swift, objc = results
        self.assertEqual(swift['settings'], baseline['settings'])
        self.assertEqual(objc, swift)
        self.assertEqual(swift['uiTranslations'], json.loads(CATALOG.read_text()))
        language = next(row for row in swift['settings'] if row['env'] == 'DM_LANG')
        self.assertEqual(language['default'], 'en-US')
        self.assertEqual([item[0] for item in language['options']], ['en-US', 'zh-Hans'])

    @unittest.skipUnless(sys.platform == 'darwin' and shutil.which('xcrun'), 'needs the macOS Swift toolchain')
    def test_saved_ui_language_is_independent_of_game_language(self):
        executable = self.root / 'ui-language-check'
        fixture = Path(__file__).with_name('fixtures') / 'launcher_ui_language_check.swift'
        subprocess.run(['xcrun', '-sdk', 'macosx', 'swiftc', '-swift-version', '5', '-parse-as-library',
                        '-module-cache-path', str(self.root / 'module-cache'), '-o', str(executable),
                        str(self.swift / 'dm/ios/Sources/LauncherSettings.swift'), str(fixture)], check=True)
        result = subprocess.run([str(executable)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('UI language independence: PASS', result.stdout)


if __name__ == '__main__':
    unittest.main()
