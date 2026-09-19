#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
set -euo pipefail
src=$(cd "$(dirname "$0")/../.." && pwd)
[[ $(uname -s) == Linux ]] || { echo 'Build on Linux with the Limelight SDK (see README.md).' >&2; exit 1; }
export ARCH=arm64
export CROSS_COMPILE=${CROSS_COMPILE:-/opt/systemcore-aarch64-toolchain/bin/aarch64-buildroot-linux-gnu-}
KDIR=${KDIR:-/opt/systemcorelinux}
KDIR=$(cd "$KDIR" && pwd)
: "${SYSTEMCORE_KERNEL_RELEASE:?Set SYSTEMCORE_KERNEL_RELEASE to uname -r from the target}"
[[ $(cat "$KDIR/include/config/kernel.release") == "$SYSTEMCORE_KERNEL_RELEASE" ]] || { echo 'Target and SDK kernel releases differ.' >&2; exit 1; }
[[ -s $KDIR/Module.symvers ]] || { echo 'A prepared kernel tree with Module.symvers is required.' >&2; exit 1; }
grep -qx 'CONFIG_ARM64=y' "$KDIR/.config"
grep -qx 'CONFIG_MODULES=y' "$KDIR/.config"
# Autoconf/libtool and Kbuild must find all target binutils, not host fallbacks.
compiler=$(command -v "${CROSS_COMPILE}gcc")
export PATH="$(dirname "$compiler"):$PATH"
export NM="${CROSS_COMPILE}nm" OBJDUMP="${CROSS_COMPILE}objdump"
export OBJCOPY="${CROSS_COMPILE}objcopy" READELF="${CROSS_COMPILE}readelf"
export LD="${CROSS_COMPILE}ld" AS="${CROSS_COMPILE}as"
"${CROSS_COMPILE}gcc" --version
# Use a fresh directory; never clean a caller-supplied directory recursively.
output=${OUTPUT_DIR:-$src/dist/systemcore}
mkdir -p "$output"
output=$(cd "$output" && pwd)
[[ "$output" != "$src" ]] || { echo 'OUTPUT_DIR must not be the source root.' >&2; exit 1; }
work=$(mktemp -d "$output/build.XXXXXX")
# Linux Kbuild expects module sources alongside the generated Kbuild files.
# Configure in a disposable source copy, keeping the original checkout untouched.
copy_excludes=(--exclude=/.git --exclude=/dist --exclude=__pycache__)
case "$output/" in
    "$src/"*) copy_excludes+=(--exclude="/${output#"$src"/}/") ;;
esac
rsync -a "${copy_excludes[@]}" "$src/" "$work/"
echo "Build files: $work"
cd "$work"
export CC="${CROSS_COMPILE}gcc" CXX="${CROSS_COMPILE}g++"
export AR="${CROSS_COMPILE}ar" RANLIB="${CROSS_COMPILE}ranlib" STRIP="${CROSS_COMPILE}strip"
./configure --host=aarch64-buildroot-linux-gnu \
    --prefix=/usr --libdir=/usr/lib --sysconfdir=/etc \
    --with-linux-dir="$KDIR" --with-systemdsystemunitdir=no \
    --disable-initd --enable-generic --disable-8139too --disable-e100 \
    --disable-e1000 --disable-e1000e --disable-genet --disable-macb \
    --disable-igb --disable-igc --disable-r8169 --disable-ccat \
    --disable-stmmac-pci --disable-dwmac-intel \
    --disable-eoe --disable-cycles --enable-hrtimer --enable-tool --enable-userlib
make -j"${JOBS:-4}" all modules
stage="$work/stage"
# Stage the CLI and development library without upstream service/config conflicts.
make -C tool DESTDIR="$stage" install
make -C lib DESTDIR="$stage" install
make -C include DESTDIR="$stage" install
moddir="$stage/lib/modules/$SYSTEMCORE_KERNEL_RELEASE/ethercat"
mkdir -p "$moddir"
for module in master/ec_master.ko devices/ec_generic.ko; do
    [[ $(modinfo -F vermagic "$module") == "$SYSTEMCORE_KERNEL_RELEASE "* ]] || { echo "Wrong vermagic: $module" >&2; exit 1; }
    install -m 644 "$module" "$moddir/"
done
python3 "$src/packaging/systemcore/package.py" --stage "$stage" \
    --kernel-release "$SYSTEMCORE_KERNEL_RELEASE" --output "$output" \
    --version "${PACKAGE_VERSION:-1.6.12-1}"
