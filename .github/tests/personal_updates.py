#!/usr/bin/env python3
"""Exercise update identity, signing and safe publication without GitHub writes."""

import base64
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, PublicFormat, NoEncryption

ROOT = Path(__file__).resolve().parents[2]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f'devutils/{name}.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


configure = module('configure_personal_updates')
prepare = module('prepare_personal_update')
publish = module('publish_personal_update')


class Updates(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        key = Ed25519PrivateKey.generate()
        self.public = base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
        self.secret = base64.b64encode(key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())).decode()
        self.config = {'repository': 'RTLiang/helium-macos', 'public_key': self.public,
                       'feed_tag': 'personal-updates', 'feed_name': 'appcast-arm64.xml'}
        (self.root / 'resources').mkdir()
        (self.root / 'resources/personal_updates.json').write_text(json.dumps(self.config))
        self.env = {'GITHUB_REPOSITORY': self.config['repository'], 'GITHUB_SHA': 'a' * 40,
                    'GITHUB_RUN_ID': '36223344526', 'GITHUB_RUN_ATTEMPT': '1',
                    'PERSONAL_SPARKLE_PRIVATE_KEY': self.secret}
        self.app = self.root / 'Helium.app'
        (self.app / 'Contents/Frameworks/Helium Framework.framework/Frameworks/Sparkle.framework').mkdir(parents=True)
        self.info = {'SUPublicEDKey': self.public, 'CFBundleVersion': '154.0.8037.57.36223344526.1',
                     'CFBundleShortVersionString': '0.18.1.1', 'LSMinimumSystemVersion': '13.0'}
        (self.app / 'Contents/Info.plist').write_bytes(plistlib.dumps(self.info))
        self.dmg = self.root / 'helium_0.18.1.1_arm64-macos.dmg'
        self.dmg.write_bytes(b'fixture signed update bytes')

    def test_configuration_is_idempotent_and_keeps_build_flags(self):
        version = self.root / 'build/src/chrome/VERSION'
        version.parent.mkdir(parents=True)
        version.write_text('MAJOR=154\n')
        args = self.root / 'build/src/out/Default/args.gn'
        args.parent.mkdir(parents=True)
        args.write_text('symbol_level=1\nenable_sparkle=false\n')
        configure.configure(self.root, self.env)
        first = (version.read_bytes(), args.read_bytes())
        configure.configure(self.root, self.env)
        self.assertEqual(first, (version.read_bytes(), args.read_bytes()))
        self.assertIn('symbol_level=1', args.read_text())
        self.assertIn('PERSONAL_BUILD_NUMBER=36223344526.1', version.read_text())
        with self.assertRaises(ValueError):
            configure.configure(self.root, dict(self.env, PROD_MACOS_SPARKLE_ED_PUB_KEY='wrong'))

    def test_rejects_unconfigured_old_build(self):
        self.info.pop('SUPublicEDKey')
        (self.app / 'Contents/Info.plist').write_bytes(plistlib.dumps(self.info))
        with self.assertRaisesRegex(ValueError, 'public key'):
            prepare.validate_app(self.app, self.public, '36223344526.1')

    def test_rejects_build_number_mismatch(self):
        with self.assertRaisesRegex(ValueError, 'build number'):
            prepare.validate_app(self.app, self.public, '36223344527.1')

    def signed_artifact(self):
        tool = os.environ.get('SPARKLE_SIGN_TOOL')
        if not tool:
            self.skipTest('Set SPARKLE_SIGN_TOOL to the official sign_update binary')
        original = subprocess.check_output
        def invoke(args, **kwargs):
            if args[:2] == ['git', 'rev-parse']:
                return 'a' * 40 + '\n'
            return original(args, **kwargs)
        with patch.object(prepare.subprocess, 'check_output', side_effect=invoke):
            prepare.prepare(self.root, self.app, self.dmg, Path(tool), self.env)
        return json.loads((self.root / 'personal-update.json').read_text())

    def test_official_sparkle_signature_and_appcast(self):
        manifest = self.signed_artifact()
        version, enclosure = publish.read_feed(self.root / self.config['feed_name'])
        self.assertEqual(version, self.info['CFBundleVersion'])
        self.assertEqual(enclosure.get('url'), manifest['url'])
        self.assertEqual(enclosure.get('length'), str(self.dmg.stat().st_size))

    def test_rejects_wrong_private_key_before_signing(self):
        tool = Path(os.environ.get('SPARKLE_SIGN_TOOL', '/nonexistent'))
        with patch.object(prepare.subprocess, 'check_output', return_value='a' * 40 + '\n'):
            wrong = dict(self.env, PERSONAL_SPARKLE_PRIVATE_KEY=base64.b64encode(b'x' * 32).decode())
            with self.assertRaisesRegex(ValueError, 'does not match'):
                prepare.prepare(self.root, self.app, self.dmg, tool, wrong)

    def test_publish_uploads_dmg_before_feed(self):
        manifest = self.signed_artifact()
        calls = []
        def fake(*args, **kwargs):
            calls.append(args)
            if args[:2] == ('release', 'view'):
                return subprocess.CompletedProcess(args, 1)
            if args[:2] == ('release', 'download'):
                destination = Path(args[args.index('--dir') + 1]) / self.dmg.name
                destination.write_bytes(self.dmg.read_bytes())
            return subprocess.CompletedProcess(args, 0)
        env = dict(self.env, GH_REPO=self.config['repository'], REVISION='a' * 40)
        with patch.object(publish, 'gh', side_effect=fake):
            publish.publish(self.root, self.config, env)
        uploads = [c for c in calls if c[:2] in (('release', 'upload'), ('release', 'create'))]
        self.assertEqual(uploads[-1][2], self.config['feed_tag'])
        self.assertTrue(any(c[:3] == ('release', 'download', manifest['tag']) for c in calls))

    def test_corrupted_uploaded_dmg_never_updates_feed(self):
        self.signed_artifact()
        calls = []
        def fake(*args, **kwargs):
            calls.append(args)
            if args[:2] == ('release', 'view'):
                return subprocess.CompletedProcess(args, 1)
            if args[:2] == ('release', 'download'):
                (Path(args[args.index('--dir') + 1]) / self.dmg.name).write_bytes(b'corruption')
            return subprocess.CompletedProcess(args, 0)
        with patch.object(publish, 'gh', side_effect=fake):
            with self.assertRaisesRegex(ValueError, 'Uploaded DMG checksum'):
                publish.publish(self.root, self.config, dict(self.env, GH_REPO=self.config['repository'], REVISION='a'*40))
        self.assertFalse(any(c[:3] == ('release', 'create', self.config['feed_tag']) for c in calls))

    def test_feed_cannot_move_backwards(self):
        self.signed_artifact()
        original = (self.root / self.config['feed_name']).read_bytes()
        calls = []
        def fake(*args, **kwargs):
            calls.append(args)
            if args[:2] == ('release', 'download'):
                (Path(args[args.index('--dir') + 1]) / self.config['feed_name']).write_bytes(original)
            return subprocess.CompletedProcess(args, 0)
        with patch.object(publish, 'gh', side_effect=fake):
            with self.assertRaisesRegex(ValueError, 'must be newer'):
                publish.publish(self.root, self.config, dict(self.env, GH_REPO=self.config['repository'], REVISION='a'*40))
        self.assertFalse(any(c[:2] == ('release', 'upload') for c in calls))


if __name__ == '__main__':
    unittest.main()
