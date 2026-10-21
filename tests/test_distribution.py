import json
import os
import runpy
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path
from dotenv import dotenv_values

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
render = runpy.run_path(str(SCRIPTS / "configure_client.py"))["render"]


class DistributionTests(unittest.TestCase):
    def test_codex_config_preserves_other_servers_comments_and_is_idempotent(self):
        original = "# keep this comment\nmodel = 'existing'\n[mcp_servers.other]\ncommand = 'old-command'\n"
        directory = '/example/My references "quoted"'
        result = render("codex", original, directory, "/example/bin/docker")
        config = tomllib.loads(result)
        self.assertTrue(result.startswith(original))
        self.assertEqual(config["model"], "existing")
        self.assertEqual(config["mcp_servers"]["other"]["command"], "old-command")
        entry = config["mcp_servers"]["same-energy-public"]
        self.assertEqual(entry["args"][2], directory)
        self.assertEqual(entry["tool_timeout_sec"], 180)
        self.assertEqual(render("codex", result, directory, "/example/bin/docker"), result)

    def test_antigravity_config_preserves_other_servers_and_is_idempotent(self):
        original = json.dumps({"other_setting": True, "mcpServers": {"other": {"command": "existing"}}})
        result = render("antigravity", original, "/example/references", "docker")
        config = json.loads(result)
        self.assertTrue(config["other_setting"])
        self.assertEqual(config["mcpServers"]["other"], {"command": "existing"})
        self.assertEqual(config["mcpServers"]["same-energy-public"]["args"][2], "/example/references")
        self.assertEqual(render("antigravity", result, "/example/references", "docker"), result)

    def test_conflicting_client_entry_is_never_overwritten(self):
        for client, original in [("codex", '[mcp_servers.same-energy-public]\ncommand="existing"\n'),
                                 ("antigravity", '{"mcpServers":{"same-energy-public":{"command":"existing"}}}')]:
            with self.subTest(client=client), self.assertRaises(ValueError):
                render(client, original, "/example/references", "docker")

    def test_installer_preserves_existing_env_with_different_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            shutil.copyfile(SCRIPTS / "install.sh", root / "scripts/install.sh")
            existing = "SAME_ENERGY_WORKSPACE_DIR='/another/workspace'\nCUSTOM_SETTING=keep-this-value\n"
            (root / ".env").write_text(existing)
            binary = root / "bin"
            binary.mkdir()
            docker = binary / "docker"
            docker.write_text("#!/bin/sh\nexit 0\n")
            docker.chmod(0o755)
            result = subprocess.run(["bash", str(root / "scripts/install.sh"), "--workspace", str(root / "references")],
                                    env={**os.environ, "PATH": str(binary) + os.pathsep + os.environ["PATH"]},
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((root / ".env").read_text(), existing)
            self.assertNotIn("keep-this-value", result.stdout + result.stderr)
            self.assertFalse((root / "mcp.public.local.json").exists())

    def test_installer_rejects_relative_workspace_before_creating_files(self):
        result = subprocess.run(["bash", str(SCRIPTS / "install.sh"), "--workspace", "relative"], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("pasta absoluta", result.stderr)

    def test_installer_quotes_workspace_with_apostrophe_unicode_and_dollar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            shutil.copyfile(SCRIPTS / "install.sh", root / "scripts/install.sh")
            binary = root / "bin"
            binary.mkdir()
            docker = binary / "docker"
            docker.write_text('#!/bin/sh\ncase "$*" in *"config --quiet"*) exit 9 ;; *) exit 0 ;; esac\n')
            docker.chmod(0o755)
            workspace = root / "Fotos d'Água $referencia#1"
            result = subprocess.run(["bash", str(root / "scripts/install.sh"), "--workspace", str(workspace)],
                                    env={**os.environ, "PATH": str(binary) + os.pathsep + os.environ["PATH"]},
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 9)
            self.assertEqual(dotenv_values(root / ".env")["SAME_ENERGY_WORKSPACE_DIR"], str(workspace.resolve()))


class GuidedHelpTests(unittest.IsolatedAsyncioTestCase):
    async def test_help_tool_resource_and_prompt_work_without_site_access(self):
        from same_energy_mcp.server import mcp, same_energy_help, same_energy_help_resource
        tools = {tool.name: tool for tool in await mcp.list_tools()}
        self.assertTrue(tools["same_energy_help"].annotations.readOnlyHint)
        self.assertFalse(tools["same_energy_help"].annotations.openWorldHint)
        guide = same_energy_help()
        self.assertIn("Como funciona o MCP SAME-ENERGY?", guide["guide"])
        self.assertIn("semelh", guide["guide"])
        self.assertIn("em qual pasta salvar", guide["guide"])
        self.assertTrue(guide["preferences"]["require_visual_review_before_save"])
        self.assertEqual(same_energy_help_resource(), guide["guide"])
        resources = await mcp.list_resources()
        self.assertIn("same-energy://help", [str(resource.uri) for resource in resources])
        prompts = await mcp.list_prompts()
        self.assertIn("como_funciona_same_energy", [prompt.name for prompt in prompts])
