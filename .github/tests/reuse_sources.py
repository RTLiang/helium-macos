#!/usr/bin/env python3
"""Verify source updates invalidate changed files without losing cached objects."""

import importlib.util
import io
import os
from pathlib import Path
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('overlay', ROOT / 'devutils/overlay_build_sources.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def archive(entries):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w') as tar:
        for name, data in entries.items():
            entry = tarfile.TarInfo('./build/src/' + name)
            entry.size = len(data)
            entry.mode = 0o644
            tar.addfile(entry, io.BytesIO(data))
    buffer.seek(0)
    return buffer


class Reuse(unittest.TestCase):
    def test_preserves_objects_and_unchanged_source_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, data in {'same.cc': b'same', 'changed.cc': b'old', 'removed.cc': b'gone', 'out/Default/obj/test.o': b'compiled', 'out/Default/.ninja_log': b'log'}.items():
                p = root / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(data)
                os.utime(p, (1000, 1000))
            result = module.overlay(archive({'chrome/VERSION': b'MAJOR=154\n', 'same.cc': b'same', 'changed.cc': b'new', 'added.cc': b'added', 'out/Default/obj/test.o': b'bad overwrite'}), root)
            self.assertEqual((root / 'same.cc').stat().st_mtime, 1000)
            self.assertGreater((root / 'changed.cc').stat().st_mtime, 1000)
            self.assertEqual((root / 'changed.cc').read_bytes(), b'new')
            self.assertEqual((root / 'out/Default/obj/test.o').read_bytes(), b'compiled')
            self.assertEqual((root / 'out/Default/.ninja_log').read_bytes(), b'log')
            self.assertFalse((root / 'removed.cc').exists())
            self.assertEqual(result, (3, 1))

    def test_restores_toolchain_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            buffer = archive({'chrome/VERSION': b'v', 'bin/compiler': b'compiler'})
            with tarfile.open(fileobj=buffer, mode='a') as tar:
                link = tarfile.TarInfo('./build/src/bin/compiler-alias')
                link.type = tarfile.LNKTYPE
                link.linkname = './build/src/bin/compiler'
                tar.addfile(link)
            buffer.seek(0)
            module.overlay(buffer, Path(tmp))
            self.assertTrue(os.path.samefile(Path(tmp)/'bin/compiler', Path(tmp)/'bin/compiler-alias'))

    def test_preserves_onboarding_generator_side_effect(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            strings = root / 'components/helium_onboarding/src/lib/strings.ts'
            strings.parent.mkdir(parents=True)
            strings.write_bytes(b'generated translations')
            os.utime(strings, (1000, 1000))
            header = root / 'out/Default/gen/components/helium_onboarding/helium_onboarding_localized_strings.h'
            header.parent.mkdir(parents=True)
            header.write_bytes(b'cached generator output')
            module.overlay(archive({'chrome/VERSION': b'v'}), root)
            self.assertEqual(strings.read_bytes(), b'generated translations')
            self.assertEqual(strings.stat().st_mtime, 1000)
            self.assertTrue(header.exists())

    def test_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                module.overlay(archive({'../escaped': b'bad'}), Path(tmp))

    def test_rejects_missing_source_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                module.overlay(archive({'out/Default/test.o': b'bad'}), Path(tmp))

    def test_replaces_symlink_without_writing_through_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'target').write_bytes(b'keep')
            (root / 'file.cc').symlink_to('target')
            module.overlay(archive({'chrome/VERSION': b'v', 'file.cc': b'new', 'target': b'keep'}), root)
            self.assertFalse((root / 'file.cc').is_symlink())
            self.assertEqual((root / 'target').read_bytes(), b'keep')


if __name__ == '__main__':
    unittest.main()
