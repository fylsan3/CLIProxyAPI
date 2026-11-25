# Account console UI

The account page uses the pinned native management page's sidebar, login store and theme tokens. It is an operational interface: account readiness and authorization actions come first; technical details, usage and backup history are expandable.

- `integration.js` mounts the account view into the native content area and adds one sidebar entry. Native routes, authentication and theme controls remain owned by the original app.
- `index.html`, `style.css` and `app.js` contain the editable account view. `settings.js` and `quota_view.js` present the existing management contracts.
- `python3 -B build_page.py` generates `compiled.js` and `static/management.local.html` from the pinned, committed `static/management.html`. No production directory is needed for this build. `build.py` includes this step.
- The UI sends the same existing management operations. Browser entry buttons reconnect to the account's existing browser; they do not synthesize authorization.
- Account counts use the reported `overall_ready` state. Missing or failed snapshots clear readiness rather than presenting stale success. Expanded account details and focused action controls survive polling; active text entry is not replaced.
- Appearance uses native theme variables, restrained status badges, 40–44 px controls, and responsive layouts. Mobile navigation reuses the native sidebar dismissal.

`tests/ui_preview.py` is a loopback-only visual fixture with fictional accounts. It permits only GET forwarding for native login/configuration and handles all account write actions locally. It is not a production service and must not be deployed. Real authorization and model calls are outside this UI acceptance.
