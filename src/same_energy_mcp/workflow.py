"""Persistent guided briefs, shared by the browser and MCP conversation."""
import colorsys
import hashlib
import io
import json
import os
import re
import secrets
import unicodedata
from pathlib import Path
from PIL import Image, ImageOps
from .catalog import CatalogStore, CatalogError, catalog_port

STEPS = {
    'purpose': ('O que você quer buscar?', [
        ('reference', 'Imagens de referência', 'Fotografias reais, sem vetores, ilustrações ou IA evidente.'),
        ('advertising', 'Referências publicitárias', 'Anúncios ou fotografias publicitárias de produtos e pessoas.'),
        ('grading', 'Referências de color grading', 'Escolha a paleta de cores ou combine color e temática.')]),
    'advertising': ('Qual referência publicitária?', [
        ('ads', 'Anúncios', 'Peças publicitárias prontas, incluindo textos e identidade da campanha.'),
        ('photos', 'Fotos publicitárias', 'Fotografia comercial de produtos ou pessoas.')]),
    'subject': ('O que aparece na foto publicitária?', [
        ('products', 'Produtos', 'Objetos, embalagens, alimentos e fotografia de produto.'),
        ('people', 'Pessoas', 'Retratos, moda, beleza e pessoas em campanhas.')]),
    'grading': ('Como você quer usar o color grading?', [
        ('color_only', 'Color exclusivamente', 'Prioriza a paleta e a luz, sem exigir a mesma temática.'),
        ('color_theme', 'Color e temática', 'Combina a paleta com o assunto ou a cena da referência.')]),
    'input': ('Como você quer começar?', [
        ('image', 'Enviar foto', 'Use uma imagem como referência visual.'),
        ('text', 'Enviar descrição', 'Conte o que você procura, com suas próprias palavras.')]),
}
GUIDED_INSTRUCTIONS = '''NOVA TAREFA: antes de qualquer busca, chame same_energy_start_task.
Abra a URL local e aguarde as escolhas; use same_energy_task(task_id, wait_seconds=45)
para acompanhar. Se não puder abrir o navegador, apresente o seletor retornado
uma etapa por vez, usando os botões de pergunta do cliente quando disponíveis;
registre somente a escolha humana com same_energy_task(choice=...).
Nunca escolha uma modalidade pelo usuário. Após as opções, aceite foto OU descrição.
Na conversa, image_path só pode ser usado com input_authorized=true quando o usuário
indicou e autorizou a imagem. No navegador, a autorização aparece no formulário.
Somente quando ready=true, execute same_energy_run_task com task_id.
Passe esse task_id em get_gallery, preview_image e save_image, e examine a política
visual da modalidade. Não preencha aprovações automaticamente.
Não envie nem pesquise fotos enquanto o formulário está incompleto.
Em cada nova tarefa, crie um novo seletor sem herdar escolhas anteriores.
A pasta de destino será perguntada depois, antes de salvar, como no fluxo atual.'''


def profile(task):
    purpose = task.get('purpose')
    mode = ('ads' if task.get('advertising') == 'ads' else task.get('subject')) if purpose == 'advertising' else task.get('grading') if purpose == 'grading' else 'reference'
    labels = {'reference': 'Imagens de referência', 'ads': 'Anúncios', 'products': 'Fotos publicitárias · Produtos',
              'people': 'Fotos publicitárias · Pessoas', 'color_only': 'Color exclusivamente', 'color_theme': 'Color e temática'}
    ad = mode == 'ads'
    return {'mode': mode, 'label': labels.get(mode, ''), 'photographs_only': not ad,
            'reject_clearly_ai_generated': True, 'reject_watermarks': True,
            'allow_ad_copy_and_branding': ad, 'ignore_theme': mode == 'color_only',
            'visual_review_instructions': (
                'Inspecione a prévia individual. Rejeite IA evidente, marcas-d’água externas e dúvidas. '
                + ('Aceite somente peças publicitárias prontas; textos, logotipos e ilustrações da própria peça são permitidos. '
                   'has_markings refere-se a marcas externas, não ao texto ou à marca da campanha. '
                   'is_advertisement deve ser true, inclusive quando is_photograph for false. ' if ad else
                   'Aceite somente fotografias; exclua vetores, ilustrações, renders e marcações sobrepostas. ')
                + {'products': 'A foto precisa ser publicitária de produtos. ', 'people': 'A foto precisa ser publicitária de pessoas. ',
                   'color_only': 'Avalie somente paleta, temperatura, contraste e luz; não exija o mesmo assunto. ',
                   'color_theme': 'Avalie a paleta e também a temática escolhida. '}.get(mode, '')
                + 'matches_reference_brief deve refletir a inspeção visual, nunca uma aprovação presumida.')}


