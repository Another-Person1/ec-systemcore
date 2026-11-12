#!/bin/bash
set -euo pipefail
umask 022

die() { echo "Error: $*" >&2; exit 1; }
[[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] ||
    die 'Build on x86-64 Linux with glibc >= 2.38 (Ubuntu 24.04).'
[[ $# == 1 ]] || die 'Usage: build.sh <alpha|beta>'
variant=$1
case "$variant" in alpha|beta) ;; *) die 'Variant must be alpha or beta.' ;; esac

helpers=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo=$(git -c safe.directory='*' -C "$helpers" rev-parse --show-toplevel)
source "$helpers/releases.env"
prefix=${variant^^}
pin() { local name="${prefix}_$1"; printf '%s' "${!name}"; }
tag=$(pin TAG)
cache=${SC_CACHE:-$HOME/.cache/ec-systemcore}
mkdir -p "$cache"
cache=$(cd -- "$cache" && pwd)
downloads=$cache/downloads/$variant/$tag
trees=$cache/trees/$variant/$tag
workroot=${SC_WORK:-$cache/work}
out=${SC_OUT:-$repo/dist}
mkdir -p "$downloads" "$trees" "$workroot" "$out"
workroot=$(cd -- "$workroot" && pwd)
out=$(cd -- "$out" && pwd)
work=$(mktemp -d "$workroot/$variant.XXXXXXXX")
stage=$work/stage
control=$work/control
mkdir -p "$stage" "$control"
echo "Work directory (retained, including logs): $work"
trap 'status=$?; if (( status != 0 )); then echo "Build failed; inspect $work" >&2; fi' EXIT

download() {
    local asset=$1 sha=$2 archive="$downloads/$1"
    if [[ -f $archive ]] && printf '%s  %s\n' "$sha" "$archive" | sha256sum -c -; then
        return
    fi
    curl -fL --retry 3 -o "$archive.tmp" \
        "https://github.com/LimelightVision/systemcore-os-public/releases/download/$tag/$asset"
    printf '%s  %s\n' "$sha" "$archive.tmp" | sha256sum -c -
    mv -- "$archive.tmp" "$archive"
}

# Find exactly one match, including when archive root directory names change.
one() {
    local -a matches
    mapfile -d '' -t matches < <(find "$@" -print0)
    [[ ${#matches[@]} == 1 ]] || die "Expected exactly one match: find $* (found ${#matches[@]})"
    printf '%s\n' "${matches[0]}"
}

for kind in TOOLCHAIN KERNEL; do
    asset=$(pin "$kind")
    sha=$(pin "${kind}_SHA256")
    download "$asset" "$sha"
    tree=$trees/${kind,,}
    if [[ ! -f $tree/.complete ]] || [[ $(cat "$tree/.complete") != "$sha" ]]; then
        rm -rf -- "$tree"
        mkdir -p "$tree"
        tar -xf "$downloads/$asset" -C "$tree"
        if [[ $kind == TOOLCHAIN ]]; then
            relocate=$(one "$tree" -type f -name relocate-sdk.sh)
            (cd -- "$(dirname -- "$relocate")" && ./relocate-sdk.sh)
        fi
        printf '%s\n' "$sha" > "$tree/.complete"
    fi
done

relocate=$(one "$trees/toolchain" -type f -name relocate-sdk.sh)
sdk=$(dirname -- "$relocate")
gcc=$(one "$trees/toolchain" -path '*/bin/aarch64-buildroot-linux-gnu-gcc')
[[ $gcc == "$sdk/bin/aarch64-buildroot-linux-gnu-gcc" ]] || die 'SDK compiler is not beside relocate-sdk.sh.'
sysroot=$sdk/aarch64-buildroot-linux-gnu/sysroot
[[ -d $sysroot ]] || die "Missing SDK sysroot: $sysroot"
release=$(one "$trees/kernel" -type f -path '*/include/config/kernel.release')
KDIR=${release%/include/config/kernel.release}
KREL=$(cat "$release")
[[ $KREL =~ ^[a-zA-Z0-9._+-]+$ ]] || die "Invalid kernel release: $KREL"
[[ -f $KDIR/Module.symvers ]] || die "Missing $KDIR/Module.symvers; need a prepared kernel tree."
[[ -f $KDIR/.config ]] || die "Missing $KDIR/.config"
if grep -qx 'CONFIG_MODULE_SIG_FORCE=y' "$KDIR/.config"; then
    die 'Kernel requires signed modules (CONFIG_MODULE_SIG_FORCE=y).'
fi
grep -qx 'CONFIG_MODULES=y' "$KDIR/.config" || die 'Kernel lacks CONFIG_MODULES=y.'

git -c safe.directory='*' clone -c core.autocrlf=false --no-hardlinks "$repo" "$work/src"
git -c safe.directory='*' -C "$repo" describe --always > "$work/src/revision" ||
    printf 'unknown\n' > "$work/src/revision"
cd -- "$work/src"
upstream=$(sed -n 's/^AC_INIT(\[ethercat\], \[\([^]]*\)\].*/\1/p' configure.ac)
[[ $upstream =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die 'Cannot read upstream version from AC_INIT.'
version=$upstream-sc${SC_OS_RELEASE}.${SC_PKG_REV}

export ARCH=arm64 CROSS_COMPILE="$sdk/bin/aarch64-buildroot-linux-gnu-"
export PATH="$sdk/bin:$PATH"
export CC="${CROSS_COMPILE}gcc" CXX="${CROSS_COMPILE}g++"
export AR="${CROSS_COMPILE}ar" RANLIB="${CROSS_COMPILE}ranlib"
export STRIP="${CROSS_COMPILE}strip" NM="${CROSS_COMPILE}nm"
export OBJDUMP="${CROSS_COMPILE}objdump" OBJCOPY="${CROSS_COMPILE}objcopy"
export READELF="${CROSS_COMPILE}readelf" LD="${CROSS_COMPILE}ld"
bash ./bootstrap
./configure --host=aarch64-buildroot-linux-gnu --prefix=/usr --sysconfdir=/etc \
    --with-linux-dir="$KDIR" --with-systemdsystemunitdir=/etc/systemd/system --disable-initd \
    --enable-generic --disable-8139too --disable-e100 --disable-e1000 --disable-e1000e \
    --disable-genet --disable-macb --disable-igb --disable-igc --disable-r8169 --disable-ccat \
    --disable-stmmac-pci --disable-dwmac-intel --enable-hrtimer --disable-cycles --disable-eoe \
    --enable-tool --enable-userlib
make -j"${JOBS:-$(nproc)}" all modules 2>&1 | tee "$work/build.log"
if grep -iE 'modpost.*undefined!' "$work/build.log"; then
    die 'modpost reported undefined symbols; refusing to package.'
fi
make DESTDIR="$stage" install

moddir=lib/modules
[[ ! -L $sysroot/lib ]] || moddir=usr/lib/modules
modules=(master/ec_master.ko devices/ec_generic.ko)
for module in "${modules[@]}"; do
    vermagic=$(modinfo -F vermagic "$module")
    [[ $vermagic == "$KREL "* ]] || die "Wrong vermagic for $module: $vermagic (expected $KREL)"
    install -Dm0644 "$module" "$stage/$moddir/$KREL/extra/${module##*/}"
    printf '%s vermagic: %s\n' "$module" "$vermagic"
done

conf=$stage/etc/ethercat.conf
grep -qx 'DEVICE_MODULES=""' "$conf" || die 'Expected empty DEVICE_MODULES assignment not found.'
{
    cat <<'COMMENT'
# Systemcore: set MASTER0_DEVICE to the interface name (see ip link) or MAC
# of a dedicated wired adapter, such as a USB Ethernet adapter. List that
# same interface name in UPDOWN_INTERFACES. Never use the robot network interface.
COMMENT
    sed 's/^DEVICE_MODULES=""$/DEVICE_MODULES="generic"/' "$conf"
} > "$work/ethercat.conf"
install -m0644 "$work/ethercat.conf" "$conf"
install -Dm0755 "$helpers/ethercat-wait-device" "$stage/usr/sbin/ethercat-wait-device"
install -Dm0644 "$helpers/10-systemcore.conf" \
    "$stage/etc/systemd/system/ethercat.service.d/10-systemcore.conf"
mkdir -p "$stage/etc/udev/rules.d" "$stage/usr/share/licenses/ethercat-igh" \
    "$stage/usr/share/ethercat-igh"
printf '%s\n' 'KERNEL=="EtherCAT[0-9]*", MODE="0660", GROUP="systemcore"' \
    > "$stage/etc/udev/rules.d/99-ethercat.rules"
install -m0644 COPYING COPYING.LESSER "$stage/usr/share/licenses/ethercat-igh/"
find "$stage" -type f -name '*.la' -delete
printf '%s\n' "$KREL" > "$stage/usr/share/ethercat-igh/kernel-release"

for template in "$helpers"/control/*; do
    name=${template##*/}
    sed -e "s|@VERSION@|$version|g" -e "s|@VARIANT@|$variant|g" \
        -e "s|@KREL@|$KREL|g" "$template" > "$control/$name"
    case "$name" in
        control|conffiles) chmod 0644 "$control/$name" ;;
        *) chmod 0755 "$control/$name" ;;
    esac
done
chmod 0755 "$stage" "$control"
tar --owner=0 --group=0 --numeric-owner -czf "$work/control.tar.gz" -C "$control" .
tar --owner=0 --group=0 --numeric-owner -czf "$work/data.tar.gz" -C "$stage" .
ipk=$out/ethercat-igh_${version}_${variant}.ipk
rm -f -- "$ipk"
# Limelight's published example IPK carries debian-binary as its first member.
printf '2.0\n' > "$work/debian-binary"
ar r "$ipk" "$work/debian-binary" "$work/control.tar.gz" "$work/data.tar.gz"
ar t "$ipk"
tar -tzf "$work/data.tar.gz"
file "$stage/usr/bin/ethercat" "$stage/$moddir/$KREL/extra/"*.ko
sha256sum "$ipk"
