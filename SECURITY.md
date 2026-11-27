# Security policy

## Reporting a vulnerability

Report it privately through GitHub: **Security > Report a vulnerability** on this repository
([direct link](https://github.com/Anaximandr0s/football-data-platform/security/advisories/new)).
Do not open a public issue for a security problem.

Include what is affected (service, file or endpoint), how to reproduce it, and the impact you expect.
You get a first answer within 7 days. Once a fix is released, the advisory is published with credit to you
unless you prefer otherwise.

## Supported versions

Only the latest release receives fixes.

## Scope

MatchLens is built to run on one machine with `docker compose`. Some choices are deliberate for that setting
and are not vulnerabilities on their own:

- `.env.example` holds placeholder credentials; `make up` copies it to `.env`. Change them before exposing any port.
- Every service port is published on `127.0.0.1` only.
- The Control Center (`app/api`) and the dashboard have no login: anyone who can reach the port can start a replay.

A way around one of these (for example a service reachable from outside the machine with the default setup)
is in scope.
