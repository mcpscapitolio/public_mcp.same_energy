# SAME-ENERGY MCP — distribuição pública

Servidor MCP em Docker para encontrar referências visuais reais no
[Same Energy](https://same.energy/) por descrição ou fotografia de referência.
Inclui ajuda assistida, prancha de candidatas, consulta da origem e download do
arquivo maior disponível, preservando seus bytes.

## Instalação

Requer Git, Bash e Docker com Compose em execução. Substitua a pasta abaixo por
uma pasta absoluta escolhida para compartilhar imagens com o Docker.

**Codex**

```sh
git clone https://github.com/mcpscapitolio/public_mcp.same_energy.git && cd public_mcp.same_energy && bash scripts/install.sh --workspace "/caminho/absoluto/referencias" --client codex
```

**Claude Code**

```sh
git clone https://github.com/mcpscapitolio/public_mcp.same_energy.git && cd public_mcp.same_energy && bash scripts/install.sh --workspace "/caminho/absoluto/referencias" --client claude-code
```

**Antigravity**

```sh
git clone https://github.com/mcpscapitolio/public_mcp.same_energy.git && cd public_mcp.same_energy && bash scripts/install.sh --workspace "/caminho/absoluto/referencias" --client antigravity
```

Execute apenas a linha do cliente desejado em uma pasta onde o repositório ainda
não foi clonado. Se já instalou, use `bash scripts/register-client.sh CLIENTE`
para adicionar outro cliente sem reconstruir a imagem.

O instalador cria o `.env`, executa testes, inicia o serviço, verifica o protocolo
MCP e registra `same-energy-public` no cliente escolhido. Preserva configurações
anteriores e cria backup ao alterar arquivos de configuração existentes de Codex
ou Antigravity; entradas com o mesmo nome e configuração diferente exigem revisão.
No Claude Code, usa a própria CLI no escopo do usuário. Recarregue os servidores
MCP ou reinicie o cliente após instalar.

**Guia completo, instalação manual e instruções para outro agente:**
[AJUDA_INSTALACAO.md](AJUDA_INSTALACAO.md).

## Comece pela ajuda assistida

No seu agente, pergunte:

> como funciona o mcp SAME-ENERGY?

O MCP oferece `same_energy_help`, o recurso `same-energy://help` e o prompt
`como_funciona_same_energy`. O agente explica as opções e ajuda a escolher entre
uma descrição, foto de referência ou galeria existente. A explicação inicial não
faz pesquisas, uploads ou downloads.

## O que está incluído

| Ferramenta | Uso |
|---|---|
| `same_energy_help` | Orientação assistida e exemplos |
| `same_energy_check_updates` | Consultar se há versão nova no GitHub |
| `same_energy_prepare_update` | Preparar a instalação após concordância explícita |
| `same_energy_update_notes` | Ver mudanças da versão disponível ou da última instalada |
| `same_energy_status` | Conferir site, navegador e pasta acessível |
| `same_energy_search_by_text` | Buscar por descrição |
| `same_energy_search_by_image` | Buscar por semelhança, enviando a foto ao site |
| `same_energy_get_gallery` | Retomar uma galeria sem reenviar a foto |
| `same_energy_preview_image` | Examinar a imagem, resolução e origem |
| `same_energy_save_image` | Salvar após escolha da pasta e triagem visual |

Os padrões persistentes aceitam somente candidatas grandes, de pelo menos
1280 × 720 em qualquer orientação. O assistente deve selecionar apenas fotografias,
rejeitando marcações sobrepostas, ilustrações, renders, sinais claros de IA e dúvidas.
O servidor exige a avaliação visual da prévia individual antes do download; não
contém um detector automático de IA. Aparência fotográfica não comprova a origem.

Em cada nova busca, o agente pergunta a pasta de destino, salvo se já informada.
O salvamento cria `output_AAAA-MM-DD_nome-da-busca/`, com os JSONs em `json/`.
As preferências ficam no volume Docker; caminhos pessoais e sessões não são
incluídos na distribuição. O envio de uma foto transmite o arquivo ao Same Energy.

## Privacidade e manutenção

As buscas públicas não exigem conta, senha, API key nem token do GitHub. O navegador
é isolado no Docker e não usa login pessoal, cookies ou keychain do host.
A instalação usa projeto, imagem e volume próprios, sem publicar portas de rede.

O projeto usa a interface pública do site e pode precisar de ajustes se ela mudar.
Não é afiliado ao Same Energy. A licença MIT cobre o código; as imagens têm suas
próprias origens e licenças. Veja [LICENSE](LICENSE).

## Atualizações com orientação do agente

Ao iniciar uma conexão MCP, o servidor consulta o GitHub público. Se houver uma
versão mais recente, o agente deve dizer: **“Tem atualização, posso instalar?”**
A consulta não instala nada. A recusa mantém o uso normal da versão atual.

Depois da concordância, o agente prepara um plano vinculado ao commit apresentado
e executa o atualizador no terminal do host. A nova versão é testada antes de
alterar o checkout; mudanças locais impedem a atualização para evitar sobrescrita.
O `.env` e as preferências Docker são preservados. O servidor não recebe acesso
ao socket Docker nem instala atualizações por conta própria.

Pergunte **“O que mudou na última atualização?”** para consultar as notas salvas.
Antes de instalar, também é possível perguntar **“O que muda nessa atualização?”**.
Veja [CHANGELOG.md](CHANGELOG.md) e o [guia de atualização](AJUDA_INSTALACAO.md#atualizações-assistidas).
Se o GitHub não responder, a versão instalada continua funcionando e a checagem
pode ser repetida com `same_energy_check_updates`.

```sh
docker build --target test -t same-energy-public-mcp:test .
```

O [workflow de CI](.github/workflows/ci.yml) executa testes offline em Docker, sem
credenciais, consultas ao site ou uploads reais.
