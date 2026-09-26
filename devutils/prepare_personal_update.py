#!/usr/bin/env python3
"""Validate the built app and create a signed, full-update Sparkle feed."""

import argparse
import base64
from datetime import datetime, timezone
from email.utils import format_datetime
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import xml.etree.ElementTree as ET

SPARKLE = 'http://www.andymatuschak.org/xml-namespaces/sparkle'
ET.register_namespace('sparkle', SPARKLE)


def identity(env):
    revision = env['GITHUB_SHA']
    # The source checkout can be newer than the workflow's initial SHA after sync.
    revision = env.get('PERSONAL_SOURCE_REVISION', revision)
    run, attempt = env['GITHUB_RUN_ID'], env['GITHUB_RUN_ATTEMPT']
    if not re.fullmatch(r'[0-9a-f]{40}', revision) or not run.isdecimal() or not attempt.isdecimal():
        raise ValueError('Invalid release identity')
    return f'personal-{revision[:12]}-{run}-{attempt}', f'{run}.{attempt}'


def validate_app(app, public, build_number):
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    if info.get('SUPublicEDKey') != public:
        raise ValueError('Built app is missing the personal Sparkle public key')
    if not (app / 'Contents/Frameworks/Helium Framework.framework/Frameworks/Sparkle.framework').exists():
        raise ValueError('Built app is missing its Sparkle framework')
    version = info['CFBundleVersion']
    if not re.fullmatch(r'\d+(?:\.\d+)+', version) or not version.endswith('.' + build_number):
        raise ValueError('Built app has no increasing personal build number')
    return info


def make_feed(info, url, signature, length):
    if len(base64.b64decode(signature, validate=True)) != 64:
        raise ValueError('Invalid Ed25519 signature')
    rss = ET.Element('rss', version='2.0')
    channel = ET.SubElement(rss, 'channel')
    ET.SubElement(channel, 'title').text = 'RTLiang Helium arm64 updates'
    item = ET.SubElement(channel, 'item')
    ET.SubElement(item, 'title').text = 'Personal Helium ' + info['CFBundleShortVersionString']
    ET.SubElement(item, 'pubDate').text = format_datetime(datetime.now(timezone.utc))
    ET.SubElement(item, f'{{{SPARKLE}}}version').text = info['CFBundleVersion']
    ET.SubElement(item, f'{{{SPARKLE}}}shortVersionString').text = info['CFBundleShortVersionString']
    ET.SubElement(item, f'{{{SPARKLE}}}minimumSystemVersion').text = info['LSMinimumSystemVersion']
    ET.SubElement(item, 'enclosure', {
        'url': url, 'length': str(length), 'type': 'application/octet-stream',
        f'{{{SPARKLE}}}edSignature': signature,
        f'{{{SPARKLE}}}os': 'macos',
    })
    ET.indent(rss)
    return ET.tostring(rss, encoding='utf-8', xml_declaration=True)


def prepare(root, app, dmg, sign_tool, env):
    config = json.loads((root / 'resources/personal_updates.json').read_text())
    if env['GITHUB_REPOSITORY'] != config['repository']:
        raise ValueError('Refusing to publish updates for a different repository')
    release_env = dict(env)
    release_env['PERSONAL_SOURCE_REVISION'] = subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    tag, number = identity(release_env)
    info = validate_app(app, config['public_key'], number)
    secret = env.get('PERSONAL_SPARKLE_PRIVATE_KEY', '').strip()
    if not secret:
        raise ValueError('PERSONAL_SPARKLE_PRIVATE_KEY is not configured')
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    seed = base64.b64decode(secret, validate=True)
    key = Ed25519PrivateKey.from_private_bytes(seed)
    public = key.public_key()
    if public.public_bytes(Encoding.Raw, PublicFormat.Raw) != base64.b64decode(config['public_key']):
        raise ValueError('Private signing key does not match the public key in the app')
    signature = subprocess.check_output(
        [str(sign_tool), '--ed-key-file', '-', '-p', str(dmg)],
        input=(secret + '\n').encode()).decode().strip()
    # Verify with both Sparkle's tool and the public key embedded in the app.
    subprocess.run([str(sign_tool), '--ed-key-file', '-', '--verify', str(dmg), signature],
                   input=(secret + '\n').encode(), check=True)
    public.verify(base64.b64decode(signature, validate=True), dmg.read_bytes())
    url = f"https://github.com/{config['repository']}/releases/download/{tag}/{dmg.name}"
    (dmg.parent / config['feed_name']).write_bytes(make_feed(info, url, signature, dmg.stat().st_size))
    with dmg.open('rb') as stream:
        sha256 = hashlib.file_digest(stream, 'sha256').hexdigest()
    manifest = {'tag': tag, 'version': info['CFBundleVersion'], 'file': dmg.name,
                'url': url, 'public_key': config['public_key'],
                'sha256': sha256}
    (dmg.parent / 'personal-update.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f"Signed personal update {manifest['version']}; prepared {config['feed_name']}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for option in ('root', 'app', 'dmg', 'sign-tool'):
        parser.add_argument('--' + option, type=Path, required=True)
    args = parser.parse_args()
    prepare(args.root, args.app, args.dmg, args.sign_tool, os.environ)
