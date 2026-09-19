# GitHub Actions: SystemCore build and boot test

Run **SystemCore IPK and QEMU boot** from Actions, or push/open a PR. Automatic
runs target **beta hardware, beta14**. Manual runs can select alpha14 or beta14,
and ARM64, x64, or both boot-test runners. The exact Limelight release tags,
asset names, kernel release, and SHA256 digests are in `releases.json`. This is
not a moving `latest` download. Select the release that matches your hardware;
these IPKs do not target other installed OS releases.

## What runs where

1. `ubuntu-24.04` runs host tests, downloads and verifies the official image,
   kernel archive, and toolchain, relocates the SDK, then cross-compiles the
   modules, CLI and library and creates the IPK. Build helpers in the supplied
   kernel archive are **x86-64 executables**; an ARM64 runner cannot run this SDK
   natively. The image itself does not contain GCC.
2. The build extracts BusyBox and its dynamic libraries from the official image's
   ext4 root partition. It adds the compiled CLI and modules plus a small `/init`
   test script, and packs an initramfs (a filesystem loaded into RAM at boot).
   Filesystem extraction uses Ubuntu's `debugfs`; no root mounts are needed.
3. `ubuntu-24.04-arm` and `ubuntu-24.04` both boot the **unmodified official kernel**
   with this image-derived userspace on QEMU's `virt` board. TCG software emulation
   is explicit, so nested virtualization or `/dev/kvm` is not required. The tests
   check the kernel release, run the CLI, load both EtherCAT modules, query the
   MainDevice/SubDevice list, unload the modules, and power off. A missing success marker,
   panic, nonzero QEMU exit, or timeout fails the job. Logs are always uploaded.

The IPK builds on x64; ARM64 is used for the kernel/runtime test. If ARM64 runners
are unavailable under your GitHub account's policy or capacity, dispatch with
`smoke_runners: x64`. This is an explicit fallback: Actions cannot automatically
recover a job that never acquires a runner. Both architectures use the same boot
bundle. A successful overall workflow requires all selected boot jobs to pass.

## Booting the image: supported scope

A stock CM5 disk image cannot simply be passed as QEMU's disk and booted as a
SystemCore. QEMU has no CM5/Pi 5 board model. The pinned Limelight kernel also
has `CONFIG_VIRTIO_MMIO` and `CONFIG_VIRTIO_PCI` disabled, so a virtual block
device is unavailable without changing the kernel. The RAM filesystem lets the
**original kernel and original image binaries** run without inventing a replacement
kernel or downloading an unofficial Raspberry Pi image.

This is a minimal boot of extracted SystemCore userspace, not a full SystemCore
systemd boot or hardware emulation. Compilation happens on the x64 runner using
the official SDK, not inside the guest. The test has no Ethernet device: it checks
module ABI, initialization, userspace linking and MainDevice ioctl access, not SubDevice
communication, real-time performance, CM5 I/O, or FRC safety behavior. IPK package
manager installation and service lifecycle remain on-device acceptance checks.

## Artifacts and diagnostics

- `ec-systemcore-<variant>-ipk`: IPK, pinned release manifest, compiler/host/source
  information, and artifact hashes. Treat it as a candidate until the full run
  passes; the build job uploads it before the boot jobs execute.
- `systemcore-boot`: kernel, expected kernel release, and initramfs for reproducing
  the test (seven-day retention). Contains a small subset of the official image.
- `systemcore-build-log`: build output and configure failure logs.
- `systemcore-boot-<runner>`: serial console and exact QEMU command.

Use official Ubuntu apt repositories and GitHub's own checkout/artifact actions.
No third-party VM, Raspberry Pi kernel, rootfs image, or setup-QEMU action is used.
Ubuntu patch revisions and apt packages evolve; `ubuntu-24.04` standardizes the
runner distribution but is not an immutable host image. Firmware/SDK asset bytes
are pinned; this workflow does not claim bit-identical compiled binaries across
runner image updates.

On x86-64 Ubuntu 24.04 with the packages listed in the workflow:

```sh
bash packaging/systemcore/ci/build.sh /tmp/ec-systemcore-ci beta
python3 packaging/systemcore/ci/image-smoke.py --boot-only \
  --work /tmp/ec-systemcore-ci/boot --kernel /tmp/ec-systemcore-ci/boot/Image \
  --release "$(cat /tmp/ec-systemcore-ci/boot/kernel-release)"
```

The work directory must be new. Allow approximately 12 GB of free disk space for
SDK, kernel sources, image extraction and output. Download/extraction failures
stop the build. No credentials, image flashing, deployment, or release publishing
are part of this workflow.

## Verification performed during implementation

Locally tested on macOS ARM64 with QEMU 9.0.1 using the checksum-verified beta14
image and kernel: Linux `6.12.77-v8-16k` booted, image BusyBox/glibc ran, the expected
kernel release check passed, and the guest powered off with
`SYSTEMCORE_SMOKE_PASS`. This local run omitted `--stage`, so it did **not** test
compiled EtherCAT modules. No GitHub Actions run or complete SDK build has been
performed from this workspace. The workflow adds those checks; their results must
be inspected after pushing it. Alpha14 boot is not locally verified.

## Official references

- [Limelight releases and SDK assets](https://github.com/LimelightVision/systemcore-os-public/releases)
- [Limelight kernel build example and host requirements](https://github.com/LimelightVision/systemcore-os-public/tree/main/crosscomp_examples/kernel)
- [QEMU ARM machine compatibility](https://www.qemu.org/docs/master/system/target-arm.html)
- [QEMU Raspberry Pi board support](https://www.qemu.org/docs/master/system/arm/raspi.html)
- [GitHub runner availability](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)
