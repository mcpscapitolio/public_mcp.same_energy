"""User defaults live in a Docker volume, seeded from the versioned JSON."""

import json
import os
import re
import tempfile
import unicodedata
from datetime import datetime
from importlib.resources import files
from pathlib import Path
from zoneinfo import ZoneInfo


def load_preferences() -> dict:
    defaults = files("same_energy_mcp").joinpath("preferences.json").read_text()
    location = os.environ.get("SAME_ENERGY_PREFERENCES_FILE")
    if location:
        path = Path(location)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as f:
                temporary = Path(f.name)
                f.write(defaults)
            try:
                os.link(temporary, path)  # Atomic, without overwriting an existing user file.
            except FileExistsError:
                pass
            finally:
                temporary.unlink()
        data = json.loads(path.read_text())
        if data.get("schema_version", 1) == 1:
            # Add the newly requested rule without resetting the user's settings.
            current_defaults = json.loads(defaults)
            for key in ("photographs_only", "reject_markings", "reject_clearly_ai_generated", "require_visual_review_before_save"):
                data.setdefault(key, current_defaults[key])
            data["schema_version"] = 2
            with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as f:
                temporary = Path(f.name)
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.write("\n")
            try:
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
    else:
        data = json.loads(defaults)
    for key in ("minimum_long_edge", "minimum_short_edge"):
        if type(data.get(key)) is not int or data[key] < 1:
            raise ValueError(f"Preferência inválida: {key}")
    subdir = data.get("metadata_subdirectory", "")
    if not subdir or subdir in {".", ".."} or not re.fullmatch(r"[a-zA-Z0-9_-]+", subdir):
        raise ValueError("metadata_subdirectory deve ser o nome de uma subpasta.")
    ZoneInfo(data["timezone"])
    return data


def is_large(width: int, height: int, preferences: dict) -> bool:
    return (max(width, height) >= preferences["minimum_long_edge"]
            and min(width, height) >= preferences["minimum_short_edge"])


def output_folder_name(search_name: str, preferences: dict, now: datetime | None = None) -> str:
    name = unicodedata.normalize("NFKD", search_name).encode("ascii", "ignore").decode().lower()
    name = re.sub(r"[^a-z0-9]+", "-", name).strip("-")[:80].rstrip("-")
    if not name:
        raise ValueError("Informe um nome válido para a busca.")
    current = now or datetime.now(ZoneInfo(preferences["timezone"]))
    date = current.astimezone(ZoneInfo(preferences["timezone"])).strftime(preferences["date_format"])
    folder = preferences["output_folder_template"].format(date=date, search_name=name)
    if Path(folder).name != folder or folder in {".", ".."}:
        raise ValueError("O modelo da pasta deve produzir uma única subpasta.")
    return folder
