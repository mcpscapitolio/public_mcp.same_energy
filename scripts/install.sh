#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
workspace_dir=''
client=''
usage() { echo 'Uso: bash scripts/install.sh --workspace /pasta/absoluta [--client codex|claude-code|antigravity]'; }
while [ "$#" -gt 0 ]; do
  case "$1" in
    --workspace) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; workspace_dir="$2"; shift 2 ;;
    --client) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; client="$2"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done
case "$client" in ''|codex|claude-code|antigravity) ;; *) usage >&2; exit 2 ;; esac
if [ -n "$workspace_dir" ]; then
  case "$workspace_dir" in /*) ;; *) echo 'Use uma pasta absoluta.' >&2; exit 2 ;; esac
  case "$workspace_dir" in *$'\n'*|*$'\r'*) echo 'O caminho não pode conter quebras de linha.' >&2; exit 2 ;; esac
elif [ ! -f "$repo_dir/.env" ]; then
  usage >&2
  exit 2
fi
command -v docker >/dev/null || { echo 'Instale e inicie o Docker com Compose.' >&2; exit 2; }
docker_bin="$(command -v docker)"
"$docker_bin" compose version >/dev/null
"$docker_bin" info >/dev/null
unset SAME_ENERGY_WORKSPACE_DIR
umask 077
if [ -n "$workspace_dir" ]; then
  mkdir -p -- "$workspace_dir"
  workspace_dir="$(CDPATH= cd -- "$workspace_dir" && pwd -P)"
  escaped_apostrophe="\\'"
  escaped_workspace="${workspace_dir//\'/$escaped_apostrophe}"
  env_line="SAME_ENERGY_WORKSPACE_DIR='$escaped_workspace'"
  if [ -e "$repo_dir/.env" ]; then
    if ! grep -Fxq -- "$env_line" "$repo_dir/.env"; then
      echo 'O .env existente foi preservado. Revise SAME_ENERGY_WORKSPACE_DIR e execute sem --workspace para reutilizá-lo.' >&2
      exit 2
    fi
  else
    printf '%s\n' "$env_line" > "$repo_dir/.env"
  fi
fi
compose() { "$docker_bin" compose --project-directory "$repo_dir" --env-file "$repo_dir/.env" "$@"; }
compose config --quiet
"$docker_bin" build --target test -t same-energy-public-mcp:test "$repo_dir"
compose build
compose up -d same-energy
compose exec -T -e SAME_ENERGY_INSTALL_DIRECTORY="$repo_dir" -e SAME_ENERGY_DOCKER_COMMAND="$docker_bin" same-energy python -c 'import json,os; print(json.dumps({"mcpServers":{"same-energy-public":{"command":os.environ["SAME_ENERGY_DOCKER_COMMAND"],"args":["compose","--project-directory",os.environ["SAME_ENERGY_INSTALL_DIRECTORY"],"exec","-T","same-energy","same-energy-mcp"]}}},ensure_ascii=False,indent=2))' > "$repo_dir/mcp.public.local.json"
compose exec -T same-energy python /app/verify_install.py
if [ -n "$client" ]; then bash "$repo_dir/scripts/register-client.sh" "$client"; fi
echo "Instalação verificada. Configuração genérica: $repo_dir/mcp.public.local.json"
echo 'No agente, pergunte: como funciona o mcp SAME-ENERGY?'
