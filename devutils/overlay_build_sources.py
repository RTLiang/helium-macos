#!/usr/bin/env python3
"""Overlay fresh source files while preserving unchanged files and Ninja outputs."""

import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import tarfile
import tempfile


def overlay(stream, destination):
    destination = Path(destination).resolve()
    seen = set()
    changed = 0
    scanned = 0
    prefix = './build/src/'
    with tarfile.open(fileobj=stream, mode='r|') as archive:
        for entry in archive:
            name = entry.name
            if name.startswith('build/src/'):
                name = './' + name
            if not name.startswith(prefix):
                continue
            relative = PurePosixPath(name[len(prefix):])
            if '..' in relative.parts or relative.is_absolute():
                raise ValueError('Unsafe source archive path')
            if not relative.parts or relative.parts[0] in ('out', '.git'):
                continue
            seen.add(str(relative))
            path = destination / relative
            if not path.parent.resolve().is_relative_to(destination):
                raise ValueError(f'Source parent escapes build directory: {relative}')
            path.parent.mkdir(parents=True, exist_ok=True)
            if entry.isdir():
                if path.is_symlink() or (path.exists() and not path.is_dir()):
                    path.unlink()
                path.mkdir(exist_ok=True)
            elif entry.issym():
                if not path.is_symlink() or os.readlink(path) != entry.linkname:
                    if path.is_dir() and not path.is_symlink():
                        shutil.rmtree(path)
                    else:
                        path.unlink(missing_ok=True)
                    path.symlink_to(entry.linkname)
                    changed += 1
            elif entry.islnk():
                link = entry.linkname.removeprefix('./')
                if not link.startswith('build/src/'):
                    raise ValueError('Hard link points outside source archive')
                target_relative = PurePosixPath(link[len('build/src/'):])
                if '..' in target_relative.parts or target_relative.parts[0] in ('out', '.git'):
                    raise ValueError('Unsafe source hard link')
                target = destination / target_relative
                if not target.resolve().is_relative_to(destination) or not target.is_file():
                    raise ValueError('Missing or external source hard link')
                if not path.exists() or path.is_symlink() or not os.path.samefile(path, target):
                    if path.is_dir() and not path.is_symlink():
                        shutil.rmtree(path)
                    else:
                        path.unlink(missing_ok=True)
                    os.link(target, path)
                    changed += 1
            elif entry.isfile():
                existing = path.open('rb') if path.is_file() and not path.is_symlink() else None
                same = existing is not None and path.stat().st_size == entry.size
                incoming = archive.extractfile(entry)
                temporary = None
                try:
                    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
                        temporary = Path(output.name)
                        while chunk := incoming.read(1024 * 1024):
                            output.write(chunk)
                            if existing is not None and existing.read(len(chunk)) != chunk:
                                same = False
                    os.chmod(temporary, entry.mode)
                    if existing is not None:
                        existing.close()
                        existing = None
                    if same:
                        os.chmod(path, entry.mode)
                    else:
                        if path.is_dir() and not path.is_symlink():
                            shutil.rmtree(path)
                        os.replace(temporary, path)
                        changed += 1
                finally:
                    if existing is not None:
                        existing.close()
                    incoming.close()
                    if temporary is not None:
                        temporary.unlink(missing_ok=True)
            else:
                raise ValueError(f'Unsupported source archive entry: {relative}')
            scanned += 1
            if scanned % 5000 == 0:
                print(f'Source overlay: {scanned} entries checked, {changed} changed', flush=True)
    if 'chrome/VERSION' not in seen:
        raise ValueError('Resource archive contains no Chromium source version')
    removed = 0
    for directory, dirs, files in os.walk(destination, topdown=False, followlinks=False):
        parent = Path(directory)
        relative_parent = parent.relative_to(destination)
        if relative_parent.parts and relative_parent.parts[0] in ('out', '.git'):
            continue
        for name in files + dirs:
            path = parent / name
            relative = path.relative_to(destination)
            if relative.parts[0] in ('out', '.git') or str(relative) in seen:
                continue
            if path.is_symlink() or not path.is_dir():
                path.unlink()
                removed += 1
            elif not any(path.iterdir()):
                path.rmdir()
    print(f'Source overlay complete: {scanned} entries, {changed} changed, {removed} removed; unchanged timestamps and out/ retained', flush=True)
    return changed, removed


if __name__ == '__main__':
    overlay(sys.stdin.buffer, sys.argv[1])
