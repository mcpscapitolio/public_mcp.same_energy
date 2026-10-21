import asyncio
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from same_energy_mcp import __version__
from same_energy_mcp.updates import (QUESTION, REPOSITORY, UpdateChecker, bundled_release,
                                    history_path, installed_notes, record_update, startup_notice, version_tuple)

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
SHA = "a" * 40


class UpdateCheckTests(unittest.IsolatedAsyncioTestCase):
    def checker(self, installed="0.3.0", release=None, status=200):
        self.requests = []

        async def respond(request):
            self.requests.append(request)
            self.assertNotIn("authorization", request.headers)
            if request.url.host == "api.github.com":
                self.assertEqual(request.url.path, f"/repos/{REPOSITORY}/git/ref/heads/main")
                return httpx.Response(status, json={"object": {"sha": SHA}})
            self.assertEqual(str(request.url), f"https://raw.githubusercontent.com/{REPOSITORY}/{SHA}/src/same_energy_mcp/release.json")
            return httpx.Response(200, json=release or bundled_release())

        return UpdateChecker(installed, httpx.MockTransport(respond))

    async def test_new_version_checks_github_anonymously_and_pins_release_notes(self):
        checker = self.checker()
        result = await checker.check()
        self.assertTrue(result["update_available"])
        self.assertEqual(result["question"], QUESTION)
        self.assertEqual(result["target_sha"], SHA)
        self.assertEqual(result["changes"], bundled_release()["changes"])
        self.assertEqual(len(self.requests), 2)
        self.assertIn(QUESTION, startup_notice(result))
        self.assertNotIn("command", result)

    async def test_same_and_older_versions_do_not_ask_to_install(self):
        for version in [__version__, "0.2.0"]:
            with self.subTest(version=version):
                checker = self.checker(__version__, {"version": version, "changes": ["Notas"]})
                result = await checker.check()
                self.assertFalse(result["update_available"])
                self.assertIsNone(result["question"])
                self.assertNotIn(QUESTION, startup_notice(result))
        self.assertGreater(version_tuple("0.10.0"), version_tuple("0.9.9"))

    async def test_network_error_and_invalid_metadata_do_not_prevent_current_use(self):
        for checker in [self.checker(status=403), self.checker(release={"version": "not-a-version", "changes": []})]:
            result = await checker.check()
            self.assertEqual(result["status"], "unavailable")
            self.assertFalse(result["update_available"])
            plan = await checker.prepare(True, SHA)
            self.assertFalse(plan["ready_to_install"])
            self.assertNotIn("command", plan)

    async def test_redirects_are_not_followed_to_another_host(self):
        requests = []

        async def respond(request):
            requests.append(request)
            return httpx.Response(302, headers={"location": "https://other.example/manifest"})

        result = await UpdateChecker("0.3.0", httpx.MockTransport(respond)).check()
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(len(requests), 1)

    async def test_consent_and_exact_presented_commit_are_both_required(self):
        checker = self.checker()
        await checker.check()
        for approved, target in [(False, SHA), (True, None), (True, "b" * 40)]:
            with self.subTest(approved=approved, target=target):
                result = await checker.prepare(approved, target)
                self.assertTrue(result["requires_user_approval"])
                self.assertEqual(result["question"], QUESTION)
                self.assertNotIn("command", result)

    async def test_approved_plan_is_quoted_and_does_not_claim_installation(self):
        checker = self.checker()
        await checker.check()
        directory = "/example/Fotos d'Água $reference"
        with patch.dict(os.environ, {"SAME_ENERGY_INSTALL_DIRECTORY": directory}):
            result = await checker.prepare(True, SHA)
        self.assertTrue(result["ready_to_install"])
        self.assertFalse(result["installed"])
        self.assertEqual(shlex.split(result["command"]), ["bash", directory + "/scripts/update.sh", "--approved", "--target-sha", SHA])

    async def test_missing_install_directory_never_returns_an_executable_plan(self):
        checker = self.checker()
        await checker.check()
        with patch.dict(os.environ, {"SAME_ENERGY_INSTALL_DIRECTORY": ""}):
            result = await checker.prepare(True, SHA)
        self.assertTrue(result["requires_install_directory"])
        self.assertNotIn("command", result)

    async def test_initial_protocol_instructions_include_question_and_gate(self):
        fixture = {"status": "update_available", "update_available": True,
                   "installed_version": "0.3.0", "available_version": __version__, "target_sha": SHA,
                   "changes": bundled_release()["changes"]}
        code = ("from same_energy_mcp import server\n"
                f"server.updates.latest = {fixture!r}\n"
                "async def check(): return server.updates.latest\n"
                "server.updates.check = check\nserver.main()\n")
        with tempfile.TemporaryDirectory() as tmp:
            env = {key: os.environ[key] for key in ("PYTHONPATH", "PLAYWRIGHT_BROWSERS_PATH") if key in os.environ}
            env.update(SAME_ENERGY_PREFERENCES_FILE=str(Path(tmp) / "preferences.json"), SAME_ENERGY_INSTALL_DIRECTORY="/example/installation")
            params = StdioServerParameters(command=sys.executable, args=["-c", code], env=env)
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=15)) as session:
                    initialized = await session.initialize()
                    self.assertIn(QUESTION, initialized.instructions[:512])
                    for approved, target in [(False, SHA), (True, "b" * 40), (True, SHA)]:
                        response = await session.call_tool("same_energy_prepare_update", {"approved": approved, "target_sha": target})
                        self.assertFalse(response.isError)
                        data = json.loads(next(content.text for content in response.content if content.type == "text"))
                        self.assertEqual(data["ready_to_install"], approved and target == SHA)
                        if not data["ready_to_install"]:
                            self.assertNotIn("command", data)


