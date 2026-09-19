"""Synthetic ELF fixtures test packaging only, never compilation or hardware."""
import importlib.util
import io
from pathlib import Path
import struct
import subprocess
import tarfile
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('package', HERE / 'package.py')
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


def elf(kernel=None, machine=183):
    data = bytearray(64)
    data[:6] = b'\x7fELF\x02\x01'
    struct.pack_into('<H', data, 18, machine)
    return data + (b'\0vermagic=' + kernel.encode() + b' SMP\0' if kernel else b'')


def members(path):
    data = path.read_bytes()
    assert data[:8] == b'!<arch>\n'
    position, result = 8, {}
    while position < len(data):
        header = data[position:position + 60]
        size = int(header[48:58])
        name = header[:16].decode().strip().rstrip('/')
        position += 60
        with tarfile.open(fileobj=io.BytesIO(data[position:position + size]), mode='r:gz') as tar:
            result[name] = {entry.name: (entry, tar.extractfile(entry).read() if entry.isfile() else None) for entry in tar}
        position += size + size % 2
    return result


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.stage = self.root / 'stage'
        self.kernel = '6.12.77-test'
        for name in ('usr/bin/ethercat', 'usr/lib/libethercat.so.1.0.0',
                     f'lib/modules/{self.kernel}/ethercat/ec_master.ko',
                     f'lib/modules/{self.kernel}/ethercat/ec_generic.ko'):
            path = self.stage / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(elf(self.kernel if name.endswith('.ko') else None))
            path.chmod(0o755 if '/bin/' in name else 0o644)
        (self.stage / 'usr/lib/libethercat.so.1').symlink_to('libethercat.so.1.0.0')

    def build(self):
        return package.build(self.stage, self.kernel, '1.6.12-1', self.root / 'out')

    def test_layout_permissions_and_reproducibility(self):
        path = self.build()
        original = path.read_bytes()
        self.assertEqual(original, self.build().read_bytes())
        contents = members(path)
        self.assertEqual(set(contents), {'control.tar.gz', 'data.tar.gz'})
        control, data = contents['control.tar.gz'], contents['data.tar.gz']
        self.assertIn(b'Architecture: aarch64', control['./control'][1])
        self.assertEqual(control['./conffiles'][1], b'/etc/ethercat-systemcore.conf\n')
        self.assertEqual(data['./usr/sbin/ethercat-systemcore'][0].mode, 0o755)
        self.assertTrue(data['./usr/lib/libethercat.so.1'][0].issym())
        self.assertEqual(data['./usr/share/ethercat-systemcore/kernel-release'][1], (self.kernel + '\n').encode())
        for entry, _ in data.values():
            self.assertEqual((entry.uid, entry.gid), (0, 0))
        for hook in ('preinst', 'postinst', 'prerm', 'postrm'):
            entry, body = control['./' + hook]
            self.assertEqual(entry.mode, 0o755)
            subprocess.run(['sh', '-n'], input=body, check=True)
            # Offline installs must not run host systemctl/modprobe/depmod.
            subprocess.run(['/bin/sh'], input=body, env={'IPKG_INSTROOT': '/offline', 'PATH': '/nonexistent'}, check=True)

    def test_wrong_architecture_rejected(self):
        (self.stage / 'usr/bin/ethercat').write_bytes(elf(machine=62))
        with self.assertRaisesRegex(ValueError, 'AArch64'):
            self.build()

    def test_wrong_kernel_rejected(self):
        (self.stage / f'lib/modules/{self.kernel}/ethercat/ec_generic.ko').write_bytes(elf('6.6.45'))
        with self.assertRaisesRegex(ValueError, 'vermagic'):
            self.build()

    def test_missing_library_rejected(self):
        for path in (self.stage / 'usr/lib').iterdir():
            path.unlink()
        with self.assertRaisesRegex(ValueError, 'Missing shared'):
            self.build()

    def test_metadata_injection_rejected(self):
        with self.assertRaises(ValueError):
            package.build(self.stage, self.kernel, '1\nOther: field', self.root / 'out')


if __name__ == '__main__':
    unittest.main()
