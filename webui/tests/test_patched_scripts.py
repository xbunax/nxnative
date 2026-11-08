"""Behaviour of the upstream scripts after the hook patches, in a freshly built stage.

test_patch_queue.py only looks for markers in the patched text; these tests run or
parse the patched files, so a patch that still applies but no longer works fails here.
"""
import ast
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace

from webui import staging

REPO = Path(__file__).resolve().parents[2]
PATCHED_PYTHON = ('dm/gfx/tools/shader_split.py', 'dm/ios/tools/gen_embed.py', 'scripts/build_ipa_from_nsp.py')


class PatchedScripts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.TemporaryDirectory()
        cls.tree = staging.ensure(REPO, Path(cls.root.name))

    @classmethod
    def tearDownClass(cls):
        cls.root.cleanup()

    def python(self, code):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
        if os.name == 'nt':
            # The Mac entry point imports tree_tar. These argument/AST tests never
            # take its POSIX lock; the Windows build uses its own entry point.
            code = "import sys, types; sys.modules['fcntl'] = types.ModuleType('fcntl')\n" + code
        return subprocess.run([sys.executable, '-c', code], cwd=self.tree, capture_output=True, text=True, env=env)

    def test_patched_python_compiles(self):
        for name in PATCHED_PYTHON:
            with self.subTest(name):
                path = self.tree / name
                compile(path.read_text(encoding='utf-8'), str(path), 'exec')

    @unittest.skipUnless(shutil.which('bash'), 'bash is required')
    def test_patched_shell_parses(self):
        process = subprocess.run(['bash', '-n', str(self.tree / 'dm/ios/tools/build_ipa.sh')],
                                 capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)

    def test_separate_romfs_flag_is_parsed_and_limited_to_ios(self):
        process = self.python(
            "import sys; sys.path.insert(0, 'scripts')\n"
            "import build_ipa_from_nsp as b\n"
            "a = b.parse_args(['--separate-romfs'])\n"
            "assert a.separate_romfs is True and not hasattr(a, 'target'), a\n"
            "assert b.parse_args([]).separate_romfs is False\n"
            "try:\n"
            "    b.main(b.parse_args(['--separate-romfs', '--platform', 'mac']))\n"
            "except b.BuildError as error:\n"
            "    print('refused:', error)\n"
            "else:\n"
            "    raise SystemExit('--separate-romfs with --platform mac was accepted')\n")
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertIn('refused:', process.stdout)

    def test_separate_romfs_flag_selects_upstream_separate_mode(self):
        tree = ast.parse((self.tree / 'scripts/build_ipa_from_nsp.py').read_text(encoding='utf-8'))
        assigns = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == 'romfs_mode' for t in node.targets)]
        self.assertEqual(len(assigns), 1)
        expression = ast.Expression(assigns[0].value)
        ast.fix_missing_locations(expression)
        code = compile(expression, 'romfs_mode', 'eval')

        def mode(separate_romfs, romfs=None):
            return eval(code, {'args': Namespace(separate_romfs=separate_romfs, romfs=romfs), 'ROMFS': 'bundle'})
        self.assertEqual(mode(True), 'separate')
        self.assertEqual(mode(True, 'bundle'), 'separate')
        self.assertEqual(mode(False), 'bundle')
        self.assertEqual(mode(False, 'separate'), 'separate')


if __name__ == '__main__':
    unittest.main()
