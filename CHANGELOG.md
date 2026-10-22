# Histórico de atualizações

## 0.6.0

- Nova tarefa com seletor de três modalidades: imagens de referência, referências publicitárias e color grading.
- Publicidade com Anúncios ou Fotos publicitárias, divididas em Produtos e Pessoas.
- Color grading com Color exclusivamente ou Color e temática; entrada por foto ou descrição após as escolhas.
- Guia local com telas, botão Voltar e autorização explícita para usar a foto; briefs persistentes no Docker.
- Buscas e triagem vinculadas à modalidade; anúncios permitem textos e identidade da própria peça, mantendo rejeição de marcas externas e IA evidente.
- Color exclusivamente por foto analisa a paleta localmente, sem enviar a foto, e ordena candidatas por cor; por descrição remove a temática da consulta.
- Fluxo alternativo na conversa para clientes sem navegador, com as mesmas escolhas humanas e ajuda assistida atualizada.

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
