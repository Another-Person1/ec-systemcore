#!/usr/bin/env python3
"""Fetch only checksum-pinned assets from Limelight's official release repository."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import urllib.request

BASE = 'https://github.com/LimelightVision/systemcore-os-public/releases/download/'


def fetch(variant, directory, selected_manifest=None):
    manifest = json.loads(selected_manifest.read_text()) if selected_manifest else json.loads(Path(__file__).with_name('releases.json').read_text())[variant]
    directory.mkdir(parents=True, exist_ok=True)
    for role, asset in manifest['assets'].items():
        for part in (manifest['tag'], asset['name']):
            if not re.fullmatch(r'[A-Za-z0-9_.-]+', part) or part in ('.', '..'):
                raise ValueError('Invalid release path component')
        destination = directory / asset['name']
        digest = hashlib.sha256()
        print(f'Downloading official {role}: {asset["name"]}', flush=True)
        request = urllib.request.Request(BASE + manifest['tag'] + '/' + asset['name'], headers={'User-Agent': 'ec-systemcore-ci'})
        with urllib.request.urlopen(request, timeout=120) as source, destination.open('wb') as output:
            while block := source.read(1024*1024):
                digest.update(block)
                output.write(block)
        if digest.hexdigest() != asset['sha256']:
            destination.unlink()
            raise ValueError(f'SHA256 mismatch: {asset["name"]}')
    (directory / 'release.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('variant', choices=['alpha', 'beta'])
    parser.add_argument('directory', type=Path)
    parser.add_argument('--manifest', type=Path)
    args = parser.parse_args()
    fetch(args.variant, args.directory, args.manifest)
