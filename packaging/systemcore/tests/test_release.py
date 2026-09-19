"""Exercise scheduled image-change detection without downloading SDKs."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('check_release', HERE / 'ci/check-release.py')
release_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_check)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.baseline = json.loads((HERE / 'ci/releases.json').read_text())['beta']
        self.release = {'tag_name': self.baseline['tag'], 'published_at': '2026-09-01T00:00:00Z',
                        'draft': False, 'assets': [
                            {'name': asset['name'], 'digest': 'sha256:' + asset['sha256']}
                            for asset in self.baseline['assets'].values()]}

    def select(self, releases):
        return release_check.selection(self.baseline, releases, 'beta', True)

    def test_unchanged_image_skips(self):
        self.assertFalse(self.select([self.release])[1])

    def test_changed_image_selects_matching_sdk(self):
        new = copy.deepcopy(self.release)
        new['tag_name'] = 'limelightosr-2027.0.0-beta15-999'
        new['published_at'] = '2026-09-20T00:00:00Z'
        new['assets'][0]['digest'] = 'sha256:' + 'a' * 64
        manifest, changed = self.select([self.release, new])
        self.assertTrue(changed)
        self.assertEqual(manifest['tag'], new['tag_name'])
        self.assertIsNone(manifest['kernel_release'])
        self.assertEqual(manifest['assets']['toolchain'], self.baseline['assets']['toolchain'])

    def test_same_image_in_new_tag_does_not_rebuild(self):
        self.release['tag_name'] = 'retagged'
        self.assertFalse(self.select([self.release])[1])

    def test_alpha_and_draft_images_are_ignored(self):
        alpha = copy.deepcopy(self.release)
        alpha['published_at'] = '2026-09-20T00:00:00Z'
        alpha['assets'][0]['name'] = 'limelightsystemcorecm5-alpha.zip'
        draft = copy.deepcopy(self.release)
        draft['draft'] = True
        draft['published_at'] = '2026-09-21T00:00:00Z'
        self.assertFalse(self.select([alpha, draft, self.release])[1])

    def test_missing_sdk_fails_without_falling_back(self):
        new = copy.deepcopy(self.release)
        new['published_at'] = '2026-09-20T00:00:00Z'
        new['assets'] = new['assets'][:1]
        with self.assertRaisesRegex(ValueError, 'toolchain'):
            self.select([new, self.release])

    def test_missing_digest_fails(self):
        self.release['assets'][0]['digest'] = None
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            self.select([self.release])

    def test_manual_build_keeps_pins(self):
        manifest, changed = release_check.selection(self.baseline, [], 'beta', False)
        self.assertTrue(changed)
        self.assertEqual(manifest, self.baseline)