class TaskStore(CatalogStore):
    def __init__(self):
        super().__init__()
        self.registry = Path(os.environ.get('SAME_ENERGY_TASKS_FILE', str(self.registry.with_name('tasks.json'))))

    def new(self, description=None):
        if description is not None and (not isinstance(description, str) or len(description) > 2000):
            raise CatalogError('A descrição deve ter até 2000 caracteres.')
        task = {'task_id': secrets.token_hex(16), 'token': secrets.token_hex(24), 'step': 'purpose',
                'history': [], 'draft_description': description or ''}
        with self.locked():
            data = self.read(); data[task['task_id']] = task; self.write(data)
        return self.view(task)

    def task(self, ident, token=None):
        if not isinstance(ident, str) or not re.fullmatch('[a-f0-9]{32}', ident):
            raise CatalogError('Tarefa inválida.')
        task = self.read().get(ident)
        if not task or (token is not None and not secrets.compare_digest(task['token'], token)):
            raise CatalogError('Tarefa não encontrada.')
        return task

    def view(self, task):
        step = task['step']
        question, options = STEPS.get(step, ('Envie sua referência' if step == 'brief' else 'Tudo pronto para a busca', []))
        result = {k: v for k, v in task.items() if k not in {'token', 'history'}}
        return {**result, 'url': f"http://127.0.0.1:{catalog_port()}/guide/{task['task_id']}/{task['token']}/",
                'ready': step == 'ready', 'can_go_back': bool(task['history']), 'question': question,
                'options': [{'value': v, 'label': label, 'description': hint} for v, label, hint in options],
                'profile': profile(task), 'instruction': GUIDED_INSTRUCTIONS}

    def choose(self, ident, choice):
        with self.locked():
            data = self.read(); task = data.get(ident)
            if not task: raise CatalogError('Tarefa não encontrada.')
            if choice == 'back':
                if not task['history']: raise CatalogError('Você já está na primeira etapa.')
                previous = task['history'].pop()
                for key in ['purpose', 'advertising', 'subject', 'grading', 'input', 'description', 'image_path', 'theme', 'input_authorized']:
                    task.pop(key, None)
                task.update(previous)
            else:
                step = task['step']
                if choice not in [item[0] for item in STEPS.get(step, ('', []))[1]]:
                    raise CatalogError('Escolha uma das opções desta etapa.')
                task['history'].append({k: v for k, v in task.items() if k not in {'history', 'token', 'task_id', 'draft_description'}})
                task[step] = choice
                task['step'] = {'purpose': {'reference': 'input', 'advertising': 'advertising', 'grading': 'grading'},
                                'advertising': {'ads': 'input', 'photos': 'subject'},
                                'subject': {'products': 'input', 'people': 'input'},
                                'grading': {'color_only': 'input', 'color_theme': 'input'},
                                'input': {'text': 'brief', 'image': 'brief'}}[step][choice]
            self.write(data)
        return self.view(task)

    def submit(self, ident, description=None, image_path=None, theme=None, input_authorized=False, image_data=None):
        with self.locked():
            data = self.read(); task = data.get(ident)
            if not task or task['step'] != 'brief': raise CatalogError('Conclua as opções antes de enviar a referência.')
            if theme is not None and not isinstance(theme, str): raise CatalogError('Temática inválida.')
            theme = (theme or '').strip()
            if len(theme) > 1000: raise CatalogError('A temática deve ter até 1000 caracteres.')
            fields = {'theme': theme}
            if task['input'] == 'text':
                if image_path or image_data: raise CatalogError('Esta etapa aceita somente descrição.')
                if description is not None and not isinstance(description, str): raise CatalogError('Descrição inválida.')
                description = (description or '').strip()
                if not description or len(description) > 2000: raise CatalogError('Escreva uma descrição de 1 a 2000 caracteres.')
                if profile(task)['mode'] == 'color_theme' and not theme: raise CatalogError('Informe também a temática que deseja manter.')
                if profile(task)['mode'] == 'color_only': color_terms(description)
                fields['description'] = description
            else:
                if description: raise CatalogError('Envie uma foto nesta etapa; a temática tem um campo próprio.')
                if input_authorized is not True: raise CatalogError('Autorize o uso da imagem indicada antes de continuar.')
                from .client import Workspace, inspect_image
                # Only bytes provided by the file picker or an explicitly authorized workspace file.
                if image_data is None:
                    if not image_path: raise CatalogError('Selecione uma foto.')
                    source = Workspace().resolve(image_path)
                    if not source.is_file() or source.stat().st_size > 20 * 1024 * 1024: raise CatalogError('Escolha uma imagem de até 20 MiB.')
                    image_data = source.read_bytes()
                if not image_data or len(image_data) > 20 * 1024 * 1024: raise CatalogError('Escolha uma imagem de até 20 MiB.')
                measured = inspect_image(image_data)
                ext = {'JPEG': '.jpg', 'PNG': '.png', 'GIF': '.gif', 'BMP': '.bmp'}.get(measured['format'])
                if not ext: raise CatalogError('Use JPEG, PNG, GIF ou BMP.')
                folder = self.root / '.same-energy-inputs' / ident
                # Check existing ancestors before mkdir or writing, including symlinked input folders.
                current = self.root
                for part in folder.relative_to(self.root).parts:
                    current /= part
                    if current.is_symlink(): raise CatalogError('Pasta de entrada inválida.')
                folder.mkdir(parents=True, exist_ok=True)
                self.directory(folder)
                target = folder / (secrets.token_hex(12) + ext)
                with target.open('xb') as f: f.write(image_data)
                fields.update(image_path=str(target), image_sha256=measured['sha256'], input_authorized=True)
            task['history'].append({k: v for k, v in task.items() if k not in {'history', 'token', 'task_id', 'draft_description'}})
            task.update(fields, step='ready')
            self.write(data)
        return self.view(task)

    def ready(self, ident):
        task = self.task(ident)
        if task['step'] != 'ready': raise CatalogError('Aguarde o usuário concluir o seletor antes de pesquisar.')
        return task


