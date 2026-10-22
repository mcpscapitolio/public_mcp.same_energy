"""Reusable local contact sheet; capability URLs only expose registered search folders."""

import fcntl
import hmac
import io
import json
import os
import re
import secrets
import tempfile
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen

from PIL import Image, ImageOps

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif"}
MAX_IMAGE_BYTES = 32 * 1024 * 1024
MARKER = "<!-- same-energy-catalog:v1 -->"


class CatalogError(ValueError):
    pass


def catalog_port():
    port = int(os.environ.get("SAME_ENERGY_CATALOG_PORT", "8765"))
    if not 1024 <= port <= 65535:
        raise CatalogError("SAME_ENERGY_CATALOG_PORT deve estar entre 1024 e 65535.")
    return port


class CatalogStore:
    def __init__(self):
        self.root = Path(os.environ.get("SAME_ENERGY_WORKSPACE", "/workspace")).resolve()
        preferences = Path(os.environ.get("SAME_ENERGY_PREFERENCES_FILE", "/data/preferences.json"))
        self.registry = Path(os.environ.get("SAME_ENERGY_CATALOG_REGISTRY", str(preferences.with_name("catalogs.json"))))

    @contextmanager
    def locked(self):
        self.registry.parent.mkdir(parents=True, exist_ok=True)
        with self.registry.with_suffix(".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def read(self):
        return json.loads(self.registry.read_text()) if self.registry.exists() else {}

    def write(self, entries):
        with tempfile.NamedTemporaryFile(mode="w", dir=self.registry.parent, delete=False) as f:
            temporary = Path(f.name)
            json.dump(entries, f, ensure_ascii=False)
        try:
            os.replace(temporary, self.registry)
        finally:
            temporary.unlink(missing_ok=True)

    def directory(self, value):
        path = Path(value)
        if not path.is_absolute() or not path.is_relative_to(self.root):
            raise CatalogError("A pasta do catálogo precisa estar dentro da pasta compartilhada.")
        # Reject symlinks even when they currently resolve inside the workspace.
        current = self.root
        for part in path.relative_to(self.root).parts:
            if part in {".", ".."}:
                raise CatalogError("Pasta inválida.")
            current /= part
            if current.is_symlink():
                raise CatalogError("O catálogo não aceita pastas com links simbólicos.")
        if not path.resolve().is_relative_to(self.root) or not path.is_dir():
            raise CatalogError("A pasta do catálogo não existe na pasta compartilhada.")
        return path

    def register(self, directory, title=None):
        directory = self.directory(directory)
        path = directory / "catalogo.html"
        if path.is_symlink() or (path.exists() and MARKER not in path.read_text(encoding="utf-8")):
            raise CatalogError("Já existe um catalogo.html que não pertence ao MCP; ele foi preservado.")
        relative = str(directory.relative_to(self.root))
        with self.locked():
            entries = self.read()
            ident = next((key for key, item in entries.items() if item["directory"] == relative), secrets.token_hex(16))
            entry = entries.get(ident, {"directory": relative, "token": secrets.token_hex(24)})
            if title or "title" not in entry:
                entry["title"] = (title or directory.name)[:240]
            entries[ident] = entry
            self.write(entries)
        url = f"http://127.0.0.1:{catalog_port()}/catalog/{ident}/{entry['token']}/"
        # The same packaged model is used for every search, without generated code.
        html = render_catalog({"url": url, "id": ident})
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, delete=False) as f:
            temporary = Path(f.name)
            f.write(html)
        try:
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return {"url": url, "path": str(path), "directory": str(directory),
                "selected_directory": str(directory / "selecionadas"),
                "requires_running_docker": True}

    def get(self, ident, token):
        entry = self.read().get(ident)
        if not entry or not hmac.compare_digest(entry["token"], token):
            raise CatalogError("Catálogo não encontrado.")
        return entry, self.directory(self.root / entry["directory"])

    def bucket(self, directory, group):
        if group == "available":
            return self.directory(directory)
        if group != "selected":
            raise CatalogError("Aba inválida.")
        path = directory / "selecionadas"
        if path.is_symlink():
            raise CatalogError("A pasta selecionadas não pode ser um link simbólico.")
        return self.directory(path) if path.exists() else path

    def image_path(self, directory, group, name):
        if not isinstance(name, str) or not name or Path(name).name != name or "\\" in name or name in {".", ".."}:
            raise CatalogError("Nome de imagem inválido.")
        path = self.bucket(directory, group) / name
        if path.suffix.lower() not in IMAGE_EXTENSIONS or path.is_symlink() or not path.is_file():
            raise CatalogError("Imagem indisponível.")
        if path.stat().st_size > MAX_IMAGE_BYTES:
            raise CatalogError("Imagem maior que 32 MiB.")
        return path

    def scan(self, directory, group):
        folder = self.bucket(directory, group)
        rows = []
        if not folder.exists():
            return rows
        # Deliberately nonrecursive: selected images never reenter the main selector.
        for path in sorted(folder.iterdir(), key=lambda p: p.name.casefold()):
            if path.suffix.lower() not in IMAGE_EXTENSIONS or path.is_symlink() or not path.is_file():
                continue
            try:
                path = self.image_path(directory, group, path.name)
                stat = path.stat()
                with Image.open(path) as im:
                    width, height = im.size
                rows.append({"name": path.name, "width": width, "height": height,
                             "bytes": stat.st_size, "revision": str(stat.st_mtime_ns)})
            except (OSError, ValueError, Image.DecompressionBombError):
                continue
        return rows

    def snapshot(self, entry, directory):
        return {"title": entry["title"], "folder": directory.name,
                "available": self.scan(directory, "available"),
                "selected": self.scan(directory, "selected")}

    def move(self, directory, names):
        if (not isinstance(names, list) or not names or len(names) > 1000
                or any(not isinstance(n, str) for n in names) or len(set(names)) != len(names)):
            raise CatalogError("Marque de 1 a 1000 imagens diferentes.")
        moved, errors = [], []
        with self.locked():
            # Validate the complete request before moving anything.
            sources = [self.image_path(directory, "available", name) for name in names]
            selected = self.bucket(directory, "selected")
            selected.mkdir(exist_ok=True)
            for source in sources:
                destination = selected / source.name
                try:
                    # Same filesystem: atomic no-overwrite creation, preserving original bytes.
                    os.link(source, destination, follow_symlinks=False)
                    try:
                        source.unlink()
                    except OSError:
                        destination.unlink()
                        raise
                    moved.append(source.name)
                except OSError:
                    errors.append({"name": source.name, "message": "Não foi movida; verifique se o nome já existe ou se a pasta permite escrita."})
        return {"moved": moved, "errors": errors}


