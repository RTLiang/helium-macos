#!/usr/bin/env python3
"""Publish the signed DMG first, then move the stable personal feed forward."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

SPARKLE = 'http://www.andymatuschak.org/xml-namespaces/sparkle'


def gh(*args, check=True):
    return subprocess.run(['gh', *args], text=True, capture_output=True, check=check)


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read_feed(path):
    item = ET.parse(path).find('./channel/item')
    if item is None:
        raise ValueError('Appcast has no update item')
    version = item.findtext(f'{{{SPARKLE}}}version')
    if not version or not re.fullmatch(r'\d+(?:\.\d+)+', version):
        raise ValueError('Appcast has no numeric version')
    enclosure = item.find('enclosure')
    if enclosure is None or not enclosure.get(f'{{{SPARKLE}}}edSignature'):
        raise ValueError('Appcast is missing an update signature')
    return version, enclosure


def publish(directory, config, env):
    if env['GH_REPO'] != config['repository']:
        raise ValueError('Unexpected publishing repository')
    manifest = json.loads((directory / 'personal-update.json').read_text())
    expected_tag = f"personal-{env['REVISION'][:12]}-{env['GITHUB_RUN_ID']}-{env['GITHUB_RUN_ATTEMPT']}"
    if manifest['tag'] != expected_tag or manifest['public_key'] != config['public_key']:
        raise ValueError('Artifact identity differs from the current build')
    filename = manifest['file']
    if Path(filename).name != filename or not filename.endswith('_arm64-macos.dmg'):
        raise ValueError('Invalid update filename')
    dmg = directory / filename
    if sha256(dmg) != manifest['sha256']:
        raise ValueError('Update DMG checksum differs from its manifest')
    expected_url = f"https://github.com/{config['repository']}/releases/download/{expected_tag}/{filename}"
    feed = directory / config['feed_name']
    version, enclosure = read_feed(feed)
    if (version != manifest['version'] or enclosure.get('url') != expected_url
            or enclosure.get('length') != str(dmg.stat().st_size)):
        raise ValueError('Appcast does not describe the update DMG')
    feed_tag = config['feed_tag']
    if gh('release', 'view', feed_tag, check=False).returncode == 0:
        with tempfile.TemporaryDirectory() as temporary:
            result = gh('release', 'download', feed_tag, '--pattern', config['feed_name'],
                        '--dir', temporary, check=False)
            previous = Path(temporary) / config['feed_name']
            if result.returncode != 0:
                raise ValueError('Cannot read existing feed; refusing to overwrite it')
            old, _ = read_feed(previous)
            if tuple(map(int, version.split('.'))) <= tuple(map(int, old.split('.'))):
                raise ValueError(f'Update {version} must be newer than published {old}')
    if gh('release', 'view', expected_tag, check=False).returncode != 0:
        gh('release', 'create', expected_tag, '--target', env['REVISION'],
           '--title', f'Personal Helium arm64 {version}', '--prerelease', '--latest=false',
           '--notes', 'Personal patched arm64 build. Ad hoc signed; not notarized.')
    gh('release', 'upload', expected_tag, str(dmg), str(directory / 'personal-update.json'),
       '--clobber')
    # Check the uploaded bytes before exposing the feed to installed browsers.
    with tempfile.TemporaryDirectory() as temporary:
        gh('release', 'download', expected_tag, '--pattern', filename, '--dir', temporary)
        uploaded = Path(temporary) / filename
        if sha256(uploaded) != manifest['sha256']:
            raise ValueError('Uploaded DMG checksum differs; feed was not changed')
    if gh('release', 'view', feed_tag, check=False).returncode != 0:
        gh('release', 'create', feed_tag, '--target', env['REVISION'],
           '--title', 'Personal Helium update feed', '--prerelease', '--latest=false',
           '--notes', 'Stable Sparkle feed endpoint for RTLiang personal arm64 builds.',
           str(feed))
    else:
        gh('release', 'upload', feed_tag, str(feed), '--clobber')
    print(f'Published personal update {version} and {config["feed_name"]}')


if __name__ == '__main__':
    root = Path(__file__).resolve().parent.parent
    config = json.loads((root / 'resources/personal_updates.json').read_text())
    publish(Path(sys.argv[1]), config, os.environ)
