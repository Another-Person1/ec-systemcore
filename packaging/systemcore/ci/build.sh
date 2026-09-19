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
# Keep regeneration out of the checkout and prevent recursive source copying.
case "$work/" in "$src/"*) echo 'CI work directory must be outside the source tree.' >&2; exit 1 ;; esac
rsync -a --exclude=/.git --exclude=/dist --exclude=__pycache__ "$src/" "$work/source/"
# Checkout timestamps can trigger the old aclocal-1.15 rules in shipped files.
# Regenerate the complete autotools set with this Ubuntu runner's tool versions.
(cd "$work/source" && autoreconf --force --install --verbose)
manifest_args=()
if [[ -n ${SYSTEMCORE_RELEASE_MANIFEST:-} ]]; then
    manifest_args=(--manifest "$SYSTEMCORE_RELEASE_MANIFEST")
fi
python3 "$src/packaging/systemcore/ci/fetch.py" "$variant" "$work/downloads" "${manifest_args[@]}"
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
# Scheduled releases pin asset hashes first, then read the release from that SDK.
SYSTEMCORE_KERNEL_RELEASE=$(python3 - "$work/downloads/release.json" "$KDIR/include/config/kernel.release" <<'PYCODE'
import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
manifest = json.loads(path.read_text())
actual = pathlib.Path(sys.argv[2]).read_text().strip()
if manifest.get('kernel_release') not in (None, actual):
    raise SystemExit('Pinned kernel release does not match the downloaded SDK')
manifest['kernel_release'] = actual
path.write_text(json.dumps(manifest, indent=2) + '\n')
print(actual)
PYCODE
)
export OUTPUT_DIR="$work/output"
bash "$work/source/packaging/systemcore/build.sh"
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
    autoconf --version
    automake --version
    "${CROSS_COMPILE}gcc" --version
    file "$KDIR/scripts/mod/modpost" "$stage/usr/bin/ethercat"
    sha256sum "$work/boot/Image" "$work/boot/initramfs.cpio.gz" "$work/output/"*.ipk
    git -C "$src" rev-parse HEAD
} > "$work/output/build-provenance.txt"
