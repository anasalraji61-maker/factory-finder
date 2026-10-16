# pin-actions: exact SHA resolution commands (not yet applied)

Status: workflows UNCHANGED. `gh api` returned HTTP 403 ("GitHub access to this repository is not enabled for this session") for every action repo, so no SHA was resolved. SHAs must not be guessed.

Run from a machine with GitHub API access. For each `<owner>/<repo> <tag>` below:

```sh
gh api repos/<owner>/<repo>/git/ref/tags/<tag> --jq '.object.type + " " + .object.sha'
# if type is "tag" (annotated), dereference:
gh api repos/<owner>/<repo>/git/tags/<sha> --jq '.object.sha'
```

Or all at once:

```sh
for r in actions/checkout:v4 actions/setup-python:v5 actions/setup-java:v4 \
         actions/upload-artifact:v4 actions/cache:v4 subosito/flutter-action:v2; do
  o=${r%%:*}; t=${r##*:}
  read -r type sha < <(gh api repos/$o/git/ref/tags/$t --jq '.object.type+" "+.object.sha')
  [ "$type" = tag ] && sha=$(gh api repos/$o/git/tags/$sha --jq '.object.sha')
  echo "$o@$sha # $t"
done
```

Then replace `uses: <action>@<tag>` with `uses: <action>@<sha> # <tag>` in:

| Action | Tag | Files |
|---|---|---|
| actions/checkout | v4 | audit, backend, e2e, ios, mobile-live, mobile |
| actions/setup-python | v5 | audit, backend, e2e, mobile-live |
| actions/setup-java | v4 | mobile |
| actions/upload-artifact | v4 | backend, mobile |
| actions/cache | v4 | ios, mobile-live, mobile |
| subosito/flutter-action | v2 | ios, mobile-live, mobile |

(Supersedes the incomplete list in `infra-pin-actions.md`, which omitted audit.yml, actions/cache and backend upload-artifact.)
