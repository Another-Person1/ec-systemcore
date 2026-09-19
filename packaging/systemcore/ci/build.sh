#!/bin/bash
# Official Limelight SDK host is x86_64 Linux, including kernel host utilities.
set -euo pipefail
[[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] || {
    echo 'The official SDK requires an x86_64 Linux build host.' >&2; exit 1;
}
src=$(cd "$(dirname "$0")/../../.." && pwd)
work=${1:?Usage: ci/build.sh NEW_WORK_DIRECTORY alpha-or-beta}
variant=${2:-beta}
mkdir "$work"
work=$(cd "$work" && pwd)
python3 "$src/packaging/systemcore/ci/fetch.py" "$variant" "$work/downloads"
asset() {
    python3 - "$work/downloads/release.json" "$1" <<'PY'
import json, sys
print(json.load(open(sys.argv[1]))['assets'][sys.argv[2]]['name'])
PY
}
mkdir "$work/sdk" "$work/linux"
tar -xf "$work/downloads/$(asset toolchain)" -C "$work/sdk"
tar -xf "$work/downloads/$(asset kernel)" -C "$work/linux"
# Free only downloaded archives, leaving SDK source and build evidence intact.
rm "$work/downloads/$(asset toolchain)" "$work/downloads/$(asset kernel)"
mapfile -t relocators < <(find "$work/sdk" -name relocate-sdk.sh -type f)
[[ ${#relocators[@]} == 1 ]] || { echo 'Expected one SDK relocation script.' >&2; exit 1; }
sdk=$(dirname "${relocators[0]}")
(cd "$sdk" && ./relocate-sdk.sh)
mapfile -t kernels < <(find "$work/linux" -path '*/include/config/kernel.release')
[[ ${#kernels[@]} == 1 ]] || { echo 'Expected one prepared kernel tree.' >&2; exit 1; }
export KDIR=${kernels[0]%/include/config/kernel.release}
export CROSS_COMPILE="$sdk/bin/aarch64-buildroot-linux-gnu-"
export SYSTEMCORE_KERNEL_RELEASE
SYSTEMCORE_KERNEL_RELEASE=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["kernel_release"])' "$work/downloads/release.json")
export OUTPUT_DIR="$work/output"
bash "$src/packaging/systemcore/build.sh"
mapfile -t stages < <(find "$OUTPUT_DIR" -path '*/stage/usr/bin/ethercat')
[[ ${#stages[@]} == 1 ]]
stage=${stages[0]%/usr/bin/ethercat}
python3 "$src/packaging/systemcore/ci/image-smoke.py" --prepare-only \
    --image-zip "$work/downloads/$(asset image)" \
    --kernel "$KDIR/arch/arm64/boot/Image" --release "$SYSTEMCORE_KERNEL_RELEASE" \
    --stage "$stage" --work "$work/boot"
cp "$KDIR/arch/arm64/boot/Image" "$work/boot/Image"
printf '%s\n' "$SYSTEMCORE_KERNEL_RELEASE" > "$work/boot/kernel-release"
cp "$work/downloads/release.json" "$work/output/release.json"
{
    uname -a
    "${CROSS_COMPILE}gcc" --version
    file "$KDIR/scripts/mod/modpost" "$stage/usr/bin/ethercat"
    sha256sum "$work/boot/Image" "$work/boot/initramfs.cpio.gz" "$work/output/"*.ipk
    git -C "$src" rev-parse HEAD
} > "$work/output/build-provenance.txt"
