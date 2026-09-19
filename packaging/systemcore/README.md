# SystemCore EtherCAT bring-up

This profile builds the existing IgH 1.6.12 kernel MainDevice, generic Ethernet
backend, `ethercat` CLI, and `libethercat` (including headers) into a SystemCore
IPK. It is for initial bench bring-up: loading the MainDevice and discovering SubDevices.
A cyclic robot application and Driver Station enable/disable, brownout, and
communications-loss handling are not implemented by this package. EtherCAT
outputs do not automatically inherit WPILib's actuator safety behavior.

This guide uses MainDevice/SubDevice terminology. Upstream module and CLI
names remain `ec_master`, `ethercat master`, and `ethercat slaves` for
compatibility.

## GitHub Actions

See [the CI build and QEMU boot guide](ci/README.md) for the pinned official SDK
build on Ubuntu 24.04 x64 and kernel/runtime tests on ARM64 and x64 runners.

## Build

Use Linux and the **official Limelight toolchain and prepared kernel tree for
the exact installed OS release and hardware variant**. Obtain these from the
[SystemCore OS releases](https://github.com/LimelightVision/systemcore-os-public/releases).
Do not substitute Raspberry Pi OS headers. Kernel release equality is necessary
but not sufficient: configuration, symbol versions, page size, and compiler must
also match. Current and older SystemCore images differ in these details.

Follow Limelight's SDK extraction/relocation steps, then run from this tree:

```sh
# On SystemCore, record the actual release:
uname -r

# On Linux, after extracting both official SDK archives under /opt:
cd /opt/systemcore-aarch64-toolchain
./relocate-sdk.sh
cd /path/to/ec-systemcore
SYSTEMCORE_KERNEL_RELEASE='<exact uname -r output>' \
  KDIR=/opt/systemcorelinux \
  CROSS_COMPILE=/opt/systemcore-aarch64-toolchain/bin/aarch64-buildroot-linux-gnu- \
  bash packaging/systemcore/build.sh
```

The host needs the build dependencies listed in Limelight's kernel Dockerfile,
plus Python 3 and pkg-config. The supplied `configure` script is used directly;
autotools regeneration is unnecessary. The SDK compiler itself requires Linux;
on macOS use a Linux VM or an appropriately configured Linux container with the
SDK's supported host architecture.

Output: `dist/systemcore/ethercat-systemcore_<version>_<kernel>_aarch64.ipk`.
Each run retains a unique build/staging directory for inspection. `OUTPUT_DIR`,
`JOBS`, and `PACKAGE_VERSION` are optional overrides. No host installation or
kernel-tree `modules_install` is performed. The build selects generic Ethernet,
high-resolution timers, and no CPU cycle-counter or Ethernet-over-EtherCAT support.
It does not replace SystemCore's normal NIC driver.

To package an already built staging directory independently:

```sh
python3 packaging/systemcore/package.py --stage /path/to/stage \
  --kernel-release '<exact uname -r output>' --output dist/systemcore
```

The packager checks AArch64 ELF files and module vermagic before creating the
archive. Package installation and service startup also check the kernel release.
Rebuild after OS updates; the package does not force incompatible modules to load.
The archive follows Limelight's official two-member ar IPK example and includes
configuration preservation, service metadata, lifecycle hooks, and licenses.

## Install and basic check

1. Upload the IPK through SystemCore's package manager. Installation leaves the
   service stopped; select the EtherCAT interface before starting it.
2. Connect SubDevices through a **dedicated wired Ethernet interface**, preferably a
   separate USB Ethernet adapter. Identify its actual name with `ip link`.
   Configure the OS network manager to leave it without DHCP, IP addresses,
   default routes, or bridge/bond membership. The service does not change those
   settings. Keep the robot/Driver Station network on its own interface.
3. Set `INTERFACE="<actual interface name>"` in
   `/etc/ethercat-systemcore.conf` as root.
4. Run as root:

   ```sh
   systemctl start ethercat-systemcore.service
   systemctl status ethercat-systemcore.service
   ethercat master
   ethercat slaves
   journalctl -u ethercat-systemcore.service -b
   dmesg | tail -50
   ```

   Confirm the MainDevice reports the selected MAC, an attached generic device,
   link up, and the expected SubDevice count/identities. No SubDevices is valid with an
   empty cable, but is not proof of communication. SubDevice discovery alone does
   not put devices into cyclic operational control.
5. Character devices use mode 0660 and the OS's `systemcore` group. Verify
   `ls -l /dev/EtherCAT0` and the robot user's group membership before connecting
   a robot application. Reboot or reload device permissions if another MainDevice
   installation created the device before this package's udev rule existed.
6. After successful manual bring-up, optionally enable boot startup:
   `systemctl enable ethercat-systemcore.service`. For USB adapters, test cold
   boot explicitly; a missing interface fails startup rather than choosing
   another interface. Restart the service after reconnecting an adapter.
7. Stop all EtherCAT applications, then `systemctl stop ethercat-systemcore.service`
   before removing or upgrading the package. Busy module removal fails visibly.
   Stopping leaves the interface administratively up.

Do not infer FRC competition approval from this port. This milestone contains no
WPILib HAL integration or robot output watchdog. Validate those behaviors before
using EtherCAT actuators on a robot. USB/generic-driver real-time performance has
not been measured; no cycle-time guarantee is made.

## Validation status

Host tests cover IPK layout/metadata, permissions, reproducibility, rejection of
wrong architectures/kernel versions, and offline lifecycle hooks. Run:

```sh
python3 -m unittest discover -s packaging/systemcore/tests -v
bash -n packaging/systemcore/build.sh
sh -n packaging/systemcore/ethercat-systemcore
```

An ARM64 build and on-device loading/discovery still require the matching Linux
SDK and physical SystemCore. A synthetic test archive is never a deliverable IPK.
Hardware acceptance should include start/stop/restart, cold boot, removal/upgrade,
a missing adapter, a mismatched kernel, non-root CLI access, and discovery of real
SubDevices. Robot enable/disable and fault response belong to the subsequent control
integration milestone.

## Official platform references

- [Limelight kernel cross-compilation example](https://github.com/LimelightVision/systemcore-os-public/tree/main/crosscomp_examples/kernel)
- [Limelight C++ toolchain example](https://github.com/LimelightVision/systemcore-os-public/tree/main/crosscomp_examples/cpp)
- [Limelight IPK example](https://github.com/LimelightVision/systemcore-os-public/tree/main/package_examples/hello-world-autostart)
- [Limelight OS release notes](https://github.com/LimelightVision/systemcore-os-public)
- [SystemCore June 2025 alpha specifications](https://downloads.limelightvision.io/documents/systemcore_specifications_june15_2025_alpha.pdf) (historical hardware reference)
- [FIRST control-system update](https://community.firstinspires.org/control-system-update-first-tech-challenge-edition) (roadmap context)
