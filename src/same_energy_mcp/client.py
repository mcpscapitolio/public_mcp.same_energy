"""Use the public website's rendered UI, without private API endpoints or host cookies."""

import asyncio
import hashlib
import io
import json
import os
import re
import warnings
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import httpx
from PIL import Image, ImageDraw, ImageOps
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from playwright.async_api import Error as PlaywrightError

from .preferences import is_large, load_preferences, output_folder_name

BASE = "https://same.energy"
MAX_BYTES = 32 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 40_000_000
FORMATS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "GIF": ".gif", "BMP": ".bmp", "AVIF": ".avif"}
VISUAL_REVIEW_INSTRUCTIONS = (
    "O assistente deve examinar visualmente as candidatas antes de apresentar a seleção final. "
    "Aceitar apenas fotografias; rejeitar ilustrações, pinturas, renders, capturas de interfaces, "
    "marcas-d'água, assinaturas, anotações e logotipos sobrepostos, ou imagens claramente geradas por IA. "
    "Textos e placas que fazem parte da cena fotografada não são marcações sobrepostas. "
    "Descartar os casos duvidosos. Antes de salvar cada imagem, abrir preview_image e inspecionar "
    "a prévia individual; se faltar detalhe, não aprovar. Informar visual_review usando o SHA-256 "
    "da prévia examinada. A triagem é feita pelo assistente, não por um detector automático no servidor; "
    "aparência fotográfica não comprova a origem da imagem."
)


class SameEnergyError(ValueError):
    pass


def image_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
        raise SameEnergyError("image_id inválido; use o identificador retornado na galeria.")
    return value


def gallery_url(value: str) -> str:
    p = urlsplit(value)
    if (p.scheme != "https" or p.netloc not in {"same.energy", "www.same.energy"}
            or p.path != "/search" or p.fragment):
        raise SameEnergyError("Use uma URL https://same.energy/search retornada por uma busca.")
    query = parse_qs(p.query, keep_blank_values=True)
    if not query or set(query) - {"q", "i"} or any(len(v) != 1 or not v[0] for v in query.values()):
        raise SameEnergyError("A galeria deve conter q (texto) ou i (imagem).")
    if "i" in query:
        image_id(query["i"][0])
    if len(value) > 4096:
        raise SameEnergyError("URL muito longa.")
    return urlunsplit(("https", "same.energy", "/search", urlencode({k: v[0] for k, v in query.items()}), ""))


def asset_url(value: str, *, thumbnail: bool = False) -> str:
    p = urlsplit(value)
    if p.scheme != "https" or p.netloc != "blobcdn.same.energy" or p.fragment:
        raise SameEnergyError("O arquivo precisa vir do CDN HTTPS do Same Energy.")
    if not thumbnail and "/thumbnails/" in p.path:
        raise SameEnergyError("Miniaturas não podem ser salvas como imagem em alta resolução.")
    return value


