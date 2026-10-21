"""Render a client config from stdin; the caller performs the atomic host write."""
import json
import sys
import tomllib

NAME = "same-energy-public"


def render(client: str, original: str, directory: str, docker: str) -> str:
    entry = {"command": docker, "args": ["compose", "--project-directory", directory,
             "exec", "-T", "same-energy", "same-energy-mcp"]}
    if client == "codex":
        entry.update(startup_timeout_sec=30, tool_timeout_sec=180)
        data = tomllib.loads(original)
        servers = data.get("mcp_servers", {})
        if NAME in servers:
            if servers[NAME] != entry:
                raise ValueError("existing-entry")
            return original
        section = f"\n[mcp_servers.{NAME}]\n"
        section += "\n".join(f"{key} = {json.dumps(value, ensure_ascii=False)}" for key, value in entry.items()) + "\n"
        result = original.rstrip() + "\n" + section
        assert tomllib.loads(result)["mcp_servers"][NAME] == entry
        return result
    if client != "antigravity":
        raise ValueError("unknown-client")
    data = json.loads(original) if original.strip() else {}
    servers = data.setdefault("mcpServers", {})
    if NAME in servers:
        if servers[NAME] != entry:
            raise ValueError("existing-entry")
        return original
    servers[NAME] = entry
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


if __name__ == "__main__":
    try:
        result = render(sys.argv[1], sys.stdin.read(), sys.argv[2], sys.argv[3])
    except (ValueError, TypeError, AttributeError, AssertionError):
        sys.exit("Configuração inválida ou entrada same-energy-public diferente já existente. Nada foi alterado; revise essa entrada antes de instalar.")
    sys.stdout.write(result)
