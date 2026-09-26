#!/usr/bin/env python3
"""Configure this fork's Sparkle identity before generating the build graph."""

import base64
import json
import os
from pathlib import Path
import re
import sys


def configure(root, env):
    config = json.loads((root / 'resources/personal_updates.json').read_text())
    public = config['public_key']
    if len(base64.b64decode(public, validate=True)) != 32:
        raise ValueError('Sparkle public key must be 32 bytes')
    upstream_key = env.get('PROD_MACOS_SPARKLE_ED_PUB_KEY', '')
    if upstream_key and upstream_key != public:
        raise ValueError('Configured Sparkle secret differs from the personal public key')
    run = env.get('GITHUB_RUN_ID', '0')
    attempt = env.get('GITHUB_RUN_ATTEMPT', '0')
    if not run.isdecimal() or not attempt.isdecimal():
        raise ValueError('Personal build number must be numeric')
    version_path = root / 'build/src/chrome/VERSION'
    version = re.sub(r'^PERSONAL_BUILD_NUMBER=.*\n?', '', version_path.read_text(), flags=re.M)
    version_path.write_text(version.rstrip() + f'\nPERSONAL_BUILD_NUMBER={run}.{attempt}\n')
    args_path = root / 'build/src/out/Default/args.gn'
    args = re.sub(r'^\s*(enable_sparkle|sparkle_ed_key|sparkle_automatic_checks)\s*=.*\n?',
                  '', args_path.read_text(), flags=re.M)
    args_path.write_text(args.rstrip() + '\nenable_sparkle = true\n'
                        + f'sparkle_ed_key = "{public}"\n'
                        + 'sparkle_automatic_checks = true\n')
    print(f'Personal Sparkle enabled; build number {run}.{attempt}')


if __name__ == '__main__':
    configure(Path(sys.argv[1]), os.environ)
