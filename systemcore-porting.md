# Porting and packaging software for Systemcore

A self-contained guide for agents (and people) who need to build any software for the
FRC/FTC Systemcore controller and deliver it as an `.ipk` that installs through Systemcore
OS. It does not depend on any particular project: copy this one file into a repository and
adapt the templates in section 8.

Every fact is tagged with where it comes from:

- **[LL]** Limelight's official repo `LimelightVision/systemcore-os-public` (README release
  notes, `crosscomp_examples/`, `package_examples/`, release assets).
- **[WPI]** `wpilibsuite/SystemcoreTesting` or `wpilibsuite/opensdk`.
- **[BUILT]** Observed in a real cross-build of a package (autotools userspace code plus
  kernel modules) against the official OS release 18 SDK. True for that release; re-check
  on others.
- **[UNVERIFIED]** A reasonable assumption not yet confirmed on physical hardware.

Checked on 2026-11-12 against OS release 18. The OS is alpha/beta software and changes
often; re-read the upstream README before relying on details.

## 1. Sources of truth

| What | Where |
|---|---|
| OS images, SDK, kernel tree, release notes | https://github.com/LimelightVision/systemcore-os-public |
| Package examples | `package_examples/hello-world-autostart`, `hello-world-socketstart` in that repo |
| Cross-compile examples | `crosscomp_examples/cpp`, `go`, `kernel` in that repo |
| Tester docs, vendor package links, quick start | https://github.com/wpilibsuite/SystemcoreTesting |
| WPILib robot-code toolchain | https://github.com/wpilibsuite/opensdk |
| WPILib 2027 docs | https://docs.wpilib.org/en/latest/ |
| Limelight software EULA (applies to downloads) | https://docs.limelightvision.io/eula |

Do not use Raspberry Pi OS images, headers or kernels, and do not use unofficial mirrors.

## 2. The target

| Property | Value | Source |
|---|---|---|
| Hardware | Raspberry Pi CM5-based controller, aarch64 (Cortex-A76) | [LL] asset names, [WPI] opensdk `TARGET_CPU` |
| OS | Limelight OS, built with Buildroot, systemd init | [LL], [BUILT] |
| Kernel | 6.12.x with built-in preemption; 6.12.112 since release 17 | [LL] |
| Kernel release string (release 18, alpha and beta) | `6.12.112-v8-16k`, vermagic `SMP preempt_rt mod_unload modversions aarch64` | [BUILT] |
| Page size | **16K** (since release 10) | [LL] |
| C/C++ | GCC 14, glibc | [LL] |
| Other runtimes on the device | Python 3.13 with venv and pip, Java 25 (Adoptium), Docker, git, vim, `opkg-utils` | [LL] |
| Kernel modules | Compression enabled; `modversions` on | [LL], [BUILT] |
| Filesystem | A/B partition layout; `/lib` is a symlink into `/usr` (merged-usr) in the SDK sysroot | [LL], [BUILT] |
| Default login | user `systemcore`, password `systemcore` (SSH) | [WPI] |
| Robot program | runs as user `systemcore` | [LL] |
| Hostname | `robot.local`; USB IP `172.26.0.1` (Windows) / `172.27.0.1` (Linux, macOS); Wi-Fi AP `172.30.0.1` | [WPI] |
| CAN interfaces | `can_s0`..`can_s4` on Systemcore, `can_d0`..`can_d19` on Motioncore | [WPI] |
| USB storage mounts | `/U`, `/V`, ... | [WPI] |

Consequences for porting:

- **16K pages.** Prebuilt aarch64 binaries that assume 4K pages can fail (allocators such as
  older jemalloc, anything with 4K-aligned ELF segments or hard-coded `mmap` alignment).
  Build from source with the SDK, and never hard-code the page size; use `sysconf(_SC_PAGESIZE)`.
- **Two hardware variants.** Alpha (original units) and beta (units with configuration
  buttons) get separate OS images, SDKs and kernel trees. [LL]
- **OS updates replace the kernel.** Anything containing a kernel module must be rebuilt for
  every OS release and variant. Vendors do this too: CTRE publishes a CANivore IPK per OS
  release. [WPI]

## 3. Getting the SDK

Each OS release on GitHub carries these assets [LL]:

