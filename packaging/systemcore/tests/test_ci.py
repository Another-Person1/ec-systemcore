"""Checks for image parsing and the boot archive consumed by real QEMU."""
import gzip
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('image_smoke', HERE / 'ci/image-smoke.py')
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class ImageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_extended_partition_and_root_extraction(self):
        disk = bytearray(32 * 512)
        def table(lba, entries):
            offset = lba * 512
            disk[offset+510:offset+512] = b'\x55\xaa'
            for i, (kind, start, count) in enumerate(entries):
                disk[offset+446+i*16+4] = kind
                struct.pack_into('<II', disk, offset+446+i*16+8, start, count)
        table(0, [(0xc, 1, 2), (0xf, 4, 28)])
        table(4, [(0x83, 1, 12), (0xf, 16, 12)])
        table(20, [(0x83, 1, 10)])
        disk[5*512+1080:5*512+1082] = b'\x53\xef'
        image = self.root / 'disk.img'
        image.write_bytes(disk)
        self.assertEqual(list(smoke.partitions(image)), [(512, 1024), (2560, 6144), (10752, 5120)])
        target = self.root / 'rootfs'
        smoke.extract_root(image, target)
        self.assertEqual(target.read_bytes(), disk[2560:8704])
        # A corrupt extent cannot silently copy bytes outside the disk.
        struct.pack_into('<I', disk, 446+12, 999)
        image.write_bytes(disk)
        with self.assertRaisesRegex(ValueError, 'outside image'):
            list(smoke.partitions(image))

    def test_elf_dynamic_dependencies(self):
        binary = bytearray(512)
        binary[:6] = b'\x7fELF\x02\x01'
        struct.pack_into('<Q', binary, 32, 64)
        struct.pack_into('<HH', binary, 54, 56, 3)
        struct.pack_into('<IIQQQQQQ', binary, 64, 1, 0, 0, 0x1000, 0, 512, 512, 0)
        struct.pack_into('<IIQQQQQQ', binary, 120, 2, 0, 256, 0, 0, 48, 48, 0)
        interpreter = b'/lib/ld-linux-aarch64.so.1\0'
        struct.pack_into('<IIQQQQQQ', binary, 176, 3, 0, 400, 0, 0, len(interpreter), len(interpreter), 0)
        struct.pack_into('<QQQQQQ', binary, 256, 5, 0x1000+320, 1, 1, 0, 0)
        binary[320:331] = b'\0libc.so.6\0'
        binary[400:400+len(interpreter)] = interpreter
        path = self.root / 'elf'
        path.write_bytes(binary)
        self.assertEqual(smoke.elf_dependencies(path), ('/lib/ld-linux-aarch64.so.1', ['libc.so.6']))

    @unittest.skipUnless(shutil.which('cpio'), 'Host cpio required for independent archive verification')
    def test_initramfs_with_host_cpio(self):
        source = self.root / 'root'
        (source / 'bin').mkdir(parents=True)
        (source / 'bin/test').write_text('hello')
        (source / 'bin/sh').symlink_to('test')
        archive = self.root / 'initramfs.gz'
        smoke.cpio(source, archive)
        target = self.root / 'unpacked'
        target.mkdir()
        subprocess.run(['cpio', '-id'], input=gzip.decompress(archive.read_bytes()), cwd=target,
                       capture_output=True, check=True)
        self.assertEqual((target / 'bin/test').read_text(), 'hello')
        self.assertTrue((target / 'bin/sh').is_symlink())

    def test_release_lock(self):
        releases = json.loads((HERE / 'ci/releases.json').read_text())
        self.assertEqual(set(releases), {'alpha', 'beta'})
        for release in releases.values():
            self.assertEqual(set(release['assets']), {'image', 'kernel', 'toolchain'})
            for asset in release['assets'].values():
                self.assertRegex(asset['sha256'], r'^[0-9a-f]{64}$')
                self.assertNotIn('/', asset['name'])
