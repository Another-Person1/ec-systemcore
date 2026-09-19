"""Run source staging/configure with fake SDK commands, not a module compiler."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('rsync'), 'rsync is required by the build script')
class BuildLayoutTests(unittest.TestCase):
    def exercise(self, nested):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            scripts = source / 'packaging/systemcore'
            scripts.mkdir(parents=True)
            shutil.copy2(HERE / 'build.sh', scripts / 'build.sh')
            for relative in ('examples/mini/mini.c', 'master/module.c', 'devices/generic.c'):
                path = source / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('/* source layout fixture */\n')
            configure = source / 'configure'
            configure.write_text('#!/bin/sh\nset -eu\ntest -f examples/mini/mini.c\npwd > configured-here\ntouch Kbuild config.h\n')
            configure.chmod(0o755)
            tools = root / 'bin'
            tools.mkdir()
            for name, body in {
                'uname': 'echo Linux',
                'sdk-gcc': 'echo fixture-compiler',
                'make': '''set -eu
for file in Kbuild config.h examples/mini/mini.c master/module.c devices/generic.c; do
    test -f "$file" || exit 91
done
test "$(cat configured-here)" = "$PWD" || exit 92
# Stop here: the test checks actual staging, not synthetic compilation.
exit 73''',
            }.items():
                path = tools / name
                path.write_text('#!/bin/sh\n' + body + '\n')
                path.chmod(0o755)
            kernel = root / 'kernel'
            (kernel / 'include/config').mkdir(parents=True)
            (kernel / 'include/config/kernel.release').write_text('6.12.77-test\n')
            (kernel / '.config').write_text('CONFIG_ARM64=y\nCONFIG_MODULES=y\n')
            (kernel / 'Module.symvers').write_text('fixture\n')
            output = source / 'custom-output' if nested else root / 'output'
            env = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ['PATH'],
                       KDIR=str(kernel), CROSS_COMPILE=str(tools / 'sdk-'),
                       SYSTEMCORE_KERNEL_RELEASE='6.12.77-test', OUTPUT_DIR=str(output))
            result = subprocess.run(['bash', str(scripts / 'build.sh')], env=env,
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 73, result.stdout + result.stderr)
            builds = list(output.glob('build.*'))
            self.assertEqual(len(builds), 1)
            build = builds[0]
            self.assertEqual(Path((build / 'configured-here').read_text().strip()).resolve(), build.resolve())
            self.assertFalse((source / 'config.h').exists())
            self.assertFalse((build / 'custom-output').exists())
            self.assertFalse((build / '.git').exists())

    def test_external_output(self):
        self.exercise(False)

    def test_nested_output_does_not_copy_itself(self):
        self.exercise(True)
