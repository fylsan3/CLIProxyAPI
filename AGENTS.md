# Container runtime working rules

Read `UPGRADE_POLICY_CN.md` before changing or releasing the Go executor. Check the latest official Claude Code release at the time of an upgrade; distinguish protocol compatibility from client/runtime identity declarations. Do not copy identity, account, session, device identifiers or credentials from another client. Do not rewrite customer content to resemble a different environment.

Keep `source/` unchanged: it is verified against `source-inputs.json`. Use reviewed overlays in `src/` and update `overlay-inputs.json` when needed. Keep manually edited headers intact unless the user explicitly requests a compatible change. Never publish account data, generated keys, captures, production configurations or runtime state.

Run focused tests for affected behavior. A mock capture does not verify official subscription endpoints. Record real-account cases still awaiting validation. Production migration, deployment and real-account calls require their corresponding authorization; a source commit does not constitute deployment.

Use `build.py` as the unified build entrypoint. This snapshot is ARM64-only and relies on local Docker base images. See `README.md` and `RELEASE_STATUS_CN.md` for build and deployment limitations.
