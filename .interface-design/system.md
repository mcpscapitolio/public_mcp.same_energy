# Catálogo SAME ENERGY

Mesa de referências para selecionar fotografias depois da busca. O foco são as
imagens, inteiras e sem corte; controles e nomes servem à comparação.

Domínio: prancha de contato, negativo, referência, curadoria, índice e seleção.
Paleta: mesa carvão, moldura grafite, negativo preto, legenda prata, papel marfim,
filme âmbar para marcações e ação. Uma família de superfícies, bordas discretas.
Assinatura: índice de contato + dimensões + contorno âmbar nas fotos marcadas.
Evitar: painel lateral, métricas em cartões, recorte decorativo das imagens.

Modelo único: src/same_energy_mcp/catalog.html. Sem bibliotecas nem fontes remotas.
Georgia 28–44 no título; Arial 14 nos controles; monospace 10–11 nos índices.
Base de espaço: 4px. Página 32px, grid 16px, separação vertical 24px.
Cards 4:3 com object-fit contain. Até 5 colunas, 2 no celular.
Controles com área mínima 44px. Barra fixa inferior sempre visível.
Duas abas acessíveis, filtro de marcadas e dialog nativo para ampliar.
Botão âmbar reservado a Mover seleção; estados de erro e pasta vazia explícitos.
Transição de pressionar 120ms; respeitar redução de movimento.

## Guia de uma nova tarefa

Reutilizar guide.html. Mesma mesa, tipografia, paleta e foco âmbar do catálogo.
Uma pergunta por tela; primeira tela com três opções. Índice 01/02/03, rótulo
serif 25px e descrição 14px por opção, sem imagens de exemplo que sugiram uma escolha.
Opções em grid 240px mínimo, uma coluna no celular; altura mínima208/148px.
Trilha de escolhas e botão Voltar; formulário vem somente após a modalidade.
Resumo final e botão para copiar a continuação. Não expor comandos, IDs ou caminhos
internos no fluxo normal; o agente usa o protocolo para acompanhar a tarefa.
