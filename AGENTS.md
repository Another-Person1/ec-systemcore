# Project guidance

## What this repository is

Upstream IgH EtherCAT master from the `stable-1.6` branch at `1.6.13-12-g0ea0fbb` (12
commits after the 1.6.13 tag; version string 1.6.13), with no source changes. Six
documentation-only upstream entries are absent (two PDFs, three `documentation/` Makefiles,
the `doxygen-layout` submodule). On top of that sits packaging under `systemcore/` that
builds an installable `.ipk` for the FRC Systemcore controller (Raspberry Pi CM5, aarch64,
Limelight OS). The package ships the `ec_master` and `ec_generic` kernel modules, the
`ethercat` CLI, `libethercat` with headers, and upstream's `ethercatctl` / `ethercat.conf` /
`ethercat.service`.

## Rules

- Do not modify upstream sources, `Kbuild.in`, `Makefile.am`, `configure.ac` or `script/`.
  All Systemcore work lives in `systemcore/`, `.github/workflows/systemcore.yml`,
  `systemcore-porting.md` and this file.
- Files under `systemcore/` must have LF line endings (enforced by `.gitattributes`).
  Scripts that run on the target (`control/*`, `ethercat-wait-device`) are POSIX `sh`;
  `build.sh` is `bash`.
- Never commit build outputs, downloaded SDKs or generated autotools files. `dist/` is ignored.
- Get the SDK and kernel tree only from
  `https://github.com/LimelightVision/systemcore-os-public/releases`, pinned by tag and
  SHA-256 in `systemcore/releases.env`. Never use `latest` or Raspberry Pi OS headers.
- Kernel modules load only on the exact kernel they were built for. One IPK per hardware
  variant (alpha, beta) and OS release; rebuild after every OS update.
- Only the generic Ethernet driver is built. IgH has no native driver for the CM5 NIC
  (`macb`) on kernel 6.12.
- Installing the package must not start or enable anything. The user picks a dedicated
  wired interface in `/etc/ethercat.conf`; never default to the robot network interface.
- EtherCAT outputs are not tied to FRC enable/disable, brownout or comms loss. Do not claim
  FRC safety integration or competition legality.

## Layout

| Path | Purpose |
|---|---|
| `systemcore/releases.env` | Pinned OS release, asset names, SHA-256, package revision |
| `systemcore/build.sh <alpha\|beta>` | Download, verify, cross-build, stage and pack the IPK |
| `systemcore/control/` | opkg control file and lifecycle script templates (`@VERSION@`, `@VARIANT@`, `@KREL@`) |
| `systemcore/ethercat-wait-device`, `10-systemcore.conf` | Waits for the configured adapter before the service starts |
| `systemcore/Dockerfile`, `docker-build.ps1` | Local build on Windows through Docker Desktop |
| `.github/workflows/systemcore.yml` | Builds both variants and uploads the IPKs |
| `systemcore-porting.md` | Generic, project-independent guide to building IPKs for Systemcore; keep it free of references to this repository |

## How the build works (things that are easy to break)

- The build host must be x86-64 Linux with glibc >= 2.38 (Ubuntu 24.04).
- `build.sh` builds from a fresh `git clone` of **committed HEAD** with LF endings, because
  Windows checkouts are CRLF. Uncommitted changes to upstream sources are not built;
  files in `systemcore/` are read directly, so uncommitted packaging changes are.
- Configure and build happen in-tree in that clone: IgH's Kbuild files set
  `src := @abs_srcdir@`, so a separate build directory fails.
- Upstream `bootstrap` is not executable in git; it is run as `bash ./bootstrap`.
- Modules are installed under `usr/lib/modules/<kernel>/extra/` because the target is
  merged-usr (`build.sh` detects this from the SDK sysroot).
- The IPK is an `ar` archive with members `debian-binary`, `control.tar.gz`, `data.tar.gz`,
  in that order, matching Limelight's published example package.
- Bump `SC_PKG_REV` in `releases.env` whenever package contents change; reset it to 1 and
  update tags and hashes when moving to a new OS release.
- In the workflow, the `runner` context is not available in job-level `env`; GitHub rejects
  the whole file. Use `$RUNNER_TEMP` inside `run:` steps instead.

## Commands

```powershell
./systemcore/docker-build.ps1 beta    # or alpha; output in dist/
```

```sh
bash systemcore/build.sh beta         # on x86-64 Ubuntu 24.04
bash -n systemcore/build.sh
sh -n systemcore/control/preinst systemcore/control/postinst \
      systemcore/control/prerm systemcore/control/postrm systemcore/ethercat-wait-device
```

## Reporting

Keep these evidence levels separate when describing results:

1. Static checks (syntax, line endings).
2. A real cross-build that produced an IPK, with module vermagic matching the kernel release.
3. Installation and operation on a physical Systemcore: package manager accepts the IPK,
   modules load, service starts, `ethercat master` / `ethercat slaves` work.

As of 2026-11-12, levels 1 and 2 are done for release 18 (alpha and beta, kernel
`6.12.112-v8-16k`), both locally in Docker and in GitHub Actions. Level 3 has not been done.
