"""Exercise the installed MCP protocol without uploading or saving photographs."""
import asyncio
import json
import os
from datetime import timedelta

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def run():
    env = {key: os.environ[key] for key in ("PLAYWRIGHT_BROWSERS_PATH", "SAME_ENERGY_WORKSPACE", "SAME_ENERGY_HOST_WORKSPACE", "SAME_ENERGY_PREFERENCES_FILE", "SAME_ENERGY_INSTALL_DIRECTORY") if key in os.environ}
    params = StdioServerParameters(command="same-energy-mcp", env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=180)) as session:
            initialized = await session.initialize()
            assert "CONSULTA INICIAL GITHUB" in initialized.instructions
            names = {tool.name for tool in (await session.list_tools()).tools}
            assert len(names) == 10 and "same_energy_prepare_update" in names
            for name in ("same_energy_help", "same_energy_status"):
                result = await session.call_tool(name, {})
                assert not result.isError, name
                if name == "same_energy_status":
                    status = result.structuredContent
                    if status is None:
                        status = json.loads(next(x.text for x in result.content if x.type == "text"))
                    assert status["ready"] and status["preferences"]["photographs_only"]
            resource = await session.read_resource("same-energy://help")
            assert resource.contents
            notes = await session.call_tool("same_energy_update_notes", {})
            assert not notes.isError
            plan = await session.call_tool("same_energy_prepare_update", {})
            assert not plan.isError
            plan_data = json.loads(next(x.text for x in plan.content if x.type == "text"))
            assert not plan_data["ready_to_install"] and "command" not in plan_data
            prompt = await session.call_tool("same_energy_save_image", {"image_id": "installation-check"})
            assert not prompt.isError
            data = json.loads(next(x.text for x in prompt.content if x.type == "text"))
            assert data["requires_user_input"] and not data["saved"]
    print(json.dumps({"verified": True, "tools": len(names), "guided_help": True, "initial_update_check": True, "update_without_consent": False, "uploaded_images": 0, "saved_images": 0}))


asyncio.run(run())