def palette(data):
    from .client import inspect_image
    inspect_image(data)
    with Image.open(io.BytesIO(data)) as image:
        image = ImageOps.exif_transpose(image).convert('RGB'); image.thumbnail((128, 128))
        quantized = image.quantize(colors=5)
        colors = quantized.getpalette()
        rows = sorted(quantized.getcolors(), reverse=True)
        values = [(count, tuple(colors[index*3:index*3+3])) for count, index in rows]
    names = []
    for _, rgb in values:
        h,s,v = colorsys.rgb_to_hsv(*(channel/255 for channel in rgb))
        color = 'black' if v < .17 else 'white' if s < .12 and v > .82 else 'gray' if s < .15 else ['red','orange','yellow','green','green','cyan','cyan','blue','blue','purple','magenta','red'][int(h*12)%12]
        if color not in names: names.append(color)
    return {'colors': ['#%02x%02x%02x' % rgb for _,rgb in values], 'terms': ' '.join(names)}


def search_plan(task):
    spec = profile(task); mode = spec['mode']
    if task['input'] == 'image':
        data = Path(task['image_path']).read_bytes()
        if hashlib.sha256(data).hexdigest() != task['image_sha256']: raise CatalogError('A imagem mudou; refaça o envio no seletor.')
        if mode == 'color_only':
            colors = palette(data)
            return {'method': 'text', 'query': 'photography color grading ' + colors['terms'], 'palette': colors,
                    'color_only_ranking': True, 'original_photo_uploaded': False}
        return {'method': 'image', 'image_path': task['image_path'], 'original_photo_uploaded': True}
    prefixes = {'reference': 'photography', 'ads': 'advertising campaign print ad', 'products': 'commercial product photography',
                'people': 'commercial portrait advertising photography', 'color_only': 'photography color grading', 'color_theme': 'photography color grading'}
    query = prefixes[mode] + ' ' + (color_terms(task['description']) if mode == 'color_only' else task['description'])
    if mode == 'color_theme': query += ' ' + task['theme']
    return {'method': 'text', 'query': query, 'original_photo_uploaded': False}


