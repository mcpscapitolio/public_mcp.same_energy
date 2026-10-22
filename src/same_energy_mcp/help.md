# Como funciona o MCP SAME-ENERGY?

O MCP ajuda a encontrar referências no Same Energy por descrição ou semelhança
com uma foto. Ele não gera imagens. As buscas públicas não exigem conta ou token.

## Uma nova tarefa, uma escolha por vez

Ao começar uma nova tarefa, o agente chama `same_energy_start_task` e abre o link
local. O guia apresenta três opções:

1. **Imagens de referência:** o modo fotográfico atual. Somente fotografias,
   sem vetores, ilustrações, renders, marcas sobrepostas ou IA evidente.
2. **Referências publicitárias:** na próxima tela, escolha **Anúncios** ou
   **Fotos publicitárias**. Em fotos publicitárias, escolha **Produtos** ou **Pessoas**.
3. **Referências de color grading:** na próxima tela, escolha **Color exclusivamente**
   ou **Color e temática**.

Depois das escolhas, há duas entradas: **Enviar foto** ou **Enviar descrição**.
Os botões Voltar permitem corrigir uma escolha. Uma nova tarefa começa sem herdar
as escolhas da anterior. O agente nunca escolhe uma modalidade pelo usuário.

- Em **Anúncios**, textos, logotipos e ilustrações da peça publicitária pronta são
  permitidos. Marcas-d'água externas, IA evidente e dúvidas continuam rejeitadas.
  Fotos publicitárias de produtos ou pessoas continuam exigindo fotografias.
- Em **Color exclusivamente**, o assunto pode ser diferente. Se enviar foto,
  a paleta é analisada localmente e a busca é textual por cores, com reordenação
  aproximada por paleta. A foto não é enviada ao site nessa modalidade. Por
  descrição, somente cores, luz e contraste entram na consulta; o tema é ignorado.
- Em **Color e temática**, a referência deve combinar as cores e o assunto.
  Ao usar descrição, há um campo separado para informar a temática.

O formulário de foto pede autorização explícita. Nas buscas por semelhança,
a foto indicada é enviada para `https://same.energy` quando o agente executa
a busca. Até concluir o guia, nenhuma busca nem envio ao site é feito. O
formulário guarda uma cópia local da entrada para o agente; não altera o original.
Use JPEG, PNG, GIF ou BMP de até 20 MiB. Referências locais ficam na pasta
`.same-energy-inputs/` da área compartilhada; só os arquivos escolhidos são lidos.

Ao concluir, volte à conversa. O agente acompanha a tarefa com `same_energy_task`
e pesquisa com `same_energy_run_task`. O botão Copiar pedido ajuda a retomar
se o agente estiver aguardando uma mensagem. Se o cliente não puder abrir o
navegador, apresente as mesmas opções na conversa, uma etapa por vez, e registre
cada escolha humana com `same_energy_task`. Nenhuma entrada deve ser presumida.

## Seleção e arquivos

O agente examina as candidatas e a prévia individual de cada referência antes de
salvar, seguindo a modalidade escolhida. Isso é triagem visual do assistente,
não um detector automático de IA ou uma classificação automática de publicidade.
Ele descarta dúvidas e registra `visual_review` com o SHA-256 da prévia examinada.
Em tarefas guiadas, `matches_reference_brief` deve confirmar a adequação visual.
Em Anúncios, `is_advertisement` confirma que se trata de uma peça pronta; não
invente aprovação. O `task_id` acompanha busca, galeria, prévia e salvamento.

Antes de baixar, pergunte **em qual pasta salvar** nesta busca, salvo se a pessoa
já informou. O MCP cria `output_AAAA-MM-DD_nome-da-busca/`, com os JSONs em `json/`.
As imagens devem ter no mínimo 1280 × 720, em qualquer orientação. O download
preserva os bytes do arquivo maior exposto na página, sem ampliar ou recomprimir.
Origem, licença, dimensões, hash, triagem e modalidade ficam nos metadados.
A licença depende da fonte; aparência fotográfica não comprova a origem.

Ao terminar, abra e entregue o catálogo. Todas as imagens ficam na mesma página:
marque, confira **Visualizar apenas marcadas** e use **Mover seleção** no rodapé
fixo. As imagens vão para `selecionadas/`, dentro da busca, e aparecem somente
na aba Selecionadas. A grade principal permite acrescentar outras depois.
Os JSONs continuam em `json/`. O Docker precisa continuar em execução.

## Orientação para o agente

Na explicação inicial, apresente as três modalidades e um exemplo de cada uma.
Não pesquise nem envie fotos durante a explicação. Quando a pessoa quiser começar,
use o seletor. Nunca pule as opções por ela ter enviado uma descrição ou foto:
preserve a descrição inicial e aguarde a modalidade e a forma de entrada.

Exemplos: “Busque fotografias de ruas chuvosas”; “Quero anúncios de perfumes”;
“Preciso de referências de color com sombras azuis e luzes quentes”. Não trate
esses exemplos como uma escolha humana para a tarefa atual.

As preferências, os briefs e o registro dos catálogos persistem no Docker.
Não apague o volume ao atualizar. Na distribuição pública, a conexão inicial
consulta o GitHub e, se houver novidade, o agente pergunta exatamente
**“Tem atualização, posso instalar?”**. Só instala após concordância explícita.
**“O que mudou na última atualização?”** consulta as notas instaladas.

Guia de instalação pública:
https://github.com/mcpscapitolio/public_mcp.same_energy/blob/main/AJUDA_INSTALACAO.md
