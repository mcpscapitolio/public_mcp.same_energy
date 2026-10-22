import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

import httpx
from PIL import Image
from playwright.sync_api import sync_playwright, expect

from same_energy_mcp.catalog import CatalogError, CatalogStore, MARKER, make_server, render_catalog
from same_energy_mcp.preferences import load_preferences


def photo(path, color='#637259'):
    image = Image.new('RGB', (1400, 900), color)
    image.save(path, format='JPEG')
    return path.read_bytes()


class CatalogFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {
            'SAME_ENERGY_WORKSPACE': str(self.root),
            'SAME_ENERGY_CATALOG_REGISTRY': str(self.root / 'internal/catalogs.json'),
            'SAME_ENERGY_PREFERENCES_FILE': str(self.root / 'internal/preferences.json'),
        })
        self.env.start()
        self.store = CatalogStore()
        self.folder = self.root / 'output_teste'
        self.folder.mkdir()
        self.before = photo(self.folder / 'água #1.jpg')
        photo(self.folder / 'outra.jpg')
        (self.folder / 'json').mkdir()
        self.sidecar = self.folder / 'json/água #1.jpg.json'
        self.sidecar.write_text('{"source": "fixture"}')

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()


class CatalogTests(CatalogFixture):
    def test_template_reused_registry_survives_restart_and_filename_is_safe(self):
        first = self.store.register(self.folder, 'Água </script><img src=x>')
        second = CatalogStore().register(self.folder)
        self.assertEqual(first['url'], second['url'])
        html = Path(first['path']).read_text()
        self.assertIn(MARKER, html)
        self.assertNotIn('__CATALOG_CONFIG__', html)
        self.assertIn('Visualizar apenas marcadas', html)
        self.assertIn('\\u003c/script>', render_catalog({'title': '</script>'}))
        self.assertEqual(len(self.store.read()), 1)
        self.assertFalse((self.folder / 'selecionadas').exists())
        (self.folder / 'catalogo.html').write_text('user document')
        with self.assertRaises(CatalogError):
            self.store.register(self.folder)
        self.assertEqual((self.folder / 'catalogo.html').read_text(), 'user document')

    def test_move_is_physical_preserves_bytes_and_json_and_main_excludes_selected(self):
        result = self.store.move(self.folder, ['água #1.jpg'])
        self.assertEqual(result['moved'], ['água #1.jpg'])
        self.assertFalse((self.folder / 'água #1.jpg').exists())
        self.assertEqual((self.folder / 'selecionadas/água #1.jpg').read_bytes(), self.before)
        self.assertEqual(self.sidecar.read_text(), '{"source": "fixture"}')
        self.assertEqual([x['name'] for x in self.store.scan(self.folder, 'available')], ['outra.jpg'])
        self.assertEqual([x['name'] for x in self.store.scan(self.folder, 'selected')], ['água #1.jpg'])
        self.store.move(self.folder, ['outra.jpg'])
        self.assertEqual(len(self.store.scan(self.folder, 'selected')), 2)
        self.assertEqual(self.store.scan(self.folder, 'available'), [])

    def test_collision_never_overwrites_existing_or_loses_source(self):
        selected = self.folder / 'selecionadas'
        selected.mkdir()
        original = photo(selected / 'outra.jpg', '#cb9962')
        result = self.store.move(self.folder, ['outra.jpg', 'água #1.jpg'])
        self.assertEqual(result['moved'], ['água #1.jpg'])
        self.assertEqual(len(result['errors']), 1)
        self.assertEqual((selected / 'outra.jpg').read_bytes(), original)
        self.assertTrue((self.folder / 'outra.jpg').exists())

    def test_escape_invalid_batch_and_symbolic_links_are_rejected_before_any_move(self):
        outside = self.root / 'external'
        outside.mkdir()
        for names in [['água #1.jpg', '../outra.jpg'], ['água #1.jpg', 'missing.jpg'], ['outra.jpg', 'outra.jpg'], ['json/a.json'], ['selecionadas/outra.jpg'], [], 'outra.jpg', [3], ['a\\b.jpg']]:
            with self.subTest(names=names), self.assertRaises(CatalogError):
                self.store.move(self.folder, names)
            self.assertTrue((self.folder / 'água #1.jpg').exists())
        (self.folder / 'link.jpg').symlink_to(self.folder / 'outra.jpg')
        with self.assertRaises(CatalogError):
            self.store.move(self.folder, ['link.jpg'])
        self.assertNotIn('link.jpg', [x['name'] for x in self.store.scan(self.folder, 'available')])
        (self.folder / 'selecionadas').symlink_to(outside)
        with self.assertRaises(CatalogError):
            self.store.move(self.folder, ['outra.jpg'])
        self.assertFalse(list(outside.iterdir()))
        with self.assertRaises(CatalogError):
            self.store.register('/etc')
        linked = self.root / 'linked'
        linked.symlink_to(self.folder)
        with self.assertRaises(CatalogError):
            self.store.register(linked)

    def test_schema2_preferences_gain_catalog_without_resetting_settings(self):
        old = load_preferences()
        old.update(schema_version=2, minimum_long_edge=1920)
        old.pop('catalog_after_save')
        self.store.registry.with_name('preferences.json').write_text(json.dumps(old))
        prefs = load_preferences()
        self.assertEqual(prefs['schema_version'], 3)
        self.assertTrue(prefs['catalog_after_save'])
        self.assertEqual(prefs['minimum_long_edge'], 1920)


