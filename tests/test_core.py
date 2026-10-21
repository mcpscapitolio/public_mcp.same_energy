import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from PIL import Image

from same_energy_mcp.client import SameEnergy, SameEnergyError, Workspace, asset_url, gallery_url, image_id, inspect_image, save_original
from same_energy_mcp.preferences import is_large, load_preferences, output_folder_name


def jpeg(size=(1600, 1063)):
    out = io.BytesIO()
    Image.new("RGB", size, "#783d99").save(out, format="JPEG")
    return out.getvalue()


def approved_review(data):
    # Protocol fixture, not an automated visual classifier.
    return {"sha256": inspect_image(data)["sha256"], "is_photograph": True,
            "has_markings": False, "clearly_ai_generated": False, "uncertain": False}


class ValidationTests(unittest.TestCase):
    def test_urls_reject_external_hosts_credentials_redirects_and_thumbnails(self):
        for url in ["http://same.energy/search?q=x", "https://same.energy.evil.test/search?q=x", "https://user@same.energy/search?q=x", "https://same.energy/i/a", "https://same.energy/search?q=x&redirect=https://evil.test", "https://same.energy/search?i=../x", "https://same.energy/search?q=x&q=y", "https://same.energy/search?q="]:
            with self.subTest(url=url), self.assertRaises(SameEnergyError):
                gallery_url(url)
        self.assertEqual(gallery_url("https://www.same.energy/search?q=rainy%20street"), "https://same.energy/search?q=rainy+street")
        for url in ["http://blobcdn.same.energy/a/b", "https://blobcdn.same.energy.evil.test/a", "https://blobcdn.same.energy/thumbnails/a", "https://blobcdn.same.energy:8443/a", "https://user@blobcdn.same.energy/a"]:
            with self.subTest(url=url), self.assertRaises(SameEnergyError):
                asset_url(url)
        self.assertTrue(asset_url("https://blobcdn.same.energy/a/b"))

    def test_identifiers_cannot_escape_url_or_filename(self):
        for ident in ["../x", "a/b", "x?y", "", "x" * 65]:
            with self.subTest(ident=ident), self.assertRaises(SameEnergyError):
                image_id(ident)

    def test_paths_are_confined_and_host_paths_are_translated(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"SAME_ENERGY_WORKSPACE": tmp, "SAME_ENERGY_HOST_WORKSPACE": "/host/photos"}):
                ws = Workspace()
                self.assertEqual(ws.resolve("/host/photos/a.jpg"), Path(tmp) / "a.jpg")
                self.assertEqual(ws.host_path(Path(tmp) / "b.jpg"), "/host/photos/b.jpg")
                for value in ["relative.jpg", "/etc/passwd", "/host/photos/../../etc/passwd"]:
                    with self.assertRaises(SameEnergyError):
                        ws.resolve(value)
                (Path(tmp) / "escape").symlink_to("/etc")
                with self.assertRaises(SameEnergyError):
                    ws.resolve(str(Path(tmp) / "escape/passwd"))

    def test_image_validation_rejects_html_empty_and_truncated_files(self):
        for data in [b"", b"<html>blocked</html>", jpeg()[:100]]:
            with self.assertRaises(SameEnergyError):
                inspect_image(data)
        self.assertEqual(inspect_image(jpeg())["width"], 1600)

    def test_download_preserves_bytes_metadata_and_never_overwrites(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            data = jpeg()
            first = save_original(data, Path(tmp), "aghP", {"source_links": []})
            second = save_original(data, Path(tmp), "aghP", {})
            self.assertNotEqual(first["path"], second["path"])
            self.assertEqual(Path(first["path"]).read_bytes(), data)
            saved = json.loads(Path(first["metadata_path"]).read_text())
            self.assertEqual(saved["sha256"], inspect_image(data)["sha256"])
            self.assertEqual((saved["width"], saved["height"]), (1600, 1063))
            self.assertEqual(Path(first["metadata_path"]).parent, Path(tmp) / "json")
            self.assertFalse(list(Path(tmp).glob("*.json")))

    def test_low_resolution_download_leaves_no_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            for size in [(512, 341), (1600, 400)]:
                with self.assertRaises(SameEnergyError):
                    save_original(jpeg(size), Path(tmp), "a", {})
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_preferences_persist_without_resetting_on_reload(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
            "SAME_ENERGY_PREFERENCES_FILE": str(Path(tmp) / "preferences.json")
        }):
            prefs = load_preferences()
            self.assertTrue(prefs["large_images_only"])
            self.assertTrue(prefs["ask_output_directory_per_search"])
            self.assertEqual(prefs["metadata_subdirectory"], "json")
            prefs["minimum_long_edge"] = 1920
            (Path(tmp) / "preferences.json").write_text(json.dumps(prefs))
            self.assertEqual(load_preferences()["minimum_long_edge"], 1920)

    def test_folder_name_uses_brazil_date_and_cannot_escape(self):
        from datetime import datetime, timezone
        name = output_folder_name("../Rua / Chuva: São Paulo", load_preferences(),
                                  datetime(2026, 10, 22, 1, 30, tzinfo=timezone.utc))
        self.assertEqual(name, "output_2026-10-21_rua-chuva-sao-paulo")
        self.assertTrue(is_large(720, 1280, load_preferences()))
        self.assertFalse(is_large(1600, 400, load_preferences()))

    def test_old_preferences_gain_photo_rule_without_resetting_custom_settings(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
            "SAME_ENERGY_PREFERENCES_FILE": str(Path(tmp) / "preferences.json")
        }):
            path = Path(tmp) / "preferences.json"
            prefs = load_preferences()
            for key in ("photographs_only", "reject_markings", "reject_clearly_ai_generated", "require_visual_review_before_save"):
                prefs.pop(key)
            prefs.update(schema_version=1, minimum_long_edge=1920, metadata_subdirectory="metadados")
            path.write_text(json.dumps(prefs))
            migrated = load_preferences()
            self.assertEqual(migrated["schema_version"], 2)
            self.assertTrue(migrated["photographs_only"])
            self.assertTrue(migrated["reject_markings"])
            self.assertTrue(migrated["reject_clearly_ai_generated"])
            self.assertTrue(migrated["require_visual_review_before_save"])
            self.assertEqual(migrated["minimum_long_edge"], 1920)
            self.assertEqual(migrated["metadata_subdirectory"], "metadados")
            self.assertEqual(json.loads(path.read_text()), migrated)
            self.assertEqual(load_preferences(), migrated)

    def test_json_subdirectory_cannot_be_an_external_symlink(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            (Path(tmp) / "json").symlink_to(outside)
            with self.assertRaises(SameEnergyError):
                save_original(jpeg(), Path(tmp), "a", {})
            self.assertEqual(list(Path(outside).iterdir()), [])


class NetworkTests(unittest.IsolatedAsyncioTestCase):
    async def test_upload_waits_for_results_replacement_after_url_change(self):
        # Reproduce the website: URL changes while the previous feed remains visible.
        html = """<input type=file><div id=results><img sameenergyid=old
            src='https://blobcdn.same.energy/thumbnails/old'></div>
            <script>document.querySelector('input').onchange = () => {
                history.pushState({}, '', '/search?i=uploaded');
                setTimeout(() => { document.querySelector('#results').innerHTML =
                    '<img sameenergyid=fresh src=https://blobcdn.same.energy/thumbnails/fresh>';
                }, 700);
            };</script>"""
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
            "SAME_ENERGY_WORKSPACE": tmp, "SAME_ENERGY_HOST_WORKSPACE": ""
        }):
            photo = Path(tmp) / "input.jpg"
            photo.write_bytes(jpeg())
            c = SameEnergy()
            original_open = c.open

            async def mock_open(page, url):
                async def route(request_route):
                    if "/search?i=uploaded" in request_route.request.url:
                        await request_route.fulfill(status=200, content_type="text/html", body="<img sameenergyid=fresh src=https://blobcdn.same.energy/thumbnails/fresh>")
                    elif request_route.request.url.startswith("https://same.energy"):
                        await request_route.fulfill(status=200, content_type="text/html", body=html)
                    else:
                        await request_route.fulfill(status=200, content_type="image/jpeg", body=jpeg((1, 1)))
                await page.route("**/*", route)
                await original_open(page, url)

            c.open = mock_open
            c.detail_on_page = AsyncMock(return_value={"asset": {"width": 1600, "height": 1063}})
            try:
                result = await c.search_image(str(photo), 1)
                self.assertEqual(result["gallery_url"], "https://same.energy/search?i=uploaded")
                self.assertEqual(result["results"][0]["image_id"], "fresh")
                self.assertTrue(result["requires_output_directory_confirmation"])
                self.assertIn("Em qual pasta", result["output_directory_question"])
                self.assertTrue(result["visual_review_required"])
                self.assertEqual(result["results_kind"], "unreviewed_candidates")
            finally:
                await c.close()

    async def test_cdn_redirect_cannot_escape_allowlist(self):
        async def respond(request):
            return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})
        c = SameEnergy()
        await c.http.aclose()
        c.http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            with self.assertRaises(SameEnergyError):
                await c.fetch("https://blobcdn.same.energy/a/b")
        finally:
            await c.close()

    async def test_oversize_download_is_interrupted(self):
        async def respond(request):
            return httpx.Response(200, content=b"a" * 1025)
        c = SameEnergy()
        await c.http.aclose()
        c.http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            with patch("same_energy_mcp.client.MAX_BYTES", 1024), self.assertRaises(SameEnergyError):
                await c.fetch("https://blobcdn.same.energy/a/b")
        finally:
            await c.close()

    async def test_tool_schema_and_annotations(self):
        from same_energy_mcp.server import mcp
        tools = {t.name: t for t in await mcp.list_tools()}
        self.assertEqual(len(tools), 7)
        self.assertFalse(tools["same_energy_search_by_image"].annotations.readOnlyHint)
        self.assertFalse(tools["same_energy_save_image"].annotations.destructiveHint)
        limit = tools["same_energy_get_gallery"].inputSchema["properties"]["limit"]
        self.assertEqual((limit["minimum"], limit["maximum"]), (1, 50))
        self.assertIn("destination_confirmed", tools["same_energy_save_image"].inputSchema["properties"])
        self.assertIn("visual_review", tools["same_energy_save_image"].inputSchema["properties"])
        resources = await mcp.list_resources()
        self.assertIn("same-energy://preferences", [str(r.uri) for r in resources])

    async def test_missing_destination_asks_user_without_network_or_files(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
            "SAME_ENERGY_WORKSPACE": tmp, "SAME_ENERGY_HOST_WORKSPACE": ""
        }):
            c = SameEnergy()
            c.detail = AsyncMock()
            try:
                for directory in (None, tmp):
                    result = await c.save("aghP", directory)
                    self.assertTrue(result["requires_user_input"])
                    self.assertFalse(result["saved"])
                c.detail.assert_not_awaited()
                self.assertEqual(list(Path(tmp).iterdir()), [])
            finally:
                await c.close()

    async def test_confirmed_destination_creates_search_folder_and_json_subfolder(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
            "SAME_ENERGY_WORKSPACE": tmp, "SAME_ENERGY_HOST_WORKSPACE": ""
        }):
            c = SameEnergy()
            c.detail = AsyncMock(return_value={"asset": {"url": "https://blobcdn.same.energy/a/test"}})
            c.fetch = AsyncMock(return_value=jpeg())
            try:
                preview, _ = await c.preview("aghP")
                self.assertTrue(preview["visual_review_required"])
                result = await c.save("aghP", tmp, "https://same.energy/search?q=rua+noturna", destination_confirmed=True,
                                      visual_review=approved_review(jpeg()))
                directory = Path(tmp) / output_folder_name("rua noturna", c.preferences)
                self.assertTrue(result["saved"])
                self.assertEqual(Path(result["path"]).parent, directory)
                self.assertEqual(Path(result["metadata_path"]).parent, directory / "json")
                self.assertEqual(Path(result["path"]).read_bytes(), jpeg())
                self.assertFalse(list(directory.glob("*.json")))
                metadata = json.loads(Path(result["metadata_path"]).read_text())
                self.assertEqual(metadata["visual_review"]["sha256"], metadata["sha256"])
                self.assertEqual(metadata["visual_review"]["method"], "assistant_visual_inspection")
            finally:
                await c.close()

    async def test_non_photographs_markings_ai_and_uncertain_reviews_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
            "SAME_ENERGY_WORKSPACE": tmp, "SAME_ENERGY_HOST_WORKSPACE": ""
        }):
            c = SameEnergy()
            c.detail = AsyncMock()
            try:
                for key, value in [("is_photograph", False), ("has_markings", True),
                                   ("clearly_ai_generated", True), ("uncertain", True)]:
                    with self.subTest(key=key):
                        result = await c.save("a", tmp, destination_confirmed=True,
                                              visual_review={**approved_review(jpeg()), key: value})
                        self.assertTrue(result["rejected"])
                        self.assertFalse(result["saved"])
                c.detail.assert_not_awaited()
                self.assertEqual(list(Path(tmp).iterdir()), [])
            finally:
                await c.close()

    async def test_save_requires_review_and_matching_preview_of_this_image(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
            "SAME_ENERGY_WORKSPACE": tmp, "SAME_ENERGY_HOST_WORKSPACE": ""
        }):
            c = SameEnergy()
            c.detail = AsyncMock()
            try:
                review = approved_review(jpeg())
                for supplied in (None, review):
                    result = await c.save("a", tmp, destination_confirmed=True, visual_review=supplied)
                    self.assertTrue(result["requires_visual_review"])
                    self.assertFalse(result["saved"])
                c.previewed_images["other-image"] = review["sha256"]
                result = await c.save("a", tmp, destination_confirmed=True, visual_review=review)
                self.assertTrue(result["requires_visual_review"])
                c.previewed_images["a"] = "0" * 64
                result = await c.save("a", tmp, destination_confirmed=True, visual_review=review)
                self.assertTrue(result["requires_visual_review"])
                c.detail.assert_not_awaited()
                self.assertEqual(list(Path(tmp).iterdir()), [])
            finally:
                await c.close()

    async def test_changed_image_invalidates_review_and_saves_nothing(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
            "SAME_ENERGY_WORKSPACE": tmp, "SAME_ENERGY_HOST_WORKSPACE": ""
        }):
            c = SameEnergy()
            c.detail = AsyncMock(return_value={"asset": {"url": "https://blobcdn.same.energy/a/test"}})
            c.fetch = AsyncMock(side_effect=[jpeg(), jpeg((1700, 1100))])
            try:
                await c.preview("a")
                with self.assertRaisesRegex(SameEnergyError, "arquivo mudou"):
                    await c.save("a", tmp, destination_confirmed=True, visual_review=approved_review(jpeg()))
                self.assertNotIn("a", c.previewed_images)
                self.assertEqual(list(Path(tmp).iterdir()), [])
            finally:
                await c.close()

    async def test_gallery_excludes_small_thin_and_unverified_images(self):
        c = SameEnergy()
        context = MagicMock()
        page = MagicMock()
        page.close = AsyncMock()
        context.new_page = AsyncMock(return_value=page)
        sizes = {"small": (512, 341), "large": (1600, 1063), "thin": (1600, 400), "portrait": (720, 1280)}

        async def detail(_page, ident):
            if ident == "unknown":
                raise SameEnergyError("Dimensões indisponíveis")
            w, h = sizes[ident]
            return {"asset": {"width": w, "height": h}}

        c.detail_on_page = detail
        try:
            result = await c.large_results(context, [{"image_id": ident} for ident in ["small", "large", "unknown", "thin", "portrait"]], 12)
            self.assertEqual([r["image_id"] for r in result], ["large", "portrait"])
            self.assertTrue(all(r["large_image_verified"] for r in result))
        finally:
            await c.close()


if __name__ == "__main__":
    unittest.main()
