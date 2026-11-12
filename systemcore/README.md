# Systemcore IPK

## Scope and limits

Packages IgH EtherCAT 1.6.13 for the FRC Systemcore (Raspberry Pi CM5,
aarch64, Limelight OS), using only the generic Ethernet driver (`ec_generic`).
EtherCAT outputs are **NOT tied to FRC enable/disable, brownout or comms loss**.
Provide appropriate application and hardware safety behavior.
There is one IPK per hardware variant and OS release; rebuild after every OS
update. Installation checks the exact kernel release and refuses a loaded master.

## Build locally

With Docker Desktop using Linux containers on an x86-64 host and PowerShell 7:

```powershell
./systemcore/docker-build.ps1 beta
```

Use `alpha` for alpha hardware. Output is `dist/ethercat-igh_<version>_<variant>.ipk`.
Versions use `<upstream>-sc<os release>.<pkg rev>`, for example `1.6.13-sc18.2`.
The build clones **committed HEAD** of the upstream sources with LF endings;
uncommitted source edits are excluded, but packaging helpers from `systemcore/`
are used directly. The repository is mounted read-only. SDK/kernel downloads and
extractions persist in the `ec-systemcore-cache` Docker volume.

Alternatively, on x86-64 Linux with glibc >= 2.38 (Ubuntu 24.04), install the
packages listed in `Dockerfile` and run `bash systemcore/build.sh beta`.
`SC_CACHE`, `SC_WORK`, `SC_OUT` and `JOBS` override cache, work, output and job count.
Work directories are retained for logs; remove old ones when no longer needed.

## Build in GitHub Actions

Push to `main`, open a pull request, or run the Systemcore IPK workflow manually.
Download the alpha or beta artifact. CI caches only verified download archives;
failed builds upload available `config.log` and `build.log` files.

## Bump the OS release

Edit `releases.env`: update `SC_OS_RELEASE` and each variant's tag, asset names
and SHA-256 pins together, and reset `SC_PKG_REV` to 1. Bump `SC_PKG_REV` whenever
package contents change within an OS release. Get the SHA-256 from each release asset's digest in
`LimelightVision/systemcore-os-public` on GitHub (omit the `sha256:` prefix).
Rebuild both variants against the new SDK and prepared kernel tree.

## Install

Use the Systemcore web UI's **Add Package** to upload the matching IPK.
Before replacing an installed package, run `systemctl stop ethercat.service`.
Installation neither enables nor starts the service.

## Configure and start

As root, edit `/etc/ethercat.conf`. Set `MASTER0_DEVICE` to the interface name
(see `ip link`) or MAC address of a dedicated wired adapter, such as USB Ethernet.
Set `UPDOWN_INTERFACES` to that same adapter's interface name. Never use the robot
network interface. `DEVICE_MODULES="generic"` is already set. Device access is
granted to group `systemcore` through udev.

The package installs `/usr/sbin/ethercat-wait-device` and the drop-in
`/etc/systemd/system/ethercat.service.d/10-systemcore.conf`. Before starting,
the helper reads `/etc/ethercat.conf` and waits up to 30 seconds for
`MASTER0_DEVICE` to appear in `/sys/class/net`, matching an interface name or
a MAC address without regard to MAC letter case. Set `ETHERCAT_WAIT_SECONDS`
in `/etc/ethercat.conf` to override the wait (a non-negative integer).
The drop-in sets `TimeoutStartSec=60` for the whole service startup; allow time
for the remaining startup steps when choosing a wait. An empty `MASTER0_DEVICE`
is left for `ethercatctl` to diagnose.

```sh
systemctl enable --now ethercat.service
ethercat master
ethercat slaves
dmesg
```

## Uninstall

As root, run `opkg remove ethercat-igh`. The removal hook attempts to stop the
service and refuses to proceed if `ec_master` or `ec_generic` remains loaded,
reporting each remaining module without forcing an unload. It then attempts to
disable the service, except during upgrades, which preserve its enabled state.
Module dependency and systemd refreshes after removal are best-effort.
The package marks
`/etc/ethercat.conf` as a configuration file for opkg to preserve local changes.
