# Como funciona o MCP SAME-ENERGY?

Ele conecta seu agente ao Same Energy para encontrar referências visuais reais por
descrição ou semelhança com uma fotografia. As buscas usam o site público; não é
preciso criar conta nem fornecer token. O MCP não gera imagens.

No início da conexão, também há uma consulta ao GitHub. Se houver versão nova,
o agente pergunta **“Tem atualização, posso instalar?”** e só instala depois da
concordância explícita. Se esse aviso estiver pendente, priorize essa pergunta;
depois da resposta, retome a orientação de uso sem juntar várias perguntas.
Pergunte **“O que mudou na última atualização?”** para consultar as notas instaladas,
ou **“O que muda nessa atualização?”** para ver as notas antes de aceitar.

## Ajuda assistida para o agente

Ao receber “como funciona o mcp SAME-ENERGY?” ou uma pergunta equivalente:

1. Explique a função em linguagem simples e apresente estas opções:
   - **Descrição:** “Busque fotografias de ruas à noite, com chuva e luzes de neon.”
   - **Foto de referência:** “Encontre fotografias parecidas com esta imagem.”
   - **Continuar uma busca:** “Abra novamente esta galeria do Same Energy.”
2. Informe que o envio de uma foto transmite o arquivo ao site externo
   `https://same.energy`. Envie somente a imagem indicada e autorizada para a busca.
3. Explique que as candidatas aparecem em uma prancha numerada. Examine-as antes
   de apresentar a seleção final; somente fotografias grandes, sem marcações
   sobrepostas ou sinais claros de IA. Descarte ilustrações, renders e dúvidas.
   Essa é uma triagem visual do assistente, não um detector automático de IA.
4. Para baixar, pergunte **em qual pasta salvar** nessa busca, salvo se a pessoa já
   informou. O MCP cria `output_AAAA-MM-DD_nome-da-busca/`, com metadados em `json/`.
   Examine a prévia individual antes de salvar e registre `visual_review` com o
   SHA-256 retornado. A escolha da pasta vale para as imagens da mesma busca.
5. Dê um exemplo de pedido completo:
   “Busque fotografias grandes de ruas chuvosas à noite e salve as escolhidas em
   [minha pasta de referências].” O trecho entre colchetes deve ser substituído
   por uma pasta absoluta que a pessoa escolher, dentro da pasta compartilhada.
6. Termine com uma única pergunta: **“Você prefere começar por uma descrição,
   uma foto de referência ou uma galeria existente?”** Se a pessoa já forneceu
   essa informação, continue a partir dela sem perguntar novamente.

Na explicação inicial não pesquise, não envie fotos e não baixe arquivos.
Use `same_energy_status` quando for necessário conferir a conexão; se houver um
problema, explique o diagnóstico e consulte o guia de instalação.

## Regras dos arquivos

- Resolução mínima: 1280 × 720 pixels, em qualquer orientação, conferida antes
  de incluir a candidata e novamente no download.
- Placas e textos da própria cena são permitidos; marcas-d'água, assinaturas,
  anotações e logotipos sobrepostos são rejeitados.
- A prévia serve para examinar. O download preserva os bytes do arquivo maior
  exposto na página, sem ampliar, recomprimir ou sobrescrever arquivos.
- O JSON registra origem, resolução, tamanho, hash e triagem. A licença de uso
  depende da fonte; a aparência de uma fotografia não comprova sua origem.
- As preferências persistem no volume Docker. Não apague o volume ao atualizar.

Instalação e solução de problemas:
https://github.com/mcpscapitolio/public_mcp.same_energy/blob/main/AJUDA_INSTALACAO.md
