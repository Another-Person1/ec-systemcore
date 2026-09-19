#!/usr/bin/env python3
"""Boot Limelight kernel + image userspace in QEMU virt (not CM5 emulation)."""
import argparse
import gzip
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
import subprocess
import zipfile


def partitions(image):
    """Read MBR and logical partitions; bound every extent to the image."""
    size = image.stat().st_size
    with image.open('rb') as stream:
        def table(lba):
            if not 0 <= lba * 512 <= size - 512:
                raise ValueError('Partition table outside image')
            stream.seek(lba * 512)
            block = stream.read(512)
            if block[510:] != b'\x55\xaa':
                raise ValueError('Missing MBR signature')
            return [(block[446+i*16+4], *struct.unpack_from('<II', block, 446+i*16+8)) for i in range(4)]
        def extent(start, count):
            if count <= 0 or (start + count) * 512 > size:
                raise ValueError('Partition outside image')
            return start * 512, count * 512
        for kind, start, count in table(0):
            if kind in (0x05, 0x0f, 0x85):
                base, current, seen = start, start, set()
                while current not in seen:
                    seen.add(current)
                    entries = table(current)
                    yield extent(current + entries[0][1], entries[0][2])
                    if not entries[1][1]:
                        break
                    current = base + entries[1][1]
                else:
                    raise ValueError('Cyclic extended partition chain')
            elif kind:
                yield extent(start, count)


def extract_root(image, target):
    with image.open('rb') as source:
        for offset, length in partitions(image):
            source.seek(offset + 1080)
            if source.read(2) != b'\x53\xef':
                continue
            source.seek(offset)
            with target.open('wb') as output:
                remaining = length
                while remaining:
                    data = source.read(min(8*1024*1024, remaining))
                    if not data:
                        raise ValueError('Truncated image')
                    output.write(data)
                    remaining -= len(data)
            return
    raise ValueError('No ext4 root partition found')


def elf_dependencies(path):
    data = path.read_bytes()
    if data[:6] != b'\x7fELF\x02\x01':
        raise ValueError(f'Not an ELF64 little-endian binary: {path}')
    phoff = struct.unpack_from('<Q', data, 32)[0]
    size, count = struct.unpack_from('<HH', data, 54)
    headers = [struct.unpack_from('<IIQQQQQQ', data, phoff + i*size) for i in range(count)]
    needed, strings, interpreter = [], None, None
    for kind, _, offset, _, _, length, _, _ in headers:
        if kind == 3:
            interpreter = data[offset:offset+length].rstrip(b'\0').decode()
        if kind == 2:
            for pos in range(offset, offset + length, 16):
                tag, value = struct.unpack_from('<QQ', data, pos)
                if tag == 0:
                    break
                if tag == 1:
                    needed.append(value)
                if tag == 5:
                    strings = value
    if needed:
        segments = [h for h in headers if h[0] == 1 and h[3] <= strings < h[3] + h[5]]
        if len(segments) != 1:
            raise ValueError('Invalid ELF string table')
        segment = segments[0]
        offset = segment[2] + strings - segment[3]
        needed = [data[offset+n:].split(b'\0', 1)[0].decode() for n in needed]
    return interpreter, needed


class ImageFiles:
    def __init__(self, image, debugfs):
        self.image, self.debugfs = image, debugfs

    def command(self, command):
        return subprocess.run([self.debugfs, '-R', command, str(self.image)],
                              check=True, capture_output=True, text=True).stdout

    def dump(self, source, destination):
        # The root is usr-merged. Resolve final symlinks too: debugfs dump does not.
        source = source.replace('/lib/', '/usr/lib/', 1) if source.startswith('/lib/') else source
        for _ in range(16):
            info = self.command(f'stat {source}')
            link = re.search(r'Fast link dest: "([^"]+)"', info)
            if not link:
                break
            value = link[1]
            source = value if value.startswith('/') else str(PurePosixPath(source).parent / value)
        else:
            raise ValueError('Too many symlinks')
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.command(f'dump {source} {destination}')
        if not destination.exists() or not destination.stat().st_size:
            raise ValueError(f'Cannot extract {source}')


def cpio(root, output):
    """Write a deterministic newc initramfs without root, mknod or host cpio."""
    with gzip.GzipFile(filename=str(output), mode='wb', mtime=0) as out:
        def entry(name, mode, data, inode):
            encoded = name.encode() + b'\0'
            values = [inode, mode, 0, 0, 1, 0, len(data), 0, 0, 0, 0, len(encoded), 0]
            header = b'070701' + ''.join(f'{x:08x}' for x in values).encode()
            out.write(header + encoded)
            out.write(b'\0' * (-(len(header) + len(encoded)) % 4))
            out.write(data)
            out.write(b'\0' * (-len(data) % 4))
        for inode, path in enumerate(sorted(root.rglob('*')), 1):
            data = os.readlink(path).encode() if path.is_symlink() else path.read_bytes() if path.is_file() else b''
            entry(path.relative_to(root).as_posix(), path.lstat().st_mode, data, inode)
        entry('TRAILER!!!', 0, b'', 0)


