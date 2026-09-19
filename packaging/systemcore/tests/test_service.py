"""Execute the shipped shell logic with isolated paths and fake Linux commands."""
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for directory in ('bin', 'etc', 'sys/class/net/test0', 'usr/share/ethercat-systemcore'):
            (self.root / directory).mkdir(parents=True)
        self.write('etc/ethercat-systemcore.conf', 'INTERFACE=test0\n')
        self.write('usr/share/ethercat-systemcore/kernel-release', '6.12.77\n')
        self.write('sys/class/net/test0/type', '1\n')
        self.write('sys/class/net/test0/address', '02:00:00:00:00:01\n')
        self.command('uname', 'echo 6.12.77')
        self.command('ip', 'exit 0')
        self.command('modprobe', 'echo "$*" >> "' + str(self.root / 'calls') + '"')
        # Only paths change: the production command/control flow is unchanged.
        script = (HERE / 'ethercat-systemcore').read_text()
        script = script.replace('PATH=/usr/sbin:/usr/bin:/sbin:/bin', f'PATH={self.root}/bin:/usr/bin:/bin')
        for prefix in ('/etc/', '/sys/', '/usr/share/'):
            script = script.replace(prefix, str(self.root) + prefix)
        self.write('service', script)

    def write(self, name, content):
        (self.root / name).write_text(content)

    def command(self, name, body):
        self.write('bin/' + name, '#!/bin/sh\n' + body + '\n')
        (self.root / 'bin' / name).chmod(0o755)

    def run_service(self):
        return subprocess.run(['/bin/sh', str(self.root / 'service'), 'start'], capture_output=True, text=True)

    def test_start_loads_selected_mac(self):
        result = self.run_service()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / 'calls').read_text().splitlines(),
                         ['ec_master main_devices=02:00:00:00:00:01', 'ec_generic'])

    def test_unconfigured_rejected(self):
        self.write('etc/ethercat-systemcore.conf', 'INTERFACE=""\n')
        self.assertNotEqual(self.run_service().returncode, 0)
        self.assertFalse((self.root / 'calls').exists())

    def test_kernel_update_rejected(self):
        self.command('uname', 'echo 6.12.78')
        self.assertNotEqual(self.run_service().returncode, 0)
        self.assertFalse((self.root / 'calls').exists())

    def test_addressed_interface_rejected(self):
        self.command('ip', 'echo "inet 10.0.0.2/24"')
        self.assertNotEqual(self.run_service().returncode, 0)
        self.assertFalse((self.root / 'calls').exists())

    def test_ip_failure_rejected(self):
        self.command('ip', 'exit 2')
        self.assertNotEqual(self.run_service().returncode, 0)
        self.assertFalse((self.root / 'calls').exists())

    def test_generic_failure_rolls_back_maindevice(self):
        self.command('modprobe', 'echo "$*" >> "' + str(self.root / 'calls') + '"\n[ "$*" != ec_generic ]')
        self.assertNotEqual(self.run_service().returncode, 0)
        self.assertEqual((self.root / 'calls').read_text().splitlines()[-1], '-r ec_master')
