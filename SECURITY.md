# Security Policy

## Supported versions

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |
| < 1.0   | :x:                |

Security fixes are applied to `main` and released from there.

## Reporting a vulnerability

**Please do not open a public issue for a security problem.**

Report it privately through GitHub's
[Report a vulnerability](https://github.com/mojtaba-py-code/universal-ecommerce-price-intelligence/security/advisories/new)
form, or by email to **mojtaba.python@gmail.com**.

Include what you can:

- the affected version, tag or commit,
- what the issue is and what an attacker gains from it,
- steps or a minimal proof of concept that reproduces it.

## What to expect

- Acknowledgement within **72 hours**.
- An initial assessment within **7 days**.
- A fix and a published advisory once a patch is ready.
- Credit in the advisory, if you want it.

## Scope

In scope: the code in this repository — the FastAPI dashboard and API, the
storage layer, and the scrapers, which parse HTML fetched from hosts this
project does not control.

Out of scope:

- Vulnerabilities in third-party dependencies — report those upstream; if this
  project's use of a dependency is what makes it exploitable, that *is* in scope.
- The demo deployment on Render's free tier. It exists to show the dashboard
  working, holds only seeded demo data, and is not a target — report issues
  against the code, not that host.
- Findings that require an attacker to already control the host or the process.

## Notes for operators

- A scraped page is untrusted input. Anything extracted from it must be escaped
  before it reaches a template, a log line, or a shell.
- Only track URLs you are permitted to track, and keep the request rate low
  enough to respect each store's `robots.txt` and Terms of Service.
- Database credentials belong in the environment. Never commit a populated
  `.env`.