def prepare(args):
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    if any(c.isspace() for c in str(work)):
        raise ValueError('Work path must not contain whitespace (debugfs commands)')
    image = work / 'systemcore.img'
    with zipfile.ZipFile(args.image_zip) as archive:
        images = [n for n in archive.namelist() if n.endswith('.img')]
        if len(images) != 1:
            raise ValueError('Expected exactly one .img in release ZIP')
        with archive.open(images[0]) as source, image.open('wb') as out:
            shutil.copyfileobj(source, out)
    rootfs = work / 'rootfs.ext4'
    extract_root(image, rootfs)
    image.unlink()  # Only the extracted temporary copy, never the source ZIP.
    files = ImageFiles(rootfs, args.debugfs)
    if 'Type: directory' not in files.command(f'stat /usr/lib/modules/{args.release}'):
        raise ValueError('Image module directory does not match SDK kernel release')
    root = work / 'initramfs'
    root.mkdir()  # Require a fresh work directory to avoid stale files in a test.
    for directory in ('bin', 'lib', 'dev', 'proc', 'sys', 'tmp'):
        (root / directory).mkdir()
    files.dump('/bin/busybox', root / 'bin/busybox')
    (root / 'bin/busybox').chmod(0o755)
    for applet in ('sh', 'mount', 'uname', 'insmod', 'rmmod', 'cat', 'poweroff', 'grep', 'sleep'):
        (root / 'bin' / applet).symlink_to('busybox')
    (root / 'lib64').symlink_to('lib')
    binaries = [root / 'bin/busybox']
    if args.stage:
        shutil.copy2(args.stage / 'usr/bin/ethercat', root / 'bin/ethercat')
        binaries.append(root / 'bin/ethercat')
        for module in ('ec_master', 'ec_generic'):
            shutil.copy2(args.stage / f'lib/modules/{args.release}/ethercat/{module}.ko', root / f'{module}.ko')
    copied = set()
    while binaries:
        binary = binaries.pop()
        interpreter, needed = elf_dependencies(binary)
        dependencies = ([interpreter] if interpreter else []) + ['/lib/' + n for n in needed]
        for dependency in dependencies:
            if dependency in copied:
                continue
            copied.add(dependency)
            dest = root / dependency.lstrip('/')
            files.dump(dependency, dest)
            dest.chmod(0o755)
            binaries.append(dest)
    files.dump('/etc/os-release', root / 'os-release')
    checks = ''
    if args.stage:
        checks = '''
/bin/ethercat version
insmod /ec_master.ko main_devices=02:00:00:00:00:01
insmod /ec_generic.ko
/bin/ethercat master
/bin/ethercat slaves
rmmod ec_generic
rmmod ec_master
'''
    init = root / 'init'
    init.write_text('''#!/bin/sh
export PATH=/bin
fail() { echo SYSTEMCORE_SMOKE_FAIL; poweroff -f; while :; do sleep 1; done; }
trap fail EXIT
set -eu
mount -t devtmpfs devtmpfs /dev
exec </dev/console >/dev/console 2>&1
mount -t proc proc /proc
mount -t sysfs sysfs /sys
cat /os-release
''' + f'[ "$(uname -r)" = "{args.release}" ]\n' + checks + '''
echo SYSTEMCORE_SMOKE_PASS
trap - EXIT
poweroff -f
while :; do sleep 1; done
''')
    init.chmod(0o755)
    cpio(root, work / 'initramfs.cpio.gz')
    rootfs.unlink()
    return work


def boot(args, work):
    command = [args.qemu, '-machine', 'virt', '-cpu', 'max', '-accel', 'tcg',
               '-m', '1024', '-smp', '2', '-nographic', '-monitor', 'none', '-nic', 'none',
               '-no-reboot', '-kernel', str(args.kernel), '-initrd', str(work / 'initramfs.cpio.gz'),
               '-append', 'console=ttyAMA0 earlycon=pl011,0x9000000 rdinit=/init panic=-1 random.trust_cpu=on']
    (work / 'qemu-command.txt').write_text(' '.join(command) + '\n')
    with (work / 'console.log').open('wb') as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        try:
            code = process.wait(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            raise RuntimeError(f'QEMU timed out after {args.timeout}s; inspect {work}/console.log')
    text = (work / 'console.log').read_text(errors='replace')
    print(text)
    if code != 0 or 'SYSTEMCORE_SMOKE_PASS' not in text or 'SYSTEMCORE_SMOKE_FAIL' in text:
        raise RuntimeError('QEMU boot/module test did not pass')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image-zip', type=Path)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--boot-only', action='store_true')
    parser.add_argument('--kernel', required=True, type=Path)
    parser.add_argument('--release', required=True)
    parser.add_argument('--work', required=True, type=Path)
    parser.add_argument('--stage', type=Path)
    parser.add_argument('--debugfs', default='debugfs')
    parser.add_argument('--qemu', default='qemu-system-aarch64')
    parser.add_argument('--timeout', default=240, type=int)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9.+_-]+', args.release):
        parser.error('Invalid kernel release')
    if args.prepare_only and args.boot_only:
        parser.error('Choose one mode')
    if not args.boot_only and not args.image_zip:
        parser.error('--image-zip is required to prepare a boot image')
    work = args.work if args.boot_only else prepare(args)
    if not args.prepare_only:
        boot(args, work)
