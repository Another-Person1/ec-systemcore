# Project guidance

## Purpose and scope

Port the existing IgH EtherCAT MainDevice to Limelight SystemCore (Raspberry Pi
CM5) for FRC development. The initial milestone is basic MainDevice operation,
SubDevice discovery, and a deployable IPK. This repository contains a kernel
MainDevice, drivers, CLI, library, and service scripts, not a standalone userspace
daemon.

Keep changes focused and preserve upstream behavior outside the SystemCore
profile. Follow `CodingStyle.md` for C changes and the existing Linux driver
style in `devices/`. Preserve license notices. Inspect the working tree before
editing and retain unrelated work.

## EtherCAT terminology

Use ETG's **MainDevice** and **SubDevice** terminology in new or edited
SystemCore prose, comments, diagnostic messages, service/package descriptions,
and new identifiers (`maindevice` / `subdevice` where appropriate).

Preserve existing upstream API/ABI and external names when required for
compatibility: `ec_master`, `ecrt_master_*`, `ec_slave_*`, the `master/`
source directory, and the `ethercat master` / `ethercat slaves` CLI commands.
Linux interface paths such as `/sys/class/net/<interface>/master` and source
URLs must also stay unchanged. Explain these legacy names when useful; do
not rename them as part of a terminology-only edit. Preserve upstream
license text and official project titles when quoting them.

## Sources and dependencies

- Use official Limelight, FIRST, and WPILib resources for platform and FRC
  information. Use official QEMU, GitHub, Ubuntu, or other upstream project
  documentation for their respective tools.
- Obtain SystemCore images, prepared kernel trees, and SDKs only from
  `https://github.com/LimelightVision/systemcore-os-public/releases`.
- Do not substitute unofficial Raspberry Pi images, kernels, SDKs, or random
  third-party setup repositories.
- Keep release tags, asset names, and SHA256 hashes pinned in
  `packaging/systemcore/ci/releases.json`. Verify downloads and update related
  documentation when changing a target release. Do not silently use `latest`.
- Keep alpha and beta hardware variants distinct. Match the installed OS,
  kernel configuration, symbol versions, and compiler; `uname -r` alone does
  not establish compatibility.

## Build and boot architecture

- Read `packaging/systemcore/README.md` and
  `packaging/systemcore/ci/README.md` before changing packaging or CI.
- `.github/workflows/systemcore.yml` defines the standard CI environment.
  The pinned official SDK and kernel build helpers require x86-64 Linux;
  build on `ubuntu-24.04` using the official SDK.
- ARM64 and x64 runners run the QEMU boot tests. Keep the explicit x64-only
  dispatch option for environments without ARM64 runner availability.
- Preserve the minimal QEMU `virt` boot of the unmodified official kernel
  and image-derived userspace. Compilation runs on the SDK host, outside
  the guest. Do not make full CM5/systemd emulation a build prerequisite.
- Use TCG for portable boot tests without requiring nested virtualization.
  A full userspace boot is a separate future integration task if needed.
- Keep builds isolated in fresh work directories. Do not commit downloaded
  images, SDK archives, extracted filesystems, build outputs, or Python caches.
- This tree includes generated autotools files. Keep applicable
  `Makefile.am` and `Makefile.in` changes consistent so the supplied
  `configure` path continues to work.

## Runtime and packaging constraints

- Use the generic Ethernet backend for initial bring-up. Require an explicitly
  configured dedicated wired interface; never automatically claim the robot
  or Driver Station network interface.
- Preserve kernel/architecture checks, configuration across upgrades, and
  visible failures when modules are busy or incompatible. Never force-load
  modules to bypass ABI checks.
- Installation must not start an unconfigured MainDevice. Keep package lifecycle
  hooks safe for offline staging and avoid invoking host services there.
- Preserve upstream licenses in the package and follow the official
  Limelight IPK format and service metadata conventions.
- EtherCAT outputs do not automatically inherit WPILib enable/disable,
  brownout, or communications-loss behavior. Do not claim FRC safety
  integration or competition approval from successful packaging or boot.

## Validation

For relevant packaging, service, or CI changes, run:

```sh
python3 -m unittest discover -s packaging/systemcore/tests -v
bash -n packaging/systemcore/build.sh packaging/systemcore/ci/build.sh
sh -n packaging/systemcore/ethercat-systemcore
git diff --check
```

Validate workflow YAML when editing Actions. Run the real SDK build and
QEMU test when the required environment is available. Preserve diagnostic
logs on failure; do not turn a failing boot check into a successful job.

Distinguish these evidence levels in reports:

1. Host unit tests and syntax checks.
2. SDK compilation and creation of a real IPK.
3. QEMU boot with compiled modules: ABI, initialization, dynamic linking,
   and CLI/MainDevice access.
4. Physical SystemCore testing: installation/removal, service lifecycle,
   Ethernet/SubDevice communication, cold boot, timing, and robot fault response.

Synthetic ELF fixtures are packaging tests, not deployable binaries. A boot
without `--stage` does not validate EtherCAT modules. The current QEMU test has
no Ethernet device and cannot establish SubDevice communication or real-time
performance. State exactly what ran and what remains unverified; consult
actual CI results rather than assuming a workflow definition has passed.
