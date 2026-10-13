# Strive fork

This fork keeps upstream history and carries a small downstream patch. Keep
`upstream` pointed at `https://github.com/AbdelftahZowail/Quickly.git`. Fetch
upstream, merge its reviewed revision into a feature branch, test, then open a
PR against this fork's `main`. Use merge commits so pinned source revisions
remain ancestors of `main`. Updating the fork does not deploy anything.

`Dockerfile.strive` builds both the frontend and Python app from source using
pinned base image digests, npm's integrity-checked lockfile, and a Python
version lock. It runs saved-content, personalized scheduling, Gmail OAuth,
and JWT regressions during the build. The runtime runs as UID 999/GID 994.
The private deployment repository selects a full source SHA, runs browser and
integration checks, and owns all production credentials and deployments.
Inherited upstream release and Pages workflows are disabled at repository level.

## Personalized editor

The campaign leads response omitted `body` and `is_html` even though it fetched
both from `CustomEmailOverride`. It now returns both. The editor restores the
saved override format, falling back to the sequence format for unwritten emails.
No database migration is required. This fixes displaying stored content; it
cannot recover content overwritten by a previous save of an empty editor.

## Dependency review (2026-10-13)

The browser runtime dependency audit reports zero known advisories after
updating DOMPurify, React Router, and moving the `react-quill` import to the
maintained `react-quill-new` package. Quill is explicitly held at 2.0.2 to avoid
the known HTML-export advisory in 2.0.3. Vite and its React plugin were updated;
Chromium regressions exercise opening and saving both HTML and plain text with
the opposite sequence default, so the saved override format must win.

Python versions start from the previously pinned image; OAuthlib and PyJWT were
updated to their advisory fixes. Two remaining affected libraries are retained:

- `ecdsa` / PYSEC-2026-1325: signing timing leakage; app sessions use HS256, not
  ECDSA signing. This package is a transitive dependency of python-jose.
- `python-jose` / CVE-2026-85394: asymmetric-key/HMAC confusion. This application
  supplies a private symmetric secret and explicitly allows only HS256. The
  regression verifies that a correctly signed HS384 token is still rejected.

The frontend build tooling retains advisories involving `braces` and
`postcss-selector-parser` through Tailwind 3. Builds operate on reviewed source
without production credentials; these tools are absent from the runtime image.
Do not expose a Vite development server in production. Review these exceptions
on updates; audit counts can change as advisories are published. This focused
review is not a complete security audit or a guarantee of security.

Verification:

```sh
docker build -f Dockerfile.strive -t quickly:review .
cd frontend
npm ci --ignore-scripts
npm audit --omit=dev
npm run build
npx playwright install --with-deps chromium
npx playwright test
```