def brief_signature(task):
    fields = {key: task.get(key) for key in ['purpose', 'advertising', 'subject', 'grading', 'input', 'description', 'theme', 'image_sha256']}
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()


def color_histogram(data):
    from .client import inspect_image
    inspect_image(data)
    with Image.open(io.BytesIO(data)) as im:
        im = ImageOps.exif_transpose(im).convert('RGB'); im.thumbnail((64, 64))
        hist = [0] * 72
        for rgb in im.get_flattened_data():
            h,s,v = colorsys.rgb_to_hsv(*(c/255 for c in rgb))
            hue = int(h*12)%12 if s >= .15 else 0
            hist[hue*6 + int(s >= .15)*3 + min(2,int(v*3))] += 1
        total = sum(hist)
        return [value/total for value in hist]


def color_terms(description):
    normalized = unicodedata.normalize('NFKD', description).encode('ascii', 'ignore').decode().lower()
    vocabulary = {
        'azul': 'blue', 'azuis': 'blue', 'blue': 'blue', 'red': 'red', 'vermelho': 'red', 'vermelha': 'red',
        'green': 'green', 'verde': 'green', 'yellow': 'yellow', 'amarelo': 'yellow', 'amarela': 'yellow',
        'orange': 'orange', 'laranja': 'orange', 'pink': 'pink', 'rosa': 'pink', 'purple': 'purple', 'roxo': 'purple', 'roxa': 'purple',
        'violeta': 'purple', 'cyan': 'cyan', 'ciano': 'cyan', 'turquesa': 'teal', 'teal': 'teal', 'magenta': 'magenta',
        'ambar': 'amber', 'amber': 'amber', 'marrom': 'brown', 'brown': 'brown', 'bege': 'beige', 'beige': 'beige',
        'gold': 'gold', 'dourado': 'gold', 'dourada': 'gold', 'branco': 'white', 'branca': 'white', 'white': 'white',
        'preto': 'black', 'preta': 'black', 'black': 'black', 'cinza': 'gray', 'gray': 'gray', 'grey': 'gray',
        'quente': 'warm', 'warm': 'warm', 'frio': 'cool', 'fria': 'cool', 'cool': 'cool',
        'saturado': 'saturated', 'saturada': 'saturated', 'saturated': 'saturated', 'desaturado': 'desaturated', 'desaturada': 'desaturated', 'desaturated': 'desaturated',
        'pastel': 'pastel', 'monocromatico': 'monochrome', 'monocromatica': 'monochrome', 'monochrome': 'monochrome',
        'escuro': 'dark', 'escura': 'dark', 'dark': 'dark', 'claro': 'bright', 'clara': 'bright', 'bright': 'bright',
        'contraste': 'contrast', 'contrast': 'contrast', 'alto': 'high', 'high': 'high', 'baixo': 'low', 'low': 'low',
        'suave': 'soft', 'soft': 'soft', 'sombras': 'shadows', 'shadows': 'shadows', 'luzes': 'highlights', 'highlights': 'highlights',
        'azuladas': 'blue', 'azulados': 'blue', 'avermelhado': 'red', 'avermelhada': 'red', 'esverdeado': 'green', 'esverdeada': 'green',
    }
    terms = []
    for word in re.findall(r'[a-z]+', normalized):
        value = vocabulary.get(word) or vocabulary.get(word[:-1]) if word.endswith('s') else vocabulary.get(word)
        if value and value not in terms: terms.append(value)
    for code in re.findall(r'#[0-9a-f]{6}\b', normalized):
        rgb = tuple(int(code[i:i+2], 16)/255 for i in (1,3,5)); h,s,v = colorsys.rgb_to_hsv(*rgb)
        value = 'black' if v < .17 else 'white' if s < .12 and v > .82 else 'gray' if s < .15 else ['red','orange','yellow','green','green','cyan','cyan','blue','blue','purple','magenta','red'][int(h*12)%12]
        if value not in terms: terms.append(value)
    if not terms: raise CatalogError('Descreva ao menos uma cor, temperatura de luz ou contraste para buscar somente color.')
    return ' '.join(terms)
