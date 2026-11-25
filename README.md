> 当前源码候选：container-native4（未部署）。NewAPI 对接、多协议与 OS/架构基线见 [NEWAPI_CONTAINER_INTEGRATION_CN.md](NEWAPI_CONTAINER_INTEGRATION_CN.md)。本机生产仍为上一发布版本；以下旧阶段记录供追溯。

# CPA container runtime — source snapshot

Source release of the `mac-production3` container runtime and `accounts-ui12` management console, based on CPA v8.1.1. One central scheduler manages separate Ubuntu account containers. The account page provides authorization/browser access, status, reported subscription usage, and explicit account-info updates; the original routing UI edits container priorities and weights. Real subscription permissions are not established by offline tests.

`deploy_existing_accounts.py` performs the authorized Mac upgrade after idle checks, retaining account environment and rollback copies. It does not authorize accounts or send model test requests. Review [ACCOUNT_MANAGEMENT_RELEASE_CN.md](ACCOUNT_MANAGEMENT_RELEASE_CN.md) for scope and outstanding real-world validation.

- `source/`: frozen CPA source, verified by `source-inputs.json`.
- `src/`: reviewed local overlays, applied using `overlay-inputs.json`.
- `image/`: account-container runtime sources and Dockerfile.
- `linux/`: separate central/controller service templates (ARM64 only).
- `tests/`: focused capture, deployment and integration tests.
- `request_sample.py`: opt-in loopback recording and replay into closed test environments.

## Build prerequisites

Set `CPA_BUILD_TOOLS` to a directory containing `go/` (Go 1.26.10) and the populated Go `modules/` cache. Dependency fetching is disabled by the build. Import the local pinned Docker base images listed in `base-images.json`; these images have not been published to a registry. This source snapshot does not include the toolchain, binaries, images, generated TLS keys, production settings, accounts, or raw capture data.

Run `python3 -B build.py --compile-only` to compile the worker, Mac/Linux ARM64 central server and config inspectors. Run `python3 -B build.py` with the required local Docker images available to build images, regenerate test certificates and generate the runtime integrity manifest. A source checkout is not directly launchable before the full build. Only use the unified build entrypoint.

The build script's toolchain location and cache location were made configurable for publication. Runtime source, protocol logic and existing manually edited headers were preserved. Client identity declarations are not proof of the actual runtime or official-client equivalence.

See `README_CN.md`, `linux/README_CN.md`, and `RELEASE_STATUS_CN.md` for limitations. No real-account compatibility or production readiness is implied.
