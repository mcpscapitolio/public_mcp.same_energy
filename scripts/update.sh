#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
approved=false
target_sha=''
while [ "$#" -gt 0 ]; do
  case "$1" in
    --approved) approved=true; shift ;;
    --target-sha) [ "$#" -ge 2 ] || exit 2; target_sha="$2"; shift 2 ;;
    *) echo 'Use o plano retornado por same_energy_prepare_update após a concordância do usuário.' >&2; exit 2 ;;
  esac
done
if [ "$approved" != true ]; then
  echo 'Tem atualização, posso instalar?'
  exit 2
fi
if ! [[ "$target_sha" =~ ^[0-9a-f]{40}$ ]]; then
  echo 'Informe o commit exato apresentado ao usuário; nada foi instalado.' >&2
  exit 2
fi
command -v git >/dev/null
command -v docker >/dev/null
cd -- "$repo_dir"
if [ ! -d .git ] || [ "$(git branch --show-current)" != main ]; then
  echo 'A atualização requer um clone Git na branch main; nada foi alterado.' >&2
  exit 2
fi
if [ -n "$(git status --porcelain)" ]; then
  echo 'Há mudanças locais. Preserve-as e resolva o checkout antes de atualizar; nada foi sobrescrito.' >&2
  exit 2
fi
if [ "$(git remote get-url origin)" != 'https://github.com/mcpscapitolio/public_mcp.same_energy.git' ]; then
  echo 'Origem diferente do repositório público esperado; atualização interrompida.' >&2
  exit 2
fi
unset SAME_ENERGY_WORKSPACE_DIR SAME_ENERGY_INSTALL_DIRECTORY
docker_bin="$(command -v docker)"
compose() { "$docker_bin" compose --project-directory "$repo_dir" --env-file "$repo_dir/.env" "$@"; }
old_version="$(compose exec -T same-energy python -c 'from same_energy_mcp import __version__; print(__version__)')"
starting_sha="$(git rev-parse HEAD)"
export GIT_TERMINAL_PROMPT=0
git -c credential.helper= -c http.extraheader= -c core.askPass=false fetch --no-tags origin "$target_sha"
git merge-base --is-ancestor HEAD "$target_sha" || { echo 'A atualização não é um avanço do checkout atual; interrompida.' >&2; exit 2; }
stage_dir="$(mktemp -d "${TMPDIR:-/tmp}/same-energy-update.XXXXXX")"
trap 'rm -rf -- "$stage_dir"' EXIT
git archive "$target_sha" | tar -x -C "$stage_dir"
"$docker_bin" build --target test -t same-energy-public-mcp:update-test "$stage_dir"
# Recheck before the only checkout mutation, in case it changed while tests ran.
if [ -n "$(git status --porcelain)" ] || [ "$(git rev-parse HEAD)" != "$starting_sha" ] || [ "$(git branch --show-current)" != main ]; then
  echo 'O checkout mudou durante a validação; atualização interrompida sem sobrescrever arquivos.' >&2
  exit 2
fi
git merge --ff-only "$target_sha"
bash "$repo_dir/scripts/install.sh"
compose exec -T same-energy python -m same_energy_mcp.updates record --from-version "$old_version" --target-sha "$target_sha" < "$repo_dir/src/same_energy_mcp/release.json"
echo 'Atualização concluída. Reconecte o MCP; a lista das mudanças está disponível em same_energy_update_notes.'
