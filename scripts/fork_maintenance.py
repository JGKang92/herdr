"""Build and publish the close-confirmation fork from upstream stable releases."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import urllib.request
from pathlib import Path

PLATFORMS = {
    "linux-x86_64": "herdr-linux-x86_64",
    "linux-aarch64": "herdr-linux-aarch64",
    "windows-x86_64": "herdr-windows-x86_64.zip",
}


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verified_manifest(plan, artifacts, repository):
    assets = {}
    for platform, name in PLATFORMS.items():
        artifact = artifacts / name
        report_path = artifacts / f"{platform}.report.json"
        if not artifact.is_file() or not report_path.is_file():
            raise ValueError(f"Missing validated platform: {platform}")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if (
            report.get("source_sha") != plan["source_sha"]
            or report.get("version") != plan["version"]
            or report.get("validated") is not True
            or report.get("sha256") != file_hash(artifact)
        ):
            raise ValueError(f"Invalid validation report: {platform}")
        assets[platform] = {
            "url": f"https://github.com/{repository}/releases/download/{plan['release_tag']}/{name}",
            "sha256": report["sha256"],
            "format": "zip" if platform.startswith("windows") else "bin",
        }
    return {
        "version": plan["version"],
        "protocol": plan["protocol"],
        "endpoint_generation": plan["endpoint_generation"],
        "notes": release_notes(plan, repository),
        "announcement": None,
        "assets": assets,
    }


def release_plan(upstream, published=None, patch_revision=""):
    tag = upstream["tag_name"]
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise ValueError("Only stable semantic-version release tags are supported")
    if upstream.get("draft") or upstream.get("prerelease"):
        raise ValueError("The upstream release is not a published stable release")
    if not re.fullmatch(r"[0-9a-f]{8,64}", patch_revision):
        raise ValueError("Invalid patch revision")
    release_tag = f"close-confirmation-{tag}-{patch_revision}"
    return {
        "build": not (
            published
            and published.get("tag_name") == release_tag
            and not published.get("draft", True)
        ),
        "version": tag.removeprefix("v"),
        "upstream_tag": tag,
        "release_tag": release_tag,
    }


def apply_close_patch(repository, patch):
    for arguments in (("--check", "--whitespace=error"), ("--whitespace=error",)):
        result = subprocess.run(
            ["git", "-C", str(repository), "apply", *arguments, str(patch)],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if result.returncode:
            raise RuntimeError(f"Close-confirmation patch could not be applied: {result.stderr}")


def run(*arguments, cwd=None, env=None):
    return subprocess.run(
        arguments, cwd=cwd, env=env, check=True, capture_output=True,
        text=True, encoding="utf-8",
    ).stdout.strip()


def api(endpoint, payload=None, optional=False, method="POST"):
    arguments = ["gh", "api", endpoint]
    if payload is not None:
        arguments += ["--method", method, "--input", "-"]
    result = subprocess.run(
        arguments, input=json.dumps(payload) if payload is not None else None,
        capture_output=True, text=True, encoding="utf-8",
    )
    if result.returncode:
        if optional and "HTTP 404" in result.stderr:
            return None
        raise RuntimeError(result.stderr)
    return json.loads(result.stdout) if result.stdout.strip() else None


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def write_outputs(plan):
    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a", encoding="utf-8") as stream:
            for key in ("build", "source_sha", "release_tag", "version", "toolchain"):
                if key in plan:
                    value = str(plan[key]).lower() if isinstance(plan[key], bool) else plan[key]
                    stream.write(f"{key}={value}\n")


def prepare(repository, output):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Invalid fork repository")
    if repository.lower() == "herdrdev/herdr":
        raise ValueError("This workflow is for personal forks only")
    root = Path(__file__).resolve().parent.parent
    patch = root / "fork" / "close-confirmation.patch"
    upstream = api("repos/herdrdev/herdr/releases/latest")
    revision = file_hash(patch)[:12]
    plan = release_plan(upstream, patch_revision=revision)
    published = api(f"repos/{repository}/releases/tags/{plan['release_tag']}", optional=True)
    plan = release_plan(upstream, published, revision)
    if not plan["build"]:
        print(f"Already published: {plan['release_tag']}")
        write_outputs(plan)
        return
    with urllib.request.urlopen("https://herdr.dev/latest.json", timeout=30) as response:
        official = json.load(response)
    if official["version"] != plan["version"]:
        raise ValueError("Upstream release and update manifest disagree; retry next scheduled run")
    output.mkdir(parents=True, exist_ok=False)
    source = output / "source"
    run("git", "clone", "--depth=1", "--branch", plan["upstream_tag"],
        "https://github.com/herdrdev/herdr.git", str(source))
    plan["upstream_sha"] = run("git", "rev-parse", "HEAD", cwd=source)
    cargo = (source / "Cargo.toml").read_text(encoding="utf-8")
    if re.search(r'^version\s*=\s*"([^"]+)"', cargo, re.M)[1] != plan["version"]:
        raise ValueError("Upstream tag and Cargo version disagree")
    plan["toolchain"] = re.search(
        r'channel\s*=\s*"([\d.]+)"',
        (source / "rust-toolchain.toml").read_text(encoding="utf-8"),
    )[1]
    apply_close_patch(source, patch)
    # Do not advertise a server compatibility level merely copied from a website.
    for field, filename, constant in (
        ("protocol", "src/protocol/wire.rs", "PROTOCOL_VERSION"),
        ("endpoint_generation", "src/protocol/endpoint.rs", "ENDPOINT_PROTOCOL_GENERATION"),
    ):
        value = int(re.search(
            rf"pub const {constant}: u32 = (\d+);",
            (source / filename).read_text(encoding="utf-8"),
        )[1])
        if value != official[field]:
            raise ValueError(f"Source and official manifest disagree on {field}")
        plan[field] = value
    environment = os.environ.copy()
    environment.update({
        "GIT_AUTHOR_NAME": "github-actions[bot]",
        "GIT_AUTHOR_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com",
        "GIT_COMMITTER_NAME": "github-actions[bot]",
        "GIT_COMMITTER_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com",
        "GIT_AUTHOR_DATE": upstream["published_at"],
        "GIT_COMMITTER_DATE": upstream["published_at"],
    })
    run("git", "add", "--all", cwd=source)
    run("git", "commit", "-m", f"feat(ui): protect close actions on {plan['upstream_tag']}",
        cwd=source, env=environment)
    plan["source_sha"] = run("git", "rev-parse", "HEAD", cwd=source)
    plan["source_branch"] = f"close-confirmation-builds/{plan['release_tag']}"
    ref = f"refs/heads/{plan['source_branch']}"
    remote = f"https://github.com/{repository}.git"
    existing = run("git", "ls-remote", remote, ref, cwd=source)
    if existing and existing.split()[0] != plan["source_sha"]:
        raise ValueError("Existing build branch has different source; refusing to overwrite")
    if not existing:
        run("git", "-c", "credential.helper=", "-c", "credential.helper=!gh auth git-credential",
            "push", remote, f"HEAD:{ref}", cwd=source)
    write_json(output / "plan.json", plan)
    write_outputs(plan)
    print(f"Prepared {plan['release_tag']} at {plan['source_sha']}")


def package(plan, platform, binary, output, archive=None):
    output.mkdir(parents=True, exist_ok=True)
    version = run(str(binary.resolve()), "--version")
    if version != f"herdr {plan['version']}":
        raise ValueError(f"Wrong binary version: {version}")
    name = PLATFORMS[platform]
    destination = output / name
    shutil.copy2(archive or binary, destination)
    digest = file_hash(destination)
    (output / f"{name}.sha256").write_text(f"{digest}  {name}\n", encoding="utf-8")
    write_json(output / f"{platform}.report.json", {
        "version": plan["version"], "source_sha": plan["source_sha"],
        "sha256": digest, "validated": True,
    })
    if platform.startswith("linux"):
        with tarfile.open(output / f"{name}.tar.gz", "w:gz") as stream:
            for file in (destination, output / f"{name}.sha256", output / f"{platform}.report.json"):
                stream.add(file, arcname=file.name)
        archive_path = output / f"{name}.tar.gz"
        (output / f"{archive_path.name}.sha256").write_text(
            f"{file_hash(archive_path)}  {archive_path.name}\n", encoding="utf-8",
        )


def release_notes(plan, repository):
    return (
        f"Personal Herdr fork based on upstream {plan['upstream_tag']}.\n\n"
        "- Ask before closing panes and tabs; `ui.confirm_close = false` opts out.\n"
        "- `herdr update` uses verified releases from this fork (stable channel only).\n"
        "- Windows x86_64 and native Linux x86_64/aarch64 validation must pass before publication.\n"
        f"- [Source](https://github.com/{repository}/commit/{plan['source_sha']})\n"
        f"- [Upstream release](https://github.com/herdrdev/herdr/releases/tag/{plan['upstream_tag']})\n"
        f"- [Build run](https://github.com/{repository}/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')})\n"
    )


def publish(repository, plan, artifacts):
    manifest = verified_manifest(plan, artifacts, repository)
    write_json(artifacts / "manifest.json", manifest)
    root = Path(__file__).resolve().parent.parent
    installer = (root / "scripts/install_close_confirmation.sh").read_text(encoding="utf-8")
    base = f"https://github.com/{repository}/releases/download/{plan['release_tag']}"
    (artifacts / "install-herdr-close-confirmation.sh").write_text(
        installer.replace("@DOWNLOAD_BASE_URL@", base), encoding="utf-8", newline="\n",
    )
    for name in ("manifest.json", "install-herdr-close-confirmation.sh"):
        (artifacts / f"{name}.sha256").write_text(
            f"{file_hash(artifacts / name)}  {name}\n", encoding="utf-8",
        )
    tag_endpoint = f"repos/{repository}/releases/tags/{plan['release_tag']}"
    release = api(tag_endpoint, optional=True)
    if release and not release["draft"]:
        raise ValueError("Refusing to overwrite a published release")
    if release is None:
        release = api(f"repos/{repository}/releases", {
            "tag_name": plan["release_tag"], "target_commitish": plan["source_sha"],
            "name": f"Herdr {plan['version']} with close confirmation",
            "body": release_notes(plan, repository), "draft": True, "prerelease": False,
        })
    files = sorted(path for path in artifacts.iterdir() if path.is_file())
    run("gh", "release", "upload", plan["release_tag"], "--repo", repository,
        "--clobber", *(str(path) for path in files))
    uploaded = api(f"repos/{repository}/releases/{release['id']}")["assets"]
    digests = {asset["name"]: asset.get("digest") for asset in uploaded}
    for path in files:
        if digests.get(path.name) != f"sha256:{file_hash(path)}":
            raise ValueError(f"Uploaded asset checksum mismatch: {path.name}")
    api(f"repos/{repository}/releases/{release['id']}", {
        "draft": False, "prerelease": False, "make_latest": "true",
    }, method="PATCH")
    print(f"Published https://github.com/{repository}/releases/tag/{plan['release_tag']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare")
    prepare_parser.add_argument("--repository", required=True)
    prepare_parser.add_argument("--output", type=Path, required=True)
    package_parser = commands.add_parser("package")
    package_parser.add_argument("--plan", type=Path, required=True)
    package_parser.add_argument("--platform", choices=PLATFORMS, required=True)
    package_parser.add_argument("--binary", type=Path, required=True)
    package_parser.add_argument("--archive", type=Path)
    package_parser.add_argument("--output", type=Path, required=True)
    publish_parser = commands.add_parser("publish")
    publish_parser.add_argument("--repository", required=True)
    publish_parser.add_argument("--plan", type=Path, required=True)
    publish_parser.add_argument("--artifacts", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.command == "prepare":
        prepare(arguments.repository, arguments.output)
    else:
        plan = json.loads(arguments.plan.read_text(encoding="utf-8"))
        if arguments.command == "package":
            package(plan, arguments.platform, arguments.binary, arguments.output, arguments.archive)
        else:
            publish(arguments.repository, plan, arguments.artifacts)


if __name__ == "__main__":
    main()
