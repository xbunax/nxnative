import os
from pathlib import Path
import tempfile
import types
import sys
import unittest
from unittest.mock import Mock

from webui.build.windows.windows_shader_build import cache_directory
from webui.file_tools import remove_stage


class WindowsShaderCachePaths(unittest.TestCase):
    def test_publish_and_reuse_library_beyond_max_path(self):
        # Exercise the real pinned cache implementation with its Windows adapter.
        source_path = Path(__file__).resolve().parents[2] / 'dm/gfx/tools/dmsh_mtlcache.py'
        source = source_path.read_text(encoding='utf-8')
        line = next(row for row in source.splitlines() if row.startswith('_clonefile ='))
        module = types.ModuleType('regression_shader_cache')
        module.__file__ = str(source_path)
        exec(compile(source.replace(line, '_clonefile = None'), '<shader-cache>', 'exec'), module.__dict__)
        module.compiler_id = lambda sdk: 'fixture compiler identity'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / ('repository-' + 'x' * 120) / '.webui-data/tasks' / ('a' * 32) / 'inputs/0100A00019DE0000_build/windows_shaders'
            cache_root = cache_directory(nested)
            msl = root / 'source.metal'; msl.write_bytes(b'fixture MSL')
            library = root / 'result.metallib'
            def compile_library(msl, air, output):
                Path(output).write_bytes(b'fixture compiled library')
            compiler = Mock(side_effect=compile_library)
            sys.path.insert(0, str(source_path.parents[2] / 'tools'))
            from shader_cache import Store
            store = Store(cache_root)
            cache = module.Cache(store, {'mac': ('macosx', 'fixture flags', compiler)}, str(root))
            cached = cache.path('mac', msl.read_bytes())
            try:
                self.assertGreater(len(cache_root), 260)
                cache.compile('mac', str(msl), str(library))
                self.assertEqual(store.get(cached), b'fixture compiled library')
                library.unlink()
                cache.compile('mac', str(msl), str(library))
                self.assertEqual(library.read_bytes(), b'fixture compiled library')
                compiler.assert_called_once()
                self.assertEqual(cache.stats['mac', 'reused'], 1)
                self.assertFalse(list(root.glob('result.metallib.tmp-*')))
            finally:
                store.close()
                remove_stage(root / ('repository-' + 'x' * 120), root)

    def test_explicit_shared_cache_is_used_instead_of_task_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shared = cache_directory(root / 'tasks/task/inputs/build/windows_shaders', root / 'tools/shader-cache')
            self.assertEqual(Path(shared).resolve(), Path(cache_directory(root, root / 'tools/shader-cache')).resolve())
            self.assertNotIn('tasks', shared)
            if os.name == 'nt':
                self.assertEqual([ord(char) for char in shared[:4]], [92, 92, 63, 92])


if __name__ == '__main__':
    unittest.main()