| Asset (beta / alpha) | Use |
|---|---|
| `systemcorebeta-aarch64-toolchain.tar.gz` / `systemcore-aarch64-toolchain.tar.gz` | Cross toolchain and sysroot (~1.7 GB) |
| `systemcorebetalinux.tar.xz` / `systemcorelinux.tar.xz` | Prepared kernel tree for building modules (~200 MB) |
| `limelightsystemcore[beta]cm5-<release>.zip` | Full disk image |
| `limelightsystemcore[beta]-<release>.llupdate` | OTA update payload |
| `LICENSES.txt` | Open-source licence manifest |

Tags look like `limelightosr-2027.0.0-beta18-252` and `limelightosr-2027.0.0-alpha18-422`.
Download URL: `https://github.com/LimelightVision/systemcore-os-public/releases/download/<tag>/<asset>`.

Pin the tag and verify the SHA-256. GitHub publishes one per asset:

```sh
gh api repos/LimelightVision/systemcore-os-public/releases/tags/<tag> \
  --jq '.assets[] | "\(.name) \(.digest)"'
```

Setup, per Limelight's examples [LL]:

1. Build host: **x86-64 Linux**. The example READMEs say glibc 2.38; Ubuntu 24.04 is what
   their Dockerfiles use and is known to work [BUILT]. The SDK does not run on macOS, Windows
   or ARM hosts; use Docker or a VM there.
2. Extract both archives under `/opt` (Limelight's layout:
   `/opt/systemcore-aarch64-toolchain`, `/opt/systemcorelinux`). The top-level directory
   name inside the tarballs differs between alpha and beta, so locate things with `find`
   rather than hard-coding it [BUILT].
3. Run `./relocate-sdk.sh` once from inside the toolchain directory. Skipping this leaves
   paths pointing at Limelight's build machine.
4. Extract on a Linux filesystem. The kernel tree does not survive NTFS or a
   case-insensitive volume; in Docker use a named volume, not a Windows bind mount [BUILT].

Toolchain facts:

- Prefix: `<sdk>/bin/aarch64-buildroot-linux-gnu-` (`gcc`, `g++`, `ld`, `ar`, ...). [LL]
- Sysroot: `<sdk>/aarch64-buildroot-linux-gnu/sysroot`. [LL]
- Autoconf host triple: `aarch64-buildroot-linux-gnu`. [BUILT]
- The sysroot already contains WPILib native libraries such as `ntcore` and `wpiutil`
  under `usr/include` and `usr/lib`. [LL] cpp example

The WPILib toolchain from `wpilibsuite/opensdk` (prefix
`aarch64-systemcore2027-linux-gnu-`, GCC 14.3) is what GradleRIO uses for robot programs.
It has no kernel tree, so it cannot build kernel modules. [WPI]

## 4. Building

### C / C++ with CMake [LL]

Toolchain file from Limelight's example:

```cmake
set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR aarch64)
set(CROSSCOMP_NAME aarch64-buildroot-linux-gnu)
set(HOST_DIR /opt/systemcore-aarch64-toolchain)
set(CMAKE_FIND_ROOT_PATH ${HOST_DIR}/${CROSSCOMP_NAME})
set(CMAKE_SYSROOT ${HOST_DIR}/${CROSSCOMP_NAME}/sysroot)
set(CMAKE_C_COMPILER ${HOST_DIR}/bin/${CROSSCOMP_NAME}-gcc)
set(CMAKE_CXX_COMPILER ${HOST_DIR}/bin/${CROSSCOMP_NAME}-g++)
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
```

```sh
cmake -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_TOOLCHAIN_FILE=cross.cmake && cmake --build build
```

### Autotools [BUILT]

```sh
P=/opt/systemcore-aarch64-toolchain/bin/aarch64-buildroot-linux-gnu-
export PATH="$(dirname "$P"):$PATH"
export CC=${P}gcc CXX=${P}g++ AR=${P}ar RANLIB=${P}ranlib STRIP=${P}strip \
       NM=${P}nm OBJDUMP=${P}objdump OBJCOPY=${P}objcopy READELF=${P}readelf LD=${P}ld
./configure --host=aarch64-buildroot-linux-gnu --prefix=/usr --sysconfdir=/etc
make && make DESTDIR="$PWD/stage" install
```