class UpdateNotesTests(unittest.TestCase):
    def test_last_update_persists_without_modifying_preferences(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"SAME_ENERGY_PREFERENCES_FILE": str(Path(tmp) / "preferences.json")}):
            preference_file = Path(tmp) / "preferences.json"
            preference_file.write_text('{"custom": "preserve"}')
            record = record_update("0.3.0", SHA, bundled_release())
            self.assertEqual(json.loads(history_path().read_text()), record)
            self.assertEqual(installed_notes()["source"], "last_successful_update")
            self.assertEqual(installed_notes()["changes"], bundled_release()["changes"])
            self.assertEqual(preference_file.read_text(), '{"custom": "preserve"}')

    def test_invalid_or_mismatched_update_record_is_not_written(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"SAME_ENERGY_PREFERENCES_FILE": str(Path(tmp) / "preferences.json")}):
            for sha, release in [("bad", bundled_release()), (SHA, {"version": "9.0.0", "changes": ["other"]})]:
                with self.assertRaises(ValueError):
                    record_update("0.3.0", sha, release)
            self.assertFalse(history_path().exists())
            self.assertEqual(installed_notes()["version"], __version__)


class HostUpdaterTests(unittest.TestCase):
    def test_no_consent_or_invalid_target_exits_before_using_git_or_docker(self):
        for args in [[], ["--target-sha", SHA], ["--approved", "--target-sha", "main; echo unsafe"]]:
            with self.subTest(args=args):
                result = subprocess.run(["bash", str(SCRIPTS / "update.sh"), *args], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                if "--approved" not in args:
                    self.assertEqual(result.stdout.strip(), QUESTION)

    def fixture(self, tmp, fail_build=False):
        root = Path(tmp)
        repo = root / "checkout"
        repo.mkdir()
        real_git = shutil.which("git")
        self.assertIsNotNone(real_git)

        def git(*args):
            return subprocess.check_output([real_git, "-C", str(repo), *args], stderr=subprocess.DEVNULL, text=True).strip()

        git("init", "-b", "main")
        git("config", "user.name", "Test Author")
        git("config", "user.email", "author@example.invalid")
        (repo / "scripts").mkdir()
        shutil.copyfile(SCRIPTS / "update.sh", repo / "scripts/update.sh")
        (repo / "scripts/install.sh").write_text('#!/bin/sh\nprintf installed > "$MCP_TEST_INSTALL_MARKER"\n')
        (repo / ".gitignore").write_text(".env\n")
        (repo / "application.txt").write_text("old version")
        git("add", ".")
        git("commit", "-m", "initial")
        initial = git("rev-parse", "HEAD")
        (repo / "application.txt").write_text("new version")
        release = repo / "src/same_energy_mcp/release.json"
        release.parent.mkdir(parents=True)
        release.write_text(json.dumps(bundled_release()))
        git("add", ".")
        git("commit", "-m", "candidate")
        target = git("rev-parse", "HEAD")
        mirror = root / "mirror.git"
        subprocess.check_call([real_git, "clone", "--bare", str(repo), str(mirror)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        git("reset", "--hard", initial)
        git("remote", "add", "origin", f"https://github.com/{REPOSITORY}.git")
        (repo / ".env").write_text("SAME_ENERGY_WORKSPACE_DIR='/example/keep'\n")
        binary = root / "bin"
        binary.mkdir()
        (binary / "git").write_text(f"#!{sys.executable}\nimport subprocess,sys\nargs=sys.argv[1:]\nif 'fetch' in args: args=['fetch',{str(mirror)!r},args[-1]]\nsys.exit(subprocess.call([{real_git!r},*args]))\n")
        (binary / "docker").write_text(f"#!{sys.executable}\nimport os,subprocess,sys\nargs=sys.argv[1:]\nif args[0]=='build': sys.exit({7 if fail_build else 0})\nif 'same_energy_mcp.updates' in args:\n i=args.index('same_energy_mcp.updates');sys.exit(subprocess.call([sys.executable,'-m',*args[i:]]))\nprint('0.3.0')\n")
        for p in binary.iterdir():
            p.chmod(0o755)
        marker = root / "installed"
        preferences = root / "data/preferences.json"
        preferences.parent.mkdir()
        preferences.write_text('{"custom":"keep"}')
        env = {**os.environ, "PATH": str(binary) + os.pathsep + os.environ["PATH"],
               "MCP_TEST_INSTALL_MARKER": str(marker), "SAME_ENERGY_PREFERENCES_FILE": str(preferences)}
        return repo, git, initial, target, marker, env, preferences

    def test_dirty_checkout_is_preserved_and_not_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, git, initial, target, marker, env, _ = self.fixture(tmp)
            (repo / "application.txt").write_text("user changes")
            result = subprocess.run(["bash", str(repo / "scripts/update.sh"), "--approved", "--target-sha", target], env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(git("rev-parse", "HEAD"), initial)
            self.assertEqual((repo / "application.txt").read_text(), "user changes")
            self.assertFalse(marker.exists())

    def test_failed_candidate_tests_leave_checkout_and_env_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, git, initial, target, marker, env, _ = self.fixture(tmp, fail_build=True)
            before = (repo / ".env").read_bytes()
            result = subprocess.run(["bash", str(repo / "scripts/update.sh"), "--approved", "--target-sha", target], env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(git("rev-parse", "HEAD"), initial)
            self.assertEqual((repo / ".env").read_bytes(), before)
            self.assertFalse(marker.exists())

    def test_successful_approved_update_preserves_env_and_records_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, git, _, target, marker, env, preferences = self.fixture(tmp)
            before = (repo / ".env").read_bytes()
            result = subprocess.run(["bash", str(repo / "scripts/update.sh"), "--approved", "--target-sha", target], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(git("rev-parse", "HEAD"), target)
            self.assertTrue(marker.exists())
            self.assertEqual((repo / ".env").read_bytes(), before)
            self.assertEqual(preferences.read_text(), '{"custom":"keep"}')
            record = json.loads(preferences.with_name("last_update.json").read_text())
            self.assertEqual(record["target_sha"], target)
            self.assertEqual(record["changes"], bundled_release()["changes"])
