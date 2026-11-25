# CPA container runtime — source snapshot

Source release of the `portable-capture1` test candidate based on CPA v8.1.1. This branch is a source snapshot, not a production deployment or upstream merge. The source and overlays reproduce the separately tested local candidate. Production migration is not yet validated.

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