Export the binutils explicitly or libtool silently falls back to the host's.

### Go [LL]

No SDK needed for pure Go: `GOOS=linux GOARCH=arm64 CGO_ENABLED=0 go build`. For cgo, set
`CGO_ENABLED=1` and point `CC`/`CXX` at the SDK compilers.

### Python [LL]

Python 3.13 is on the device with venv and pip, plus gunicorn, flask-sqlalchemy and
requests. Pure-Python apps need no cross-compilation: ship the files and a systemd unit,
as both official package examples do.

### Docker-based apps [LL]

Docker is on the device "for docker-based packages (enables ROS, custom environments,
etc)". Images must be `linux/arm64` and work with 16K pages.

### Kernel modules [LL]

```sh
make -C /opt/systemcorelinux M="$PWD" ARCH=arm64 \
  CROSS_COMPILE=/opt/systemcore-aarch64-toolchain/bin/aarch64-buildroot-linux-gnu- modules
```

Host packages from Limelight's Dockerfile: `build-essential bc bison flex libssl-dev
libelf-dev make libc6-dev libncurses5-dev rsync cpio wget kmod`.

Checks worth automating [BUILT]:

- The kernel tree is the directory containing `include/config/kernel.release`; that file is
  the exact string `uname -r` prints on the device.
- `Module.symvers` must exist in the tree (it does), or symbol versions cannot be resolved.
- `modinfo -F vermagic your.ko` must start with that release string.
- Fail the build on modpost `undefined!` warnings.
- Use the SDK compiler that belongs to the same release as the kernel tree. Release 15's
  notes mention fixing a "kernel toolchain misalignment introduced in release 14". [LL]
- Install modules to `/usr/lib/modules/<release>/extra/` (the target is merged-usr) and run
  `depmod -a <release>` in `postinst`. [BUILT] for the path, [UNVERIFIED] on hardware.

## 5. The IPK format

An `.ipk` is an `ar` archive. Limelight's published example package has three members in
this order [LL] (inspected from `hello-world-autostart_1.0.0.ipk`):

1. `debian-binary`: the four bytes `2.0\n`
2. `control.tar.gz`: metadata and lifecycle scripts, at the archive root (`./control`, ...)
3. `data.tar.gz`: the files to install, paths relative to `/`

Limelight's example `build.sh` only adds the two tarballs; their shipped `.ipk` nevertheless
contains `debian-binary`. Include it to match the published artifact.

Minimal recipe:

```sh
umask 022
tar --owner=0 --group=0 --numeric-owner -czf control.tar.gz -C control .
tar --owner=0 --group=0 --numeric-owner -czf data.tar.gz    -C overlay .
printf '2.0\n' > debian-binary
rm -f mypkg_1.0.0.ipk
ar r mypkg_1.0.0.ipk debian-binary control.tar.gz data.tar.gz
```

Pitfalls [BUILT]:

- Without `--owner=0 --group=0`, files are owned by your build user's uid on the robot.
- Directory modes in the tarball apply to the target, including `./` (which is `/`). Keep
  them `0755`; a restrictive umask on the build host would otherwise leak in.
- Lifecycle scripts must be executable (`0755`) and have LF line endings. A CRLF shebang
  fails with a confusing "not found". On Windows, set `eol=lf` in `.gitattributes`.
- The device also has `opkg-build` from `opkg-utils` if you prefer building on the robot. [LL]

### `control` file [LL]

```
Package: hello-world-autostart
Version: 1.0.0
Description: Autostart systemcore package
Section: development
Priority: optional
Maintainer: Limelight Vision
Architecture: all
Source: local
X-Port: 9001
X-Has-UI: true
X-Auto-Start: true
X-Icon-Path: /usr/share/hello-world-autostart.png
```

| Field | Meaning | Source |
|---|---|---|
| `Package`, `Version` | Name and version; the example names the file `<Package>_<Version>.ipk` | [LL] |
| `Architecture` | Official examples use `all`. Third-party packages are named `aarch64`/`arm64`; whether the package manager checks it is [UNVERIFIED] | [LL], [WPI] |
| `X-Has-UI` | `true` if the package serves a web UI the Systemcore UI should link to | [LL] |
| `X-Port` | TCP port of that UI | [LL] |
| `X-Https` | When enabled, the Systemcore UI presents `https` URLs for the package | [LL] release 10 |
| `X-Auto-Start` | `true` in the always-running example, `false` in the socket-activated one | [LL] |
| `X-Icon-Path` | Icon shown on the package tile; `.png`, and `.mp4` is supported | [LL] |
| `X-Services` | Comma-separated systemd units; the UI shows restart and stop buttons for them | [LL] release 10 |

Other control-directory files: `postinst`, `prerm`, `postrm` (used by the examples) and the
standard opkg `preinst` and `conffiles` ([UNVERIFIED] that Limelight's package manager
honours the last two; they are standard opkg).

### Where to put files [LL]

| Content | Path in the examples |
|---|---|
| Program files | `/usr/local/bin/<package>/` |
| systemd units | `/etc/systemd/system/<package>.service` (and `.socket`) |
| Icon | `/usr/share/<package>.png` |

### Lifecycle scripts

The official examples do this [LL]:

- `postinst`: `systemctl daemon-reload`, then `enable` and `start` the service (autostart)
  or only the `.socket` unit (socket activation). `exit 0`.
- `prerm`: stop the units, then `disable` them. `exit 0`.
- `postrm`: `systemctl daemon-reload`, `systemctl reset-failed <unit>`. `exit 0`.

Additions that matter for anything beyond a toy [BUILT]:

- Write the scripts in POSIX `sh` (`#!/bin/sh`).
- For kernel modules: check `uname -r` in `preinst` and refuse a mismatch; `depmod -a` in
  `postinst` and `postrm`; refuse removal while the module is loaded.