def render_catalog(config):
    template = files("same_energy_mcp").joinpath("catalog.html").read_text(encoding="utf-8")
    payload = json.dumps(config, ensure_ascii=False).replace("<", "\\u003c")
    return template.replace("__CATALOG_CONFIG__", payload)


class CatalogHandler(BaseHTTPRequestHandler):
    server_version = "SameEnergyCatalog"

    def log_message(self, *_args):
        pass  # Capability URLs and local filenames must not appear in logs.

    def send(self, status, body, content_type="application/json; charset=utf-8"):
        if isinstance(body, dict):
            body = json.dumps(body, ensure_ascii=False).encode()
        if isinstance(body, str):
            body = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(body)

    def route(self, post=False):
        host = self.headers.get("Host", "")
        if host not in {f"127.0.0.1:{self.server.public_port}", f"localhost:{self.server.public_port}"}:
            self.send(403, {"error": "Host inválido."})
            return
        if post and (self.headers.get("Origin") != f"http://{host}"
                     or self.headers.get("X-Catalog-Action") != "move"
                     or self.headers.get("Content-Type", "").split(";")[0] != "application/json"):
            self.send(403, {"error": "Abra o catálogo local para mover imagens."})
            return
        if not post and self.path == "/health":
            self.send(200, {"ready": True})
            return
        match = re.fullmatch(r"/catalog/([a-f0-9]{32})/([a-f0-9]{48})/(.*)", urlsplit(self.path).path)
        if not match:
            self.send(404, {"error": "Catálogo não encontrado."})
            return
        ident, token, action = match.groups()
        store = self.server.store
        try:
            entry, directory = store.get(ident, token)
            if post:
                if action != "move":
                    self.send(404, {"error": "Ação indisponível."})
                    return
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 65536:
                    raise CatalogError("Seleção inválida ou muito grande.")
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise CatalogError("Seleção inválida.")
                result = store.move(directory, data.get("names"))
                self.send(200, {**result, "catalog": store.snapshot(entry, directory)})
            elif action == "":
                self.send(200, render_catalog({"url": f"http://{host}/catalog/{ident}/{token}/", "id": ident}), "text/html; charset=utf-8")
            elif action == "api":
                self.send(200, store.snapshot(entry, directory))
            else:
                asset = re.fullmatch(r"(image|thumb)/(available|selected)/(.+)", action)
                if not asset:
                    self.send(404, {"error": "Arquivo indisponível."})
                    return
                kind, group, name = asset.groups()
                path = store.image_path(directory, group, unquote(name))
                if kind == "thumb":
                    with Image.open(path) as im:
                        preview = ImageOps.exif_transpose(im).convert("RGB")
                        preview.thumbnail((640, 640))
                        out = io.BytesIO()
                        preview.save(out, format="JPEG", quality=85)
                    self.send(200, out.getvalue(), "image/jpeg")
                else:
                    with Image.open(path) as im:
                        mime = Image.MIME.get(im.format, "application/octet-stream")
                    self.send(200, path.read_bytes(), mime)
        except (CatalogError, ValueError, OSError, Image.DecompressionBombError):
            self.send(400, {"error": "Não foi possível concluir. Atualize o catálogo e confira os arquivos da pasta."})

    def do_GET(self):
        self.route()

    def do_POST(self):
        self.route(post=True)


def make_server(address=("0.0.0.0", 8765), public_port=None):
    server = ThreadingHTTPServer(address, CatalogHandler)
    server.daemon_threads = True
    server.store = CatalogStore()
    server.public_port = public_port or catalog_port()
    return server


def healthcheck():
    request = Request("http://127.0.0.1:8765/health", headers={"Host": f"127.0.0.1:{catalog_port()}"})
    with urlopen(request, timeout=3) as response:
        assert json.load(response)["ready"]


def main():
    with make_server() as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
