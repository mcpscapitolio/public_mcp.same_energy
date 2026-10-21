"""Anonymous GitHub checks and consent-bound host update plans; no Docker socket."""
import argparse
import asyncio
import json
import os
import re
import shlex
import sys
import tempfile
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path

import httpx

from . import __version__

REPOSITORY = "mcpscapitolio/public_mcp.same_energy"
GIT_URL = f"https://github.com/{REPOSITORY}.git"
QUESTION = "Tem atualização, posso instalar?"
SHA_PATTERN = r"[0-9a-f]{40}"


def version_tuple(value: str) -> tuple[int, ...]:
    if not isinstance(value, str) or not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", value):
        raise ValueError("Versão inválida.")
    return tuple(map(int, value.split(".")))


def validate_release(value: dict) -> dict:
    version_tuple(value["version"])
    changes = value["changes"]
    if (not isinstance(changes, list) or not 1 <= len(changes) <= 50
            or any(not isinstance(item, str) or not item.strip() or len(item) > 1000 for item in changes)):
        raise ValueError("Notas de atualização inválidas.")
    return {"version": value["version"], "changes": changes}


def bundled_release() -> dict:
    return validate_release(json.loads(files("same_energy_mcp").joinpath("release.json").read_text(encoding="utf-8")))


def history_path() -> Path:
    return Path(os.environ.get("SAME_ENERGY_PREFERENCES_FILE", "/data/preferences.json")).with_name("last_update.json")


def installed_notes() -> dict:
    path = history_path()
    if path.is_file():
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            release = validate_release(record)
            if release["version"] == __version__:
                return {**record, **release, "source": "last_successful_update"}
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return {**bundled_release(), "source": "installed_release", "updated_at": None}


def record_update(from_version: str, target_sha: str, release: dict) -> dict:
    version_tuple(from_version)
    release = validate_release(release)
    if not re.fullmatch(SHA_PATTERN, target_sha) or release != bundled_release() or release["version"] != __version__:
        raise ValueError("O registro não corresponde à versão instalada.")
    record = {**release, "from_version": from_version, "target_sha": target_sha,
              "updated_at": datetime.now(timezone.utc).isoformat()}
    path = history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False, encoding="utf-8") as f:
        temporary = Path(f.name)
        json.dump(record, f, ensure_ascii=False, indent=2)
        f.write("\n")
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return record


def startup_notice(result: dict) -> str:
    if result.get("update_available"):
        return (f"CONSULTA INICIAL GITHUB: instalada {result['installed_version']}; disponível {result['available_version']}. "
                f"Na primeira resposta desta conexão, diga exatamente: {QUESTION} "
                "Só prepare e execute a atualização se o usuário concordar explicitamente com essa versão. "
                "Se recusar, continue a versão atual sem insistir. Se perguntar o que mudou, use same_energy_update_notes(target='available').")
    if result.get("status") == "up_to_date":
        return "CONSULTA INICIAL GITHUB: não há versão mais recente. Nenhuma instalação foi realizada."
    return "CONSULTA INICIAL GITHUB: consulta indisponível; continue usando a versão instalada. Não afirme que ela está atualizada."


class UpdateChecker:
    def __init__(self, installed_version: str = __version__, transport=None):
        version_tuple(installed_version)
        self.installed_version = installed_version
        self.transport = transport
        self.latest = {"status": "not_checked", "installed_version": installed_version, "update_available": False}

    async def check(self) -> dict:
        try:
            async with asyncio.timeout(8):
                async with httpx.AsyncClient(timeout=3, follow_redirects=False, trust_env=False,
                                             transport=self.transport, headers={"User-Agent": f"same-energy-mcp/{__version__}"}) as http:
                    ref = await http.get(f"https://api.github.com/repos/{REPOSITORY}/git/ref/heads/main")
                    ref.raise_for_status()
                    if len(ref.content) > 65536:
                        raise ValueError("Resposta muito grande.")
                    sha = ref.json()["object"]["sha"]
                    if not isinstance(sha, str) or not re.fullmatch(SHA_PATTERN, sha):
                        raise ValueError("Commit inválido.")
                    response = await http.get(f"https://raw.githubusercontent.com/{REPOSITORY}/{sha}/src/same_energy_mcp/release.json")
                    response.raise_for_status()
                    if len(response.content) > 65536:
                        raise ValueError("Resposta muito grande.")
                    release = validate_release(response.json())
            available = version_tuple(release["version"]) > version_tuple(self.installed_version)
            self.latest = {"status": "update_available" if available else "up_to_date",
                           "installed_version": self.installed_version, "available_version": release["version"],
                           "update_available": available, "target_sha": sha, "changes": release["changes"],
                           "question": QUESTION if available else None, "repository": f"https://github.com/{REPOSITORY}",
                           "checked_at": datetime.now(timezone.utc).isoformat()}
        except (httpx.HTTPError, TimeoutError, ValueError, KeyError, TypeError):
            self.latest = {"status": "unavailable", "installed_version": self.installed_version,
                           "update_available": False, "message": "Não foi possível consultar o GitHub. Nada foi instalado; a versão atual continua disponível."}
        return self.latest

    async def prepare(self, approved: bool = False, target_sha: str | None = None) -> dict:
        if self.latest["status"] == "not_checked":
            await self.check()
        if not self.latest.get("update_available"):
            return {"ready_to_install": False, "requires_user_approval": False, "update": self.latest}
        if approved is not True or target_sha != self.latest["target_sha"]:
            return {"ready_to_install": False, "requires_user_approval": True, "question": QUESTION, "update": self.latest}
        directory = os.environ.get("SAME_ENERGY_INSTALL_DIRECTORY", "")
        if not directory or not Path(directory).is_absolute() or "\n" in directory or "\r" in directory:
            return {"ready_to_install": False, "requires_install_directory": True,
                    "message": "Configure SAME_ENERGY_INSTALL_DIRECTORY no .env com a pasta absoluta do checkout e recrie o serviço."}
        args = ["bash", str(Path(directory) / "scripts/update.sh"), "--approved", "--target-sha", target_sha]
        return {"ready_to_install": True, "installed": False, "target_sha": target_sha,
                "version": self.latest["available_version"], "changes": self.latest["changes"],
                "command": shlex.join(args),
                "instruction": "O usuário deve ter concordado explicitamente. Execute este comando no host pelo terminal do agente; só informe instalação concluída após sucesso. Depois reconecte o MCP. Não execute dentro do container nem monte o socket Docker."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["record"])
    parser.add_argument("--from-version", required=True)
    parser.add_argument("--target-sha", required=True)
    args = parser.parse_args()
    record_update(args.from_version, args.target_sha, json.load(sys.stdin))
    print(json.dumps({"recorded": True, "version": __version__}))
