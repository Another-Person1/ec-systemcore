#!/usr/bin/env python3
"""Package a real staged ARM64 build; no host tools or root privileges required."""
# SPDX-License-Identifier: GPL-2.0-only
import argparse
import gzip
import io
from pathlib import Path
import re
import shutil
import struct
import tarfile
import tempfile

HERE = Path(__file__).resolve().parent
NAME = 'ethercat-systemcore'


def archive(root):
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode='wb', mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w', format=tarfile.GNU_FORMAT) as tar:
            for path in sorted(root.rglob('*')):
                info = tar.gettarinfo(str(path), './' + path.relative_to(root).as_posix())
                info.uid = info.gid = info.mtime = 0
                info.uname = info.gname = 'root'
                if info.isfile():
                    with path.open('rb') as source:
                        tar.addfile(info, source)
                else:
                    tar.addfile(info)
    return buffer.getvalue()


def write_ar(path, members):
    with path.open('wb') as output:
        output.write(b'!<arch>\n')
        for name, data in members:
            output.write(f'{name + "/":<16}{0:<12}{0:<6}{0:<6}{"100644":<8}{len(data):<10}`\n'.encode('ascii'))
            output.write(data)
            if len(data) % 2:
                output.write(b'\n')


def validate_elf(path, kernel=None):
    data = path.read_bytes()
    if len(data) < 64 or data[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<H', data, 18)[0] != 183:
        raise ValueError(f'{path}: expected little-endian AArch64 ELF')
    if kernel and b'vermagic=' + kernel.encode() + b' ' not in data:
        raise ValueError(f'{path}: module vermagic does not match {kernel}')


def build(stage, kernel, version, output):
    for value in (kernel, version):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.+_~-]*', value):
            raise ValueError('Invalid kernel release or package version')
    validate_elf(stage / 'usr/bin/ethercat')
    libraries = list((stage / 'usr/lib').glob('libethercat.so.*'))
    if not libraries:
        raise ValueError('Missing shared libethercat')
    for library in libraries:
        validate_elf(library)
    for module in ('ec_master', 'ec_generic'):
        validate_elf(stage / f'lib/modules/{kernel}/ethercat/{module}.ko', kernel)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        data, control = root / 'data', root / 'control'
        shutil.copytree(stage, data, symlinks=True)
        control.mkdir()
        def put(relative, content, mode=0o644, base=data):
            path = base / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            path.chmod(mode)
        for file, destination, mode in (
            ('ethercat-systemcore', 'usr/sbin/ethercat-systemcore', 0o755),
            ('ethercat-systemcore.conf', 'etc/ethercat-systemcore.conf', 0o644),
            ('ethercat-systemcore.service', 'etc/systemd/system/ethercat-systemcore.service', 0o644),
        ):
            put(destination, (HERE / file).read_text(), mode)
        put('etc/udev/rules.d/99-ethercat-systemcore.rules',
            'KERNEL=="EtherCAT[0-9]*", GROUP="systemcore", MODE="0660"\n')
        put(f'usr/share/{NAME}/kernel-release', kernel + '\n')
        for license_file in ('COPYING', 'COPYING.LESSER'):
            put(f'usr/share/licenses/{NAME}/{license_file}', (HERE.parent.parent / license_file).read_text())
        put(f'usr/share/doc/{NAME}/README.md', (HERE / 'README.md').read_text())
        # Libtool .la files embed build-host paths and are not needed on target.
        for path in (data / 'usr/lib').glob('*.la'):
            path.unlink()
        put('control', f'''Package: {NAME}
Version: {version}
Architecture: aarch64
Section: development
Priority: optional
Maintainer: ec-systemcore contributors
Description: IgH EtherCAT MainDevice for SystemCore; kernel {kernel}
Source: local
X-Has-UI: false
X-Auto-Start: false
X-Services: ethercat-systemcore.service
''', base=control)
        put('conffiles', '/etc/ethercat-systemcore.conf\n', base=control)
        guard = '[ -z "${IPKG_INSTROOT:-}${OPKG_OFFLINE_ROOT:-}" ] || exit 0\n'
        put('preinst', '#!/bin/sh\nset -eu\n' + guard + f'''
[ "$(uname -m)" = aarch64 ] && [ "$(uname -r)" = '{kernel}' ] || {{
    echo 'This IPK requires AArch64 kernel {kernel}.' >&2; exit 1;
}}
for tool in modprobe ip systemctl depmod udevadm; do
    command -v "$tool" >/dev/null || {{ echo "Missing runtime tool: $tool" >&2; exit 1; }}
done
# Never replace modules underneath an active MainDevice during upgrade.
[ ! -d /sys/module/ec_master ] || {{ echo 'Stop EtherCAT and its clients before installing.' >&2; exit 1; }}
''', 0o755, control)
        put('postinst', '#!/bin/sh\nset -eu\n' + guard + f'''
depmod -a '{kernel}'
command -v ldconfig >/dev/null 2>&1 && ldconfig
udevadm control --reload-rules
systemctl daemon-reload
echo 'Set INTERFACE in /etc/ethercat-systemcore.conf, then start ethercat-systemcore.service.'
''', 0o755, control)
        put('prerm', '#!/bin/sh\nset -eu\n' + guard + '''
systemctl stop ethercat-systemcore.service
# A busy module must abort removal, rather than leave an untracked running MainDevice.
[ ! -d /sys/module/ec_master ] || { echo 'EtherCAT modules are still loaded.' >&2; exit 1; }
if [ "${1:-}" != upgrade ]; then
    systemctl disable ethercat-systemcore.service
fi
''', 0o755, control)
        put('postrm', '#!/bin/sh\nset -eu\n' + guard + f'''
depmod -a '{kernel}'
command -v ldconfig >/dev/null 2>&1 && ldconfig
udevadm control --reload-rules
systemctl daemon-reload
''', 0o755, control)
        output.mkdir(parents=True, exist_ok=True)
        package = output / f'{NAME}_{version}_{kernel}_aarch64.ipk'
        # Limelight's official examples use an ar containing these two members.
        write_ar(package, [('control.tar.gz', archive(control)), ('data.tar.gz', archive(data))])
        return package


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', type=Path, required=True)
    parser.add_argument('--kernel-release', required=True)
    parser.add_argument('--version', default='1.6.12-1')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(build(args.stage, args.kernel_release, args.version, args.output))
    except (ValueError, OSError) as error:
        parser.exit(1, f'Packaging failed: {error}\n')
