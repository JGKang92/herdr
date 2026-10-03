# Close-confirmation fork maintenance

This personal fork protects pane/tab closing in Herdr's TUI. The existing last-tab
workspace confirmation and `ui.confirm_close = false` setting are preserved.
CLI/API closes retain upstream behavior.

`maintain-close-confirmation.yml` runs every six hours (00:23, 06:23, 12:23,
18:23 UTC) and can also be dispatched manually from the Actions page. GitHub may
delay scheduled jobs. This branch must be the fork's default branch and the
workflow must be enabled. GitHub can disable schedules in public repositories
after 60 days without repository activity; re-enable the workflow if that occurs.

The controller fetches the latest upstream stable release, checks its official
manifest, applies `close-confirmation.patch` with `git apply --check`, and creates
a deterministic source commit on a version-specific `close-confirmation-builds/`
branch. Patch conflicts stop the job. They require a reviewed patch refresh;
the workflow never guesses how to resolve them.

Windows x86_64, native Linux x86_64 and native Linux aarch64 must all pass lint,
tests and packaging before publication. Linux installers are tested for backups,
replacement of an executing file and corrupt-download rejection. Windows uses
upstream's signed ConPTY package. The Linux x86_64 build also runs the upstream
release performance smoke comparison. Every platform records its source commit
and artifact SHA-256. Missing or inconsistent reports prevent publication.

A draft release is uploaded first. Only after GitHub's uploaded asset digests
match is it published as the fork's latest release. An already published version
with the same patch revision is skipped. A failed job leaves the last good release
available. Upstream releases, branches and pull requests are not changed.

## Install and update

Each published release includes `manifest.json`, binary checksums and
`install-herdr-close-confirmation.sh`. Download the installer from this fork's
latest release and run it on Linux; it installs to `~/.local/bin/herdr` and keeps
an existing process alive. Ensure `~/.local/bin` precedes any other Herdr path.

The Windows zip includes the executable and ConPTY dependencies. Use the upstream
Windows installer with `-LocalPackagePath`, `-LocalPackageFormat zip`, the package
SHA-256 and release tag as `-LocalPackageIdentity` when bootstrapping this build.

Fork binaries are compiled with `HERDR_FORK_UPDATE_MANIFEST_URL` pointing to this
fork's latest `manifest.json`. Thereafter `herdr update` installs the next verified
fork build. Updates are announced automatically; installation remains manual.
Official builds and older fork binaries still use the official update channel
and need this one-time bootstrap. Preview updates are rejected in fork builds;
use `[update] channel = "stable"`.

Detach with `Ctrl+B q` before updating. Reattach with `herdr` afterward. Existing
servers remain running when upstream's compatibility rules allow it; an upstream
endpoint-generation change may require a server replacement. Do not update or
stop a server while important work is running if that replacement is requested.

Fork releases use upstream's semantic version. A patch-only rebuild of the same
upstream version requires `herdr update --force`; normal update detection advances
when the upstream stable version increases.

## Refresh the patch

Update only the patch's production/test/draft-documentation files against a clean
upstream stable tag, run focused tests plus the fork-maintenance tests, and regenerate
the binary Git diff as `fork/close-confirmation.patch`. Keep automation files out
of that patch. Push the controller branch and dispatch the workflow. The patch's
SHA-256 prefix identifies the release revision; never edit an already published
release. See the action run and per-platform reports for exact validation results.
