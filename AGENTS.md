# Container runtime working rules

Read `UPGRADE_POLICY_CN.md` before changing or releasing the Go executor. Check the latest official Claude Code release at the time of an upgrade; distinguish protocol compatibility from client/runtime identity declarations. Do not copy identity, account, session, device identifiers or credentials from another client. Do not rewrite customer content to resemble a different environment.

Keep `source/` unchanged: it is verified against `source-inputs.json`. Use reviewed overlays in `src/` and update `overlay-inputs.json` when needed. Keep manually edited headers intact unless the user explicitly requests a compatible change. Never publish account data, generated keys, captures, production configurations or runtime state.

Run focused tests for affected behavior. A mock capture does not verify official subscription endpoints. Record real-account cases still awaiting validation. Production migration, deployment and real-account calls require their corresponding authorization; a source commit does not constitute deployment.

Use `build.py` as the unified build entrypoint. This snapshot is ARM64-only and relies on local Docker base images. See `README.md` and `RELEASE_STATUS_CN.md` for build and deployment limitations.

## Account request scope — 2026-11-26

Follow `ACCOUNT_REQUEST_INVENTORY_CN.md` for account request coverage and explicit field differences. OAuth, token refresh, profile, roles, usage and reset-card operations belong to this scope; do not leave undocumented exceptions. Distinguish existing behavior from implemented changes and from observed wire results.

Browser request handling stays unchanged for now. At the end of subsequent project replies, remind the user that browser login/verification/callback and browser header handling still need review, until explicitly canceled or accepted. Keep the one-hour task acceptance reminder too. These are conversational reminders, not scheduled automations.

The current candidate must not be published; existing accounts and NewAPI must remain untouched. Updating this inventory does not authorize changing header values or production behavior.

## Test scheduling — latest user instruction, 2026-11-26

Pause new test runs now; accumulate affected cases for the later consolidated test phase. Do not run tests after each individual edit or repeatedly ask to test each step. One local OAuth wire capture completed before this instruction arrived; preserve that result without rerunning it. Current OAuth restoration is in source only; the runtime image has not been rebuilt for it. No production or existing-account changes.

## Current authorization

User authorized consolidated isolated tests and local test-image packaging for this snapshot. Production, existing accounts, NewAPI and real-account calls remain excluded. Do not alter user runtime source to satisfy assertions.

## Latest instruction — 2026-11-26
Re-read user-edited source and compile only. Functional tests remain paused. No production deployment, real-account calls or NewAPI changes. Previous evidence does not validate this new revision.

## Source save authorization — 2026-11-26
User authorized committing and pushing this compile-only source snapshot to a separate branch. This does not authorize production deployment or real-account calls. Functional tests remain paused.

## Cooldown direction A — 2026-11-26
User selected preserving CPA routing/retry policy while repairing the worker/central bridge. Implement only in the candidate; compile without running functional tests, deploying, or calling real accounts. Keep reminding the user at the end of replies that reset-grant consumption remains pending; do not create a scheduled notification.

## Latest authorization — production preparation 2026-11-26
User now authorizes consolidated local tests, packaging and updating the local production release. Preserve account environments and credentials; no NewAPI changes. User will initiate real-account tests after readiness is reported. Capture Go account requests during an explicit test window; browser requests remain unchanged and outside this capture boundary. Only conservatively sanitized derived samples may enter samples/, never raw captures or keys.