- opkg runs the old package's `prerm` on upgrade (`$1` is `upgrade`). Only `disable` on a
  real removal or upgrades silently turn off start-on-boot.
- Mark user-edited config under `/etc` in `conffiles`.
- Bump `Version` whenever contents change, or the package manager may treat the new file
  as already installed.

### systemd units [LL]

Always-running service, from the autostart example:

```ini
[Unit]
Description=Hello World Web Service With Autostart
After=network.target
Wants=network.target

[Service]
Type=simple
User=root
Group=root
ExecStart=/usr/local/bin/hello-world-autostart/hello_world_autostart.py
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/log

[Install]
WantedBy=multi-user.target
```

Start-on-demand uses a `.socket` unit (`ListenStream=<port>`, `WantedBy=sockets.target`)
plus a `.service` with `Requires=`/`After=` on the socket and no `[Install]` target; the
program takes the listening socket from systemd (fd 3, `LISTEN_FDS`). Enable only the
socket. This suits UIs that should cost nothing until opened.

If the service needs hardware the robot program also uses, remember the robot program runs
as `systemcore`; grant access with a udev rule (for example `GROUP="systemcore",
MODE="0660"`) rather than running everything as root. [BUILT]

## 6. Installing and testing

- Web UI at `http://robot.local`: click **Add Package** (or drag and drop the file) and
  install one package at a time. [WPI], [LL]
- The UI shows live install logs and checks package-manager health first. [LL] release 10
- The robot program is stopped during installation and restarted afterwards. [LL] release 18
- Installing over an existing package is allowed. [LL] alpha 3
- Packages over 50 MB install correctly since alpha 3. [LL]
- The **System** tab lists services with a per-service "Download Log" button, plus Ports
  and Firewall views; check the Firewall view if your port is unreachable. [LL] release 14
- From SSH: `systemctl status <unit>`, `journalctl -u <unit> -b`, `dmesg`.

Check before shipping, on a build machine:

```sh
ar t pkg.ipk                              # debian-binary control.tar.gz data.tar.gz
ar p pkg.ipk control.tar.gz | tar -tvz    # root-owned, scripts 0755
ar p pkg.ipk data.tar.gz | tar -tvz       # paths, modes, no stray build files
file <binary>                             # ELF 64-bit ... ARM aarch64
sh -n control/postinst                    # each lifecycle script parses
```

## 7. Rules for agents

1. State which evidence level you reached: static checks, a real cross-build, or tested on
   a physical Systemcore. A successful build is not proof that a package installs or runs.
