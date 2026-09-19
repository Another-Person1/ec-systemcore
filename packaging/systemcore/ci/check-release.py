#!/usr/bin/env python3
"""Select official release assets; scheduled runs build only changed images."""
import argparse
import json
import os
from pathlib import Path
import re
import urllib.request

API = 'https://api.github.com/repos/LimelightVision/systemcore-os-public/releases?per_page=100'


def select_release(releases, variant):
    prefix = 'limelightsystemcorebetacm5-' if variant == 'beta' else 'limelightsystemcorecm5-'
    candidates = []
    for release in releases:
        if release.get('draft'):
            continue
        images = [a for a in release['assets'] if a['name'].startswith(prefix) and a['name'].endswith('.zip')]
        if images:
            candidates.append((release, images))
    if not candidates:
        raise ValueError(f'No published {variant} CM5 image found in official releases')
    release, images = max(candidates, key=lambda item: item[0]['published_at'])
    if len(images) != 1:
        raise ValueError('Ambiguous image assets in latest release')
    names = {'toolchain': f'systemcore{"beta" if variant == "beta" else ""}-aarch64-toolchain.tar.gz',
             'kernel': f'systemcore{"beta" if variant == "beta" else ""}linux.tar.xz'}
    assets = {'image': images[0]}
    for role, name in names.items():
        matches = [a for a in release['assets'] if a['name'] == name]
        if len(matches) != 1:
            raise ValueError(f'Latest image release lacks a unique matching {role}; retry after publication completes')
        assets[role] = matches[0]
    result = {'tag': release['tag_name'], 'kernel_release': None, 'assets': {}}
    for role, asset in assets.items():
        digest = asset.get('digest') or ''
        if not re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
            raise ValueError(f'Missing official SHA256 digest for {role}')
        result['assets'][role] = {'name': asset['name'], 'sha256': digest[7:]}
    return result


def selection(baseline, releases, variant, scheduled):
    manifest = select_release(releases, variant) if scheduled else baseline
    changed = not scheduled or manifest['assets']['image']['sha256'] != baseline['assets']['image']['sha256']
    return manifest, changed


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--variant', choices=['alpha', 'beta'], default='beta')
    parser.add_argument('--scheduled', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    baseline = json.loads(Path(__file__).with_name('releases.json').read_text())[args.variant]
    releases = []
    if args.scheduled:
        headers = {'User-Agent': 'ec-systemcore-ci', 'Accept': 'application/vnd.github+json'}
        if os.environ.get('GH_TOKEN'):
            headers['Authorization'] = 'Bearer ' + os.environ['GH_TOKEN']
        with urllib.request.urlopen(urllib.request.Request(API, headers=headers), timeout=60) as response:
            releases = json.load(response)
    manifest, changed = selection(baseline, releases, args.variant, args.scheduled)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2) + '\n')
    digest = manifest['assets']['image']['sha256']
    outputs = f'changed={str(changed).lower()}\ncache_key=systemcore-image-success-v1-{args.variant}-{digest}\n'
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
            stream.write(outputs)
    print(f'Selected {manifest["tag"]}: image {digest}; changed={changed}')
