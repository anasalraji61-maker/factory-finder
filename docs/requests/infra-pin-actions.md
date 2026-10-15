# infra: pin third-party Actions to commit SHAs

SHAs could not be verified (GitHub API unreachable from the agent session), so these remain on tags.
Resolve with `gh api repos/<owner>/<repo>/git/ref/tags/<tag>` (dereference annotated tags) and pin as `@<sha> # vX`.

- actions/checkout@v4 (backend, e2e, ios, mobile-live, mobile)
- actions/setup-python@v5 (backend, e2e, mobile-live)
- actions/setup-java@v4 (mobile)
- actions/upload-artifact@v4 (mobile)
- subosito/flutter-action@v2 (ios, mobile-live, mobile)

Dependabot (github-actions ecosystem) is configured and will keep pins updated once applied.
