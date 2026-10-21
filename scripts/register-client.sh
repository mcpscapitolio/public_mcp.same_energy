#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
client="${1:-}"
docker_bin="$(command -v docker)"
unset SAME_ENERGY_WORKSPACE_DIR SAME_ENERGY_INSTALL_DIRECTORY
compose() { "$docker_bin" compose --project-directory "$repo_dir" --env-file "$repo_dir/.env" "$@"; }

case "$client" in
  codex) client_config="${CODEX_HOME:-$HOME/.codex}/config.toml" ;;
  antigravity) client_config="$HOME/.gemini/config/mcp_config.json" ;;
  claude-code)
    command -v claude >/dev/null || { echo 'Instale o Claude Code e disponibilize o comando claude.' >&2; exit 2; }
    if claude mcp get same-energy-public >/dev/null 2>&1; then
      echo 'A entrada same-energy-public já existe no Claude Code; preservada. Verifique com claude mcp get same-energy-public.'
      exit 0
    fi
    claude mcp add --transport stdio --scope user same-energy-public -- "$docker_bin" compose --project-directory "$repo_dir" exec -T same-energy same-energy-mcp
    exit 0 ;;
  *) echo 'Use: bash scripts/register-client.sh codex|claude-code|antigravity' >&2; exit 2 ;;
esac

umask 077
mkdir -p -- "$(dirname -- "$client_config")"
temporary_file="$(mktemp "$client_config.same-energy.XXXXXX")"
trap 'rm -f -- "$temporary_file"' EXIT
input_file=/dev/null
if [ -e "$client_config" ]; then input_file="$client_config"; fi
compose exec -T same-energy python /app/configure_client.py "$client" "$repo_dir" "$docker_bin" < "$input_file" > "$temporary_file"
if [ -e "$client_config" ] && cmp -s "$temporary_file" "$client_config"; then
  echo 'A entrada same-energy-public já está configurada; preservada.'
  exit 0
fi
if [ -e "$client_config" ]; then
  backup_file="$(mktemp "$client_config.same-energy-backup.XXXXXX")"
  cp -p -- "$client_config" "$backup_file"
fi
mv -- "$temporary_file" "$client_config"
echo "Cliente $client configurado. Recarregue os servidores MCP ou reinicie o cliente."