class CatalogHTTPTests(CatalogFixture):
    def setUp(self):
        super().setUp()
        self.server = make_server(('127.0.0.1', 0))
        self.port = self.server.server_port
        self.server.public_port = self.port
        self.port_env = patch.dict(os.environ, {'SAME_ENERGY_CATALOG_PORT': str(self.port)})
        self.port_env.start()
        self.catalog = self.store.register(self.folder, 'Referências de água')
        self.url = self.catalog['url']
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.http = httpx.Client(timeout=5, trust_env=False)

    def tearDown(self):
        self.http.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.port_env.stop()
        super().tearDown()

    def test_http_requires_capability_origin_and_local_host(self):
        response = self.http.get(self.url + 'api')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['available']), 2)
        self.assertIn("frame-ancestors 'none'", response.headers['Content-Security-Policy'])
        self.assertEqual(response.headers['Referrer-Policy'], 'no-referrer')
        wrong = self.url.replace(urlsplit(self.url).path.split('/')[3], '0' * 48)
        self.assertNotEqual(self.http.get(wrong + 'api').status_code, 200)
        self.assertEqual(self.http.get(self.url + 'api', headers={'Host': 'evil.example'}).status_code, 403)
        for headers in [{}, {'Origin': 'https://evil.example', 'X-Catalog-Action': 'move'}]:
            self.assertEqual(self.http.post(self.url + 'move', headers=headers, json={'names': ['outra.jpg']}).status_code, 403)
        self.assertTrue((self.folder / 'outra.jpg').exists())
        self.assertFalse((self.folder / 'selecionadas').exists())
        self.assertEqual(self.http.get(self.url + 'image/available/..%2F..%2Fetc%2Fpasswd').status_code, 400)
        response = self.http.post(self.url + 'move', headers={'Origin': f'http://127.0.0.1:{self.port}', 'X-Catalog-Action': 'move'}, json={'names': ['água #1.jpg']})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['moved'], ['água #1.jpg'])
        self.assertEqual(len(response.json()['catalog']['available']), 1)
        self.assertEqual(len(response.json()['catalog']['selected']), 1)
        self.assertEqual(self.http.get(self.url + 'image/selected/%C3%A1gua%20%231.jpg').content, self.before)

    def test_browser_selection_filter_move_reload_append_and_mobile_fixed_button(self):
        for index in range(14):
            photo(self.folder / f'fixture-{index:02}.jpg')
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(viewport={'width': 1440, 'height': 900})
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(self.url)
            page.get_by_role('heading', name='Referências de água').wait_for()
            self.assertEqual(page.locator('.card').count(), 16)
            page.get_by_role('checkbox', name='Marcar água #1.jpg', exact=True).check()
            page.get_by_role('checkbox', name='Marcar outra.jpg', exact=True).check()
            page.get_by_role('checkbox', name='Visualizar apenas marcadas').check()
            self.assertEqual(page.locator('.card').count(), 2)
            page.reload()
            page.get_by_role('heading', name='Referências de água').wait_for()
            self.assertTrue(page.get_by_role('checkbox', name='Marcar água #1.jpg', exact=True).is_checked())
            page.get_by_role('checkbox', name='Visualizar apenas marcadas').check()
            page.get_by_role('button', name='Ampliar água #1.jpg').click()
            self.assertTrue(page.locator('#viewer').evaluate('(el)=>el.open'))
            page.keyboard.press('Escape')
            page.get_by_role('button', name='Mover seleção (2)').click()
            expect(page.locator("#selected-count")).to_have_text("2")
            self.assertEqual(page.locator('.card').count(), 0)
            page.get_by_role('tab', name='Selecionadas').click()
            self.assertEqual(page.locator('.card').count(), 2)
            self.assertEqual(page.locator('.card input[type=checkbox]').count(), 0)
            page.get_by_role('tab', name='Catálogo').click()
            page.get_by_role('checkbox', name='Visualizar apenas marcadas').uncheck()
            self.assertEqual(page.locator('.card').count(), 14)
            page.get_by_role('checkbox', name='Marcar fixture-00.jpg', exact=True).check()
            page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            button = page.locator('#move')
            box = button.bounding_box()
            self.assertLessEqual(box['y'] + box['height'], 900)
            self.assertTrue(button.is_enabled())
            button.click()
            expect(page.locator("#selected-count")).to_have_text("3")
            self.assertEqual(len(self.store.scan(self.folder, 'available')), 13)
            self.assertEqual(len(self.store.scan(self.folder, 'selected')), 3)
            launcher = context.new_page()
            launcher.goto(Path(self.catalog['path']).as_uri())
            launcher.wait_for_url(self.url)
            mobile = browser.new_page(viewport={'width': 390, 'height': 844})
            mobile.goto(self.url)
            mobile.get_by_role('heading', name='Referências de água').wait_for()
            mobile.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            self.assertLessEqual(mobile.locator('#move').bounding_box()['y'] + mobile.locator('#move').bounding_box()['height'], 844)
            self.assertTrue(mobile.evaluate('document.documentElement.scrollWidth<=innerWidth'))
            self.assertEqual(errors, [])
            browser.close()