2. Pin the OS release tag and SHA-256 of every SDK asset. Never use "latest".
3. Keep alpha and beta builds separate, and name the variant and OS release in the output.
4. Do not start hardware-affecting services automatically on install unless the user asked.
5. Outputs driven by your software do not follow FRC enable/disable, brownout or comms loss
   unless you implement that. Do not claim safety integration or competition legality.
6. Do not commit SDK archives, kernel trees, images or built packages.

## 8. Templates

Generic starting points. Replace `mypkg`, versions and the build step with your project's.
Suggested layout in any repository:

```
packaging/
  releases.env        pinned OS release, asset names, SHA-256
  build.sh            fetch SDK, cross-build, stage, pack
  control/            control, conffiles, preinst, postinst, prerm, postrm
  overlay/            static files copied to the target as-is (units, icons, config)
  Dockerfile          build environment
```

### `releases.env`

```sh
SC_OS_RELEASE=18
PKG_REV=1          # bump whenever package contents change

BETA_TAG=limelightosr-2027.0.0-beta18-252
BETA_TOOLCHAIN=systemcorebeta-aarch64-toolchain.tar.gz
BETA_TOOLCHAIN_SHA256=<from the release asset digest>
BETA_KERNEL=systemcorebetalinux.tar.xz          # only needed for kernel modules
BETA_KERNEL_SHA256=<from the release asset digest>

ALPHA_TAG=limelightosr-2027.0.0-alpha18-422
ALPHA_TOOLCHAIN=systemcore-aarch64-toolchain.tar.gz
ALPHA_TOOLCHAIN_SHA256=<from the release asset digest>
ALPHA_KERNEL=systemcorelinux.tar.xz
ALPHA_KERNEL_SHA256=<from the release asset digest>
```

### `build.sh <alpha|beta>` skeleton

```bash
#!/bin/bash
set -euo pipefail
umask 022
[[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] || { echo 'Need x86-64 Linux' >&2; exit 1; }
variant=${1:?alpha or beta}
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$here/releases.env"
p=${variant^^}; pin() { local n="${p}_$1"; printf '%s' "${!n}"; }
tag=$(pin TAG)
cache=${SC_CACHE:-$HOME/.cache/systemcore-sdk}/$variant/$tag
work=$(mktemp -d); stage=$work/stage; ctl=$work/control
mkdir -p "$cache" "$stage" "$ctl"

fetch() {  # fetch <asset> <sha256> <dest dir>; verified download, extracted once
    local a=$1 sha=$2 dest=$3
    [[ -f $dest/.complete ]] && return
    curl -fL --retry 3 -o "$cache/$a.tmp" \
        "https://github.com/LimelightVision/systemcore-os-public/releases/download/$tag/$a"
    printf '%s  %s\n' "$sha" "$cache/$a.tmp" | sha256sum -c -
    rm -rf "$dest"; mkdir -p "$dest"; tar -xf "$cache/$a.tmp" -C "$dest"; rm "$cache/$a.tmp"
}
fetch "$(pin TOOLCHAIN)" "$(pin TOOLCHAIN_SHA256)" "$cache/toolchain"
sdk=$(dirname "$(find "$cache/toolchain" -name relocate-sdk.sh -type f)")
[[ -f $cache/toolchain/.complete ]] || { (cd "$sdk" && ./relocate-sdk.sh); touch "$cache/toolchain/.complete"; }
export CROSS_COMPILE="$sdk/bin/aarch64-buildroot-linux-gnu-" PATH="$sdk/bin:$PATH"

# Kernel modules only:
# fetch "$(pin KERNEL)" "$(pin KERNEL_SHA256)" "$cache/kernel"; touch "$cache/kernel/.complete"
# rel=$(find "$cache/kernel" -path '*/include/config/kernel.release'); KDIR=${rel%/include/config/kernel.release}
# KREL=$(cat "$rel")
# make -C "$KDIR" M="$PWD/module" ARCH=arm64 CROSS_COMPILE="$CROSS_COMPILE" modules
# [[ $(modinfo -F vermagic module/x.ko) == "$KREL "* ]]
# install -Dm0644 module/x.ko "$stage/usr/lib/modules/$KREL/extra/x.ko"

# --- your build here: produce files under "$stage" (make DESTDIR="$stage" install, etc.) ---

cp -a "$here/overlay/." "$stage/"
version=1.0.0-sc${SC_OS_RELEASE}.${PKG_REV}
for f in "$here"/control/*; do
    sed -e "s|@VERSION@|$version|g" -e "s|@VARIANT@|$variant|g" "$f" > "$ctl/${f##*/}"
    case ${f##*/} in control|conffiles) chmod 0644 "$ctl/${f##*/}";; *) chmod 0755 "$ctl/${f##*/}";; esac
done
chmod 0755 "$stage" "$ctl"
tar --owner=0 --group=0 --numeric-owner -czf "$work/control.tar.gz" -C "$ctl" .
tar --owner=0 --group=0 --numeric-owner -czf "$work/data.tar.gz" -C "$stage" .
printf '2.0\n' > "$work/debian-binary"
out=${SC_OUT:-$PWD/dist}; mkdir -p "$out"; ipk=$out/mypkg_${version}_${variant}.ipk
rm -f "$ipk"
ar r "$ipk" "$work/debian-binary" "$work/control.tar.gz" "$work/data.tar.gz"
ar t "$ipk"; sha256sum "$ipk"
```

