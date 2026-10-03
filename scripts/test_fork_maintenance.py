import subprocess
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.fork_maintenance import apply_close_patch, release_plan, verified_manifest


class ReleasePlanTests(unittest.TestCase):
    def test_new_stable_release_requires_a_patched_build(self):
        plan = release_plan(
            {"tag_name": "v0.9.3", "draft": False, "prerelease": False},
            patch_revision="abcdef12",
        )
        self.assertTrue(plan["build"])
        self.assertEqual(plan["upstream_tag"], "v0.9.3")
        self.assertEqual(plan["release_tag"], "close-confirmation-v0.9.3-abcdef12")

    def test_a_successfully_published_build_is_not_built_twice(self):
        plan = release_plan(
            {"tag_name": "v0.9.3", "draft": False, "prerelease": False},
            {"tag_name": "close-confirmation-v0.9.3-abcdef12", "draft": False},
            patch_revision="abcdef12",
        )
        self.assertFalse(plan["build"])

    def test_an_unfinished_draft_is_retried(self):
        plan = release_plan(
            {"tag_name": "v0.9.3", "draft": False, "prerelease": False},
            {"tag_name": "close-confirmation-v0.9.3-abcdef12", "draft": True},
            patch_revision="abcdef12",
        )
        self.assertTrue(plan["build"])

    def test_untrusted_release_refs_are_rejected(self):
        for tag in ("../../other", "v1.2.3;echo bad", "preview-2026-10-03"):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                release_plan({"tag_name": tag}, patch_revision="abcdef12")


class PatchApplicationTests(unittest.TestCase):
    def test_a_conflict_leaves_upstream_source_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            subprocess.run(["git", "init", "-q", str(repository)], check=True)
            source = repository / "main.txt"
            source.write_text("new upstream behavior\n", encoding="utf-8")
            patch = repository / "close.patch"
            patch.write_text(
                "diff --git a/main.txt b/main.txt\n"
                "--- a/main.txt\n+++ b/main.txt\n"
                "@@ -1 +1 @@\n-old behavior\n+confirmed close\n",
                encoding="utf-8",
            )
            with self.assertRaises(RuntimeError):
                apply_close_patch(repository, patch)
            self.assertEqual(source.read_text(encoding="utf-8"), "new upstream behavior\n")


class PublicationGateTests(unittest.TestCase):
    def test_a_missing_platform_cannot_be_published(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError):
                verified_manifest(
                    {"version": "0.9.3", "source_sha": "a" * 40},
                    Path(temporary),
                    "example/herdr",
                )

    def test_only_intact_artifacts_from_the_same_validated_source_are_published(self):
        with tempfile.TemporaryDirectory() as temporary:
            artifacts = Path(temporary)
            plan = {
                "version": "0.9.3", "source_sha": "a" * 40,
                "release_tag": "close-confirmation-v0.9.3-abcdef12",
                "upstream_tag": "v0.9.3", "protocol": 22, "endpoint_generation": 1,
            }
            for platform, name in (
                ("linux-x86_64", "herdr-linux-x86_64"),
                ("linux-aarch64", "herdr-linux-aarch64"),
                ("windows-x86_64", "herdr-windows-x86_64.zip"),
            ):
                (artifacts / name).write_bytes(platform.encode())
                report = {
                    "version": plan["version"], "source_sha": plan["source_sha"],
                    "sha256": hashlib.sha256(platform.encode()).hexdigest(), "validated": True,
                }
                (artifacts / f"{platform}.report.json").write_text(json.dumps(report), encoding="utf-8")
            manifest = verified_manifest(plan, artifacts, "example/herdr")
            self.assertEqual(len(manifest["assets"]), 3)
            windows_report = artifacts / "windows-x86_64.report.json"
            original = json.loads(windows_report.read_text(encoding="utf-8"))
            for key, value in (("source_sha", "b" * 40), ("validated", False), ("version", "0.9.2")):
                with self.subTest(key=key), self.assertRaises(ValueError):
                    windows_report.write_text(json.dumps({**original, key: value}), encoding="utf-8")
                    verified_manifest(plan, artifacts, "example/herdr")
            windows_report.write_text(json.dumps(original), encoding="utf-8")
            (artifacts / "herdr-linux-aarch64").write_bytes(b"corrupt download")
            with self.assertRaises(ValueError):
                verified_manifest(plan, artifacts, "example/herdr")


if __name__ == "__main__":
    unittest.main()
