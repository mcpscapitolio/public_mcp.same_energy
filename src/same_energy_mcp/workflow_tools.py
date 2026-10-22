"""The same guided MCP contract is registered by public and private servers."""
import asyncio
from typing import Annotated
from mcp.server.fastmcp import Context
from pydantic import Field
from mcp.types import TextContent, ImageContent
from .workflow import TaskStore


def register_workflow_tools(mcp, client, gallery_response):
    @mcp.tool(annotations={'readOnlyHint': False, 'destructiveHint': False, 'openWorldHint': False})
    def same_energy_start_task(initial_description: str | None = None) -> dict:
        """Comece TODA nova tarefa com este seletor. Abre 3 objetivos, sem pesquisar nem enviar fotos.

        Entregue e abra a URL local. O usuário escolhe referência fotográfica, publicidade
        (Anúncios ou Fotos publicitárias → Produtos/Pessoas) ou color grading
        (Color exclusivamente / Color e temática), depois Enviar foto ou Enviar descrição.
        Se não houver navegador, apresente options e registre cada escolha com same_energy_task.
        Nunca escolha pelo usuário. initial_description só preserva um pedido já fornecido.
        """
        return TaskStore().new(initial_description)

    @mcp.tool(annotations={'readOnlyHint': False, 'destructiveHint': False, 'openWorldHint': False})
    async def same_energy_task(task_id: str, choice: str | None = None, description: str | None = None,
                               image_path: str | None = None, theme: str | None = None,
                               input_authorized: Annotated[bool, Field(strict=True)] = False,
                               wait_seconds: Annotated[int, Field(ge=0, le=60)] = 0) -> dict:
        """Lê a etapa atual ou registra uma escolha humana; não pesquisa nem transmite imagens.

        Sem argumentos de edição, acompanha o formulário; wait_seconds aguarda até ready=true.
        No modo conversacional, use choice com um value de options (ou back) por vez.
        Na última etapa, passe description OU image_path; image_path requer autorização
        explícita input_authorized=true. Copia somente a imagem indicada para a entrada local.
        theme separa a temática das cores em Color e temática. Nenhuma escolha é presumida.
        """
        store = TaskStore()
        if choice is not None:
            if description is not None or image_path is not None or theme is not None:
                raise ValueError('Registre a escolha e a referência em etapas separadas.')
            return store.choose(task_id, choice)
        if description is not None or image_path is not None:
            return store.submit(task_id, description, image_path, theme, input_authorized)
        deadline = asyncio.get_running_loop().time() + wait_seconds
        while True:
            result = store.view(store.task(task_id))
            if result['ready'] or asyncio.get_running_loop().time() >= deadline: return result
            await asyncio.sleep(.5)

    @mcp.tool(annotations={'readOnlyHint': False, 'destructiveHint': False, 'openWorldHint': True})
    async def same_energy_run_task(task_id: str, ctx: Context,
                                   limit: Annotated[int, Field(ge=1, le=50)] = 12) -> list[TextContent | ImageContent]:
        """Pesquisa SOMENTE após o usuário concluir o seletor (ready=true).

        Usa o brief salvo; envia a foto ao Same Energy nos modos por semelhança.
        Color exclusivamente por foto usa apenas a paleta local numa busca textual,
        reordenada por cor; não envia a foto nem exige a mesma temática.
        Retorna candidatas, task_id e a política visual da modalidade; inspecione-as.
        Passe task_id em get_gallery, preview_image e save_image. Pergunte a pasta
        antes de salvar e não presuma a triagem visual de anúncio, produto, pessoa ou color.
        """
        c = client(ctx)
        return await gallery_response(c, await c.run_task(task_id, limit))