If the source checkout may have CRLF line endings (Windows with `core.autocrlf=true`),
build from `git clone -c core.autocrlf=false <repo> "$work/src"` rather than the working
tree. [BUILT]

### `control/` templates

`control`:

```
Package: mypkg
Version: @VERSION@
Architecture: all
Section: development
Priority: optional
Maintainer: Your Name
Source: local
Description: What it does (Systemcore @VARIANT@ hardware)
X-Has-UI: false
X-Auto-Start: false
X-Services: mypkg.service
```

`postinst`:

```sh
#!/bin/sh
systemctl daemon-reload || exit 1
# depmod -a '<kernel release>' || exit 1      # kernel modules only
# systemctl enable --now mypkg.service        # only if it should start by itself
exit 0
```

`prerm`:

```sh
#!/bin/sh
systemctl stop mypkg.service || true
if [ "${1-}" != upgrade ]; then
    systemctl disable mypkg.service || true
fi
exit 0
```

`postrm`:

```sh
#!/bin/sh
systemctl daemon-reload || true
systemctl reset-failed mypkg.service 2>/dev/null || true
exit 0
```

`preinst` (kernel modules only):

```sh
#!/bin/sh
[ "$(uname -r)" = '<kernel release>' ] || { echo 'Wrong OS release for this package.' >&2; exit 1; }
exit 0
```

### `Dockerfile`

```dockerfile
FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential bc bison flex libssl-dev libelf-dev libncurses-dev rsync cpio kmod \
    autoconf automake libtool pkg-config cmake git curl ca-certificates xz-utils file \
    && rm -rf /var/lib/apt/lists/*
```

Run it with the repository mounted read-only, a named volume for the SDK cache (a Linux
filesystem), and an output directory:

```sh
docker build -t sc-build packaging
docker run --rm -v "$PWD:/src:ro" -v sc-sdk-cache:/cache -v "$PWD/dist:/out" \
    -e SC_CACHE=/cache -e SC_OUT=/out sc-build bash /src/packaging/build.sh beta
```

### GitHub Actions

```yaml
name: Systemcore IPK
on: [push, pull_request, workflow_dispatch]
permissions:
  contents: read
jobs:
  package:
    runs-on: ubuntu-24.04
    strategy:
      fail-fast: false
      matrix:
        variant: [alpha, beta]
    steps:
      - uses: actions/checkout@v7
      - run: |
          sudo apt-get update
          sudo apt-get install -y --no-install-recommends build-essential bc bison flex \
            libssl-dev libelf-dev libncurses-dev rsync cpio kmod autoconf automake libtool \
            pkg-config cmake curl xz-utils file
      - run: bash packaging/build.sh ${{ matrix.variant }}
      - uses: actions/upload-artifact@v7
        with:
          name: ipk-${{ matrix.variant }}
          path: dist/*.ipk
          if-no-files-found: error
```

The `runner` context is not available in job-level `env:`; use `$RUNNER_TEMP` inside `run:`
steps. A hosted runner has enough disk for one variant's SDK per job. [BUILT]
