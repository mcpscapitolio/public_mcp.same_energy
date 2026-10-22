# Histórico de atualizações

## 0.5.0

- Catálogo automático em uma única página, com modelo reutilizável e visualização ampliada das fotografias.
- Marcação de imagens e filtro Visualizar apenas marcadas, com preservação das marcações no navegador.
- Botão fixo Mover seleção cria selecionadas/ dentro da pasta da busca e move as imagens sem sobrescrever arquivos.
- A grade principal mostra apenas as imagens restantes; a aba Selecionadas lê somente selecionadas/.
- Catálogo servido localmente pelo Docker, com catalogo.html para reabrir e JSONs preservados em json/.
- Nova ferramenta same_energy_create_catalog para criar ou retomar o seletor de uma busca salva.

## 0.4.0

- Consulta inicial ao GitHub para verificar se há uma versão mais recente.
- Pergunta “Tem atualização, posso instalar?” antes de qualquer atualização.
- Plano vinculado ao commit apresentado e instalação somente após concordância.
- Teste da nova versão antes de modificar o checkout; preservação de mudanças locais.
- Preservação de `.env` e preferências no volume Docker.
- Lista das mudanças disponíveis e registro persistente da última atualização concluída.

## 0.3.0

- Primeira distribuição pública, com instalação para Codex, Claude Code e Antigravity.
- Ajuda assistida para “como funciona o mcp SAME-ENERGY?”.
- Buscas por descrição, por imagem e retomada de galerias.
- Seleção de fotografias grandes, pasta por busca e JSONs em subpasta.
- Triagem visual antes do download, com rejeição de marcações e IA evidente.