def inspect_image(data: bytes) -> dict:
    if not data or len(data) > MAX_BYTES:
        raise SameEnergyError("Arquivo vazio ou maior que 32 MiB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as im:
                fmt, size = im.format, im.size
                im.load()
                if fmt not in FORMATS:
                    raise SameEnergyError("Formato de imagem não suportado.")
    except (OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise SameEnergyError("A resposta não é uma imagem válida e decodificável.") from exc
    return {"format": fmt, "width": size[0], "height": size[1], "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest()}


class Workspace:
    def __init__(self):
        self.root = Path(os.environ.get("SAME_ENERGY_WORKSPACE", "/workspace")).resolve()
        self.host = os.environ.get("SAME_ENERGY_HOST_WORKSPACE", "")

    def resolve(self, value: str) -> Path:
        p = Path(value)
        if not p.is_absolute():
            raise SameEnergyError("Use um caminho absoluto dentro da pasta montada no Docker.")
        if self.host and p.is_relative_to(Path(self.host)):
            p = self.root / p.relative_to(Path(self.host))
        p = p.resolve()
        if not p.is_relative_to(self.root):
            raise SameEnergyError("O caminho está fora da pasta de trabalho montada no Docker.")
        return p

    def host_path(self, p: Path) -> str:
        return str(Path(self.host) / p.relative_to(self.root)) if self.host else str(p)


def save_original(data: bytes, directory: Path, ident: str, metadata: dict, preferences: dict | None = None) -> dict:
    ident = image_id(ident)
    preferences = preferences or load_preferences()
    measured = inspect_image(data)
    if not is_large(measured["width"], measured["height"], preferences):
        raise SameEnergyError(f"Arquivo de {measured['width']} × {measured['height']}: resolução abaixo do mínimo ({preferences['minimum_long_edge']} × {preferences['minimum_short_edge']}, em qualquer orientação). Nada foi salvo.")
    directory.mkdir(parents=True, exist_ok=True)
    metadata_dir = directory / preferences["metadata_subdirectory"]
    if not metadata_dir.resolve().is_relative_to(directory.resolve()):
        raise SameEnergyError("A subpasta de JSON não pode apontar para fora da pasta da busca.")
    metadata_dir.mkdir(exist_ok=True)
    stem = f"same-energy-{ident}-{measured['sha256'][:8]}"
    for n in range(1000):
        path = directory / (stem + (f"-{n}" if n else "") + FORMATS[measured["format"]])
        sidecar = metadata_dir / (path.name + ".json")
        if path.exists() or sidecar.exists():
            continue
        try:
            with path.open("xb") as f:
                f.write(data)
        except FileExistsError:
            continue
        result = {**metadata, **measured, "image_id": ident, "path": str(path),
                  "saved_at": datetime.now(timezone.utc).isoformat(),
                  "resolution_scope": "largest asset observed in Same Energy detail view; publisher original not guaranteed"}
        try:
            with sidecar.open("x") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
                f.write("\n")
        except OSError:
            path.unlink()
            raise
        return {**result, "metadata_path": str(sidecar)}
    raise SameEnergyError("Não foi possível criar um nome de arquivo sem sobrescrever existentes.")


class SameEnergy:
    def __init__(self):
        self.workspace = Workspace()
        self.preferences = load_preferences()
        self.previewed_images = {}
        self.lock = asyncio.Lock()
        self.pw = None
        self.browser = None
        self.http = httpx.AsyncClient(timeout=30, follow_redirects=False)

    async def close(self):
        if self.browser:
            await self.browser.close()
        if self.pw:
            await self.pw.stop()
        await self.http.aclose()

    @asynccontextmanager
    async def page(self):
        async with self.lock:
            if not self.browser or not self.browser.is_connected():
                if not self.pw:
                    self.pw = await async_playwright().start()
                self.browser = await self.pw.chromium.launch(headless=True)
            context = await self.browser.new_context(viewport={"width": 1440, "height": 1000})
            page = await context.new_page()
            page.set_default_timeout(30_000)
            try:
                yield page
            finally:
                await context.close()

    async def open(self, page, url):
        response = await page.goto(url, wait_until="domcontentloaded")
        if not response or response.status >= 400:
            raise SameEnergyError("O site Same Energy não respondeu normalmente. Tente novamente mais tarde.")
        welcome = page.get_by_role("button", name="Enter", exact=True)
        try:
            await welcome.wait_for(state="visible", timeout=1000)
            await welcome.click()
        except PlaywrightTimeout:
            pass
        # A fresh image-search URL can briefly render the default home feed.
        # Wait for the website's initial requests, rather than accepting that feed.
        await page.wait_for_load_state("networkidle")

    async def fetch(self, url, *, thumbnail=False):
        url = asset_url(url, thumbnail=thumbnail)
        for _ in range(4):
            async with self.http.stream("GET", url) as response:
                if response.is_redirect:
                    url = asset_url(str(response.url.join(response.headers.get("location", ""))), thumbnail=thumbnail)
                    continue
                response.raise_for_status()
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_BYTES:
                        raise SameEnergyError("Download maior que 32 MiB; operação interrompida.")
                return bytes(data)
        raise SameEnergyError("O CDN redirecionou o download muitas vezes.")

    async def status(self):
        async with self.page() as page:
            await self.open(page, BASE)
            await page.locator('input[type="file"]').first.wait_for(state="attached")
            return {"ready": True, "site": BASE, "authentication": "anonymous",
                    "browser": "isolated Chromium in Docker", "workspace": str(self.workspace.root),
                    "host_workspace": self.workspace.host, "preferences": self.preferences,
                    "preferences_file": os.environ.get("SAME_ENERGY_PREFERENCES_FILE", "bundled preferences.json")}

    async def gallery(self, page, limit):
        if not 1 <= limit <= 50:
            raise SameEnergyError("limit deve estar entre 1 e 50.")
        try:
            await page.locator('img[sameenergyid]').first.wait_for(state="attached")
        except PlaywrightTimeout as exc:
            raise SameEnergyError("A busca não retornou imagens. O site pode estar indisponível ou ter mudado.") from exc
        rows = await page.locator('img[sameenergyid]').evaluate_all("""images => images
            .map(im => ({im, rect: im.getBoundingClientRect()}))
            .sort((a,b) => a.rect.top - b.rect.top || a.rect.left - b.rect.left)
            .map(({im}) => ({image_id: im.getAttribute('sameenergyid'),
                thumbnail_url: im.getAttribute('src')}))""")
        unique = {}
        for row in rows:
            ident = image_id(row["image_id"])
            unique.setdefault(ident, {**row, "detail_url": f"{BASE}/i/{ident}"})
        candidates = list(unique.values())[:50]
        if not candidates:
            raise SameEnergyError("A galeria está vazia.")
        results = await self.large_results(page.context, candidates, limit)
        return {"gallery_url": gallery_url(page.url), "count": len(results), "results": results,
                "preferences": self.preferences, "requires_output_directory_confirmation": True,
                "output_directory_question": "Em qual pasta devo salvar as imagens desta busca?",
                "visual_review_required": True, "results_kind": "unreviewed_candidates",
                "visual_review_instructions": VISUAL_REVIEW_INSTRUCTIONS,
                "note": "Candidatas grandes com resolução confirmada, ainda sem triagem visual. Ordem visual da galeria; prancha mostra até 12 candidatas."}

    async def large_results(self, context, candidates, limit):
        verified = []

        async def check(row):
            page = await context.new_page()
            page.set_default_timeout(12_000)
            try:
                detail = await self.detail_on_page(page, row["image_id"])
                asset = detail["asset"]
                if is_large(asset["width"], asset["height"], self.preferences):
                    return {**row, "width": asset["width"], "height": asset["height"],
                            "large_image_verified": True, "visual_review_status": "pending"}
            except (SameEnergyError, PlaywrightError):
                pass  # Unknown dimensions are excluded, never presented as large.
            finally:
                await page.close()

        # Small batches preserve order and avoid making fifty simultaneous requests.
        # An overall deadline keeps the MCP call within the client's tool timeout.
        try:
            async with asyncio.timeout(90):
                for offset in range(0, len(candidates), 3):
                    batch = await asyncio.gather(*(check(row) for row in candidates[offset:offset + 3]))
                    verified.extend(row for row in batch if row is not None)
                    if len(verified) >= limit:
                        break
        except TimeoutError:
            pass
        return verified[:limit]

    async def search_text(self, query, limit):
        if not query.strip() or len(query) > 2000:
            raise SameEnergyError("Envie uma descrição entre 1 e 2000 caracteres.")
        async with self.page() as page:
            await self.open(page, BASE + "/search?" + urlencode({"q": query.strip()}))
            return await self.gallery(page, limit)

    async def search_image(self, image_path, limit):
        path = self.workspace.resolve(image_path)
        if not path.is_file() or path.stat().st_size > 20 * 1024 * 1024:
            raise SameEnergyError("Escolha um arquivo de imagem existente de até 20 MiB na pasta montada.")
        measured = inspect_image(path.read_bytes())
        if measured["format"] not in {"JPEG", "PNG", "GIF", "BMP"}:
            raise SameEnergyError("O upload nativo aceita JPEG, PNG, GIF ou BMP.")
        async with self.page() as page:
            await self.open(page, BASE)
            await page.locator('input[type="file"]').first.wait_for(state="attached")
            # Native file input triggers the website's own upload and image search.
            await page.locator('input[type="file"]').first.set_input_files(str(path))
            try:
                await page.wait_for_url(re.compile(r"https://same\.energy/search\?.*\bi="), timeout=60_000)
            except PlaywrightTimeout as exc:
                raise SameEnergyError("O site não concluiu a busca após o upload. A galeria anterior não foi retornada.") from exc
            # The SPA replaces columns separately, briefly mixing the home feed and
            # the new results. Reopen the completed search as a fresh document.
            await self.open(page, gallery_url(page.url))
            result = await self.gallery(page, limit)
            result["uploaded_image"] = {**measured, "host_path": self.workspace.host_path(path)}
            return result

    async def get_gallery(self, url, limit):
        async with self.page() as page:
            await self.open(page, gallery_url(url))
            return await self.gallery(page, limit)

    async def detail(self, ident):
        ident = image_id(ident)
        async with self.page() as page:
            return await self.detail_on_page(page, ident)

    async def detail_on_page(self, page, ident):
        ident = image_id(ident)
        await self.open(page, f"{BASE}/i/{ident}")
        try:
            await page.wait_for_function("""() => [...document.images].some(im =>
                im.src.startsWith('https://blobcdn.same.energy/') && !im.src.includes('/thumbnails/')
                && im.complete && im.naturalWidth > 0)""")
        except PlaywrightTimeout as exc:
            raise SameEnergyError("A página não disponibilizou uma imagem maior. Nenhuma miniatura foi salva.") from exc
        assets = await page.evaluate("""() => [...document.images].filter(im =>
            im.src.startsWith('https://blobcdn.same.energy/') && !im.src.includes('/thumbnails/')
            && im.naturalWidth > 0).map(im => ({url: im.currentSrc || im.src,
            width: im.naturalWidth, height: im.naturalHeight}))""")
        largest = max(assets, key=lambda x: x["width"] * x["height"])
        title = await page.locator("h1").first.inner_text() if await page.locator("h1").count() else None
        links = await page.locator('a[href^="http"]').evaluate_all("els => els.map(a => ({text: a.textContent, url: a.href}))")
        sources = [x for x in links if urlsplit(x["url"]).hostname not in {"same.energy", "www.same.energy"}]
        return {"image_id": ident, "detail_url": page.url, "title": title, "asset": largest,
                "source_links": sources, "license_url": next((x["url"] for x in sources if urlsplit(x["url"]).hostname in {"creativecommons.org", "www.creativecommons.org"}), None)}

    async def preview(self, ident):
        detail = await self.detail(ident)
        data = await self.fetch(detail["asset"]["url"])
        measured = inspect_image(data)
        if not is_large(measured["width"], measured["height"], self.preferences):
            raise SameEnergyError("O resultado não é uma imagem grande; nenhuma prévia foi apresentada.")
        with Image.open(io.BytesIO(data)) as im:
            im = im.convert("RGB")
            im.thumbnail((1000, 800))
            out = io.BytesIO()
            im.save(out, format="JPEG", quality=85)
        self.previewed_images[image_id(ident)] = measured["sha256"]
        return {**detail, **measured, "preview_only": True, "visual_review_required": True,
                "visual_review_instructions": VISUAL_REVIEW_INSTRUCTIONS}, out.getvalue()

    async def save(self, ident, output_directory=None, from_gallery=None, search_name=None, destination_confirmed=False, visual_review=None):
        if not output_directory or not destination_confirmed:
            return {"saved": False, "requires_user_input": True,
                    "question": "Em qual pasta devo salvar as imagens desta busca?",
                    "instruction": "Pergunte ao usuário. Use destination_confirmed=true somente após ele informar ou confirmar a pasta para esta busca.",
                    "preferences": self.preferences}
        ident = image_id(ident)
        if visual_review is not None and (
            visual_review.get("is_photograph") is not True
            or visual_review.get("has_markings") is not False
            or visual_review.get("clearly_ai_generated") is not False
            or visual_review.get("uncertain") is not False
        ):
            return {"saved": False, "rejected": True,
                    "reason": "A triagem indicou imagem não fotográfica, marcações, geração clara por IA ou dúvida. Escolha outra fotografia."}
        if (visual_review is None or not self.previewed_images.get(ident)
                or visual_review.get("sha256") != self.previewed_images[ident]):
            return {"saved": False, "requires_visual_review": True,
                    "instruction": VISUAL_REVIEW_INSTRUCTIONS}
        parent = self.workspace.resolve(output_directory)
        if from_gallery:
            from_gallery = gallery_url(from_gallery)
        query = parse_qs(urlsplit(from_gallery or "").query)
        name = search_name or query.get("q", [None])[0] or "imagem-" + query.get("i", [image_id(ident)])[0][:16]
        folder = output_folder_name(name, self.preferences)
        directory = self.workspace.resolve(str(parent / folder))
        if not directory.is_relative_to(parent):
            raise SameEnergyError("A pasta da busca não pode apontar para fora da pasta escolhida.")
        detail = await self.detail(ident)
        data = await self.fetch(detail["asset"]["url"])
        if inspect_image(data)["sha256"] != visual_review["sha256"]:
            self.previewed_images.pop(ident, None)
            raise SameEnergyError("O arquivo mudou após a prévia. Abra uma nova prévia e refaça a triagem visual; nada foi salvo.")
        result = save_original(data, directory, ident, {**detail, "gallery_url": from_gallery,
                               "search_name": name, "search_directory": str(directory),
                               "visual_review": {**visual_review, "method": "assistant_visual_inspection"}}, self.preferences)
        result["saved"] = True
        result["host_path"] = self.workspace.host_path(Path(result["path"]))
        result["host_metadata_path"] = self.workspace.host_path(Path(result["metadata_path"]))
        return result

    async def contact_sheet(self, results):
        rows = results[:12]
        canvas = Image.new("RGB", (960, ((len(rows) + 2) // 3) * 230), "#17191d")
        draw = ImageDraw.Draw(canvas)
        sem = asyncio.Semaphore(4)

        async def thumb(row):
            async with sem:
                return await self.fetch(row["thumbnail_url"], thumbnail=True)

        images = await asyncio.gather(*(thumb(row) for row in rows), return_exceptions=True)
        for i, (row, data) in enumerate(zip(rows, images)):
            x, y = (i % 3) * 320, (i // 3) * 230
            if isinstance(data, bytes):
                try:
                    inspect_image(data)
                    with Image.open(io.BytesIO(data)) as im:
                        preview = ImageOps.contain(im.convert("RGB"), (308, 192))
                        canvas.paste(preview, (x + (320 - preview.width) // 2, y + 6 + (192 - preview.height) // 2))
                except (SameEnergyError, OSError):
                    draw.text((x + 12, y + 90), "Preview unavailable", fill="white")
            else:
                draw.text((x + 12, y + 90), "Preview unavailable", fill="white")
            draw.text((x + 12, y + 207), f"{i + 1} | {row['image_id']}", fill="white")
        out = io.BytesIO()
        canvas.save(out, format="JPEG", quality=82)
        return out.getvalue()
