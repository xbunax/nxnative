"""Keep the Windows source list complete as upstream adds host libraries."""
from pathlib import Path
import tempfile
import unittest

from webui.build.windows.ios_cross_compile import host_shader_header, source_list

REPO = Path(__file__).resolve().parents[2]


class CrossSources(unittest.TestCase):
    def test_sources_include_decoder_wrappers_and_apple_runtime(self):
        sources = source_list(REPO)
        names = {p.relative_to(REPO).as_posix() for p in sources}
        self.assertIn('dm/third_party/dav1d/src/lib.c', names)
        self.assertIn('dm/third_party/dav1d/config/tmpl/filmgrain_8bpc.c', names)
        self.assertIn('dm/third_party/dav1d/src/arm/64/mc.S', names)
        self.assertIn('webui/build/windows/availability.m', names)
        self.assertFalse(any(n.endswith(('_tmpl.c', '_tmpl.S', '/util.S')) for n in names))
        # hle_movie.c includes this implementation itself.
        self.assertNotIn('dm/third_party/stb_vorbis/stb_vorbis.c', names)
        self.assertEqual(len(names), len(sources))

    def test_host_shader_fallback_embeds_every_upstream_source(self):
        with tempfile.TemporaryDirectory() as directory:
            header = host_shader_header(REPO, Path(directory)).read_text()
            sources = list((REPO / 'dm/gfx/msl').glob('*.metal'))
            self.assertTrue(sources)
            for source in sources:
                self.assertIn('k_host_msl_src_' + source.stem, header)
                self.assertIn('k_host_msl_lib_' + source.stem, header)
            self.assertIn('#define HOST_MSL_SDK "iphoneos"', header)
            self.assertIn('#define HOST_MSL_COMPILER "none"', header)
