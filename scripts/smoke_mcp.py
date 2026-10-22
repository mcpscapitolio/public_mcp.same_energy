"""Live protocol test; explicitly transmits --image to Same Energy if supplied."""
import argparse
import asyncio
import base64
import json
import os
import sys
from datetime import timedelta
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def run(args):
    report = {"tools": [], "checks": {}}
    Path(args.output).mkdir(parents=True, exist_ok=True)
    env = {k: os.environ[k] for k in ("PYTHONPATH", "PLAYWRIGHT_BROWSERS_PATH", "SAME_ENERGY_WORKSPACE", "SAME_ENERGY_HOST_WORKSPACE", "SAME_ENERGY_PREFERENCES_FILE", "SAME_ENERGY_INSTALL_DIRECTORY", "SAME_ENERGY_CATALOG_PORT") if k in os.environ}
    params = StdioServerParameters(command=sys.executable, args=["-m", "same_energy_mcp.server"], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=180)) as session:
            initialized = await session.initialize()
            assert "CONSULTA INICIAL GITHUB" in initialized.instructions
            report["tools"] = [t.name for t in (await session.list_tools()).tools]

            async def call(name, arguments):
                result = await session.call_tool(name, arguments)
                if result.isError:
                    raise RuntimeError(f"{name}: {result.content}")
                data = next(json.loads(x.text) for x in result.content if x.type == "text")
                report["checks"][name] = data
                for content in result.content:
                    if content.type == "image":
                        Path(args.output, name + "-preview.jpg").write_bytes(base64.b64decode(content.data))
                if name.startswith("same_energy_search"):
                    assert any(x.type == "image" for x in result.content), "Missing contact sheet"
                    assert all(r.get("large_image_verified") for r in data["results"])
                    assert data["visual_review_required"]
                    assert data["results_kind"] == "unreviewed_candidates"
                return data

            help_result = await call("same_energy_help", {})
            assert "Como funciona o MCP SAME-ENERGY?" in help_result["guide"]
            await call("same_energy_check_updates", {})
            await call("same_energy_update_notes", {})
            plan = await call("same_energy_prepare_update", {})
            assert not plan["ready_to_install"] and "command" not in plan
            await call("same_energy_status", {})
            text_search = await call("same_energy_search_by_text", {"query": "cinematic rainy street at night", "limit": 6})
            await call("same_energy_get_gallery", {"gallery_url": text_search["gallery_url"], "limit": 8})
            if args.image:
                uploaded = await call("same_energy_search_by_image", {"image_path": args.image, "limit": 6})
                reloaded = await call("same_energy_get_gallery", {"gallery_url": uploaded["gallery_url"], "limit": 6})
                matches = {r["image_id"] for r in uploaded["results"]} & {r["image_id"] for r in reloaded["results"]}
                assert len(matches) >= min(4, len(uploaded["results"])), "Upload returned a stale or inconsistent gallery"
                report["upload_consistency"] = {"matching_ids_after_reload": sorted(matches), "checked": True}
            preview = await call("same_energy_preview_image", {"image_id": "aghP"})
            assert preview["visual_review_required"] and len(preview["sha256"]) == 64
            prompt = await call("same_energy_save_image", {"image_id": "aghP"})
            assert prompt["requires_user_input"] and not prompt["saved"]
            report["destination_prompt_verified"] = True
            catalog_directory = Path(args.output) / "output_catalog-protocol"
            catalog_directory.mkdir(exist_ok=True)
            catalog = await call("same_energy_create_catalog", {"search_directory": str(catalog_directory), "title": "Verificação do catálogo"})
            assert Path(catalog["path"]).exists() and catalog["url"].startswith("http://127.0.0.1:")
            assert not Path(catalog["selected_directory"]).exists()
            report["catalog_protocol_verified"] = True
            if args.confirm_output:
                review = json.loads(Path(args.visual_review_json).read_text())
                assert review["sha256"] == preview["sha256"], "Examine a nova prévia e atualize a avaliação visual."
                saved = await call("same_energy_save_image", {"image_id": "aghP", "output_directory": args.output, "gallery_url": text_search["gallery_url"], "destination_confirmed": True, "visual_review": review})
                assert saved["saved"], saved
                from same_energy_mcp.client import inspect_image
                measured = inspect_image(Path(saved["path"]).read_bytes())
                assert measured["sha256"] == saved["sha256"]
                assert (measured["width"], measured["height"]) == (saved["width"], saved["height"])
                assert Path(saved["metadata_path"]).parent.name == "json"
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"passed": True, "tools": len(report["tools"]), "checks": list(report["checks"]), "report": args.report}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", help="Absolute mounted path. This file will be uploaded to same.energy.")
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--confirm-output", action="store_true", help="Use somente após o usuário escolher a pasta --output para esta busca; habilita o download real.")
    parser.add_argument("--visual-review-json", help="Avaliação visual de aghP feita pelo assistente após inspeção; obrigatória para download real.")
    args = parser.parse_args()
    if args.confirm_output and not args.visual_review_json:
        parser.error("--confirm-output exige --visual-review-json; o teste não aprova imagens automaticamente.")
    asyncio.run(run(args))
