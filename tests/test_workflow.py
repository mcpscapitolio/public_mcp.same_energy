import asyncio
import base64
import io
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from PIL import Image
from playwright.sync_api import sync_playwright, expect
from same_energy_mcp.catalog import CatalogError, make_server
from same_energy_mcp.client import SameEnergy, inspect_image
from same_energy_mcp.workflow import TaskStore, profile, search_plan, color_terms, color_histogram

PATHS = {
    'reference': ['reference'], 'ads': ['advertising', 'ads'],
    'products': ['advertising', 'photos', 'products'], 'people': ['advertising', 'photos', 'people'],
    'color_only': ['grading', 'color_only'], 'color_theme': ['grading', 'color_theme'],
}


def image_bytes(color='#3b6492'):
    buffer=io.BytesIO();Image.new('RGB',(1600,1000),color).save(buffer,format='PNG');return buffer.getvalue()


class WorkflowFixture:
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.env=patch.dict(os.environ,{'SAME_ENERGY_WORKSPACE':str(self.root),'SAME_ENERGY_HOST_WORKSPACE':'',
            'SAME_ENERGY_PREFERENCES_FILE':str(self.root/'data/preferences.json'),
            'SAME_ENERGY_CATALOG_REGISTRY':str(self.root/'data/catalogs.json'),
            'SAME_ENERGY_TASKS_FILE':str(self.root/'data/tasks.json')})
        self.env.start();self.store=TaskStore();self.photo=self.root/'authorized.png';self.photo.write_bytes(image_bytes())
    def tearDown(self):self.env.stop();self.tmp.cleanup()
    def brief(self,mode='reference',kind='text'):
        view=self.store.new();ident=view['task_id']
        for choice in [*PATHS[mode],kind]:view=self.store.choose(ident,choice)
        return ident,view
    def ready(self,mode='reference',kind='text'):
        ident,_=self.brief(mode,kind)
        if kind=='text':self.store.submit(ident,description='blue shadows and warm highlights' if mode.startswith('color') else 'rainy urban street',theme='city at night' if mode=='color_theme' else None)
        else:self.store.submit(ident,image_path=str(self.photo),input_authorized=True)
        return ident


class WorkflowTests(WorkflowFixture,unittest.TestCase):
    def test_initial_three_choices_and_all_twelve_paths_persist(self):
        for mode in PATHS:
            for kind in ['text','image']:
                with self.subTest(mode=mode,kind=kind):
                    ident=self.ready(mode,kind);task=TaskStore().ready(ident)
                    self.assertEqual(profile(task)['mode'],mode);self.assertEqual(task['input'],kind)
        view=self.store.new();self.assertEqual([x['value'] for x in view['options']],['reference','advertising','grading'])
        self.assertFalse(view['ready']);self.assertNotIn('purpose',view)
        self.assertEqual(len(self.store.read()),13)

    def test_invalid_choices_incomplete_tasks_and_back_cannot_leave_stale_policy(self):
        view=self.store.new();ident=view['task_id']
        for choice in ['products','image','ads']:
            with self.assertRaises(CatalogError):self.store.choose(ident,choice)
        with self.assertRaises(CatalogError):self.store.ready(ident)
        with self.assertRaises(CatalogError):self.store.submit(ident,description='not yet')
        for choice in ['advertising','photos','products','image']:self.store.choose(ident,choice)
        self.store.choose(ident,'back');self.store.choose(ident,'back')
        task=self.store.task(ident);self.assertNotIn('subject',task);self.assertNotIn('input',task)
        self.assertEqual(task['step'],'subject')

    def test_photo_requires_authorization_valid_bytes_and_workspace_path(self):
        ident,_=self.brief(kind='image')
        for path,authorized in [(str(self.photo),False),('/etc/passwd',True),('../outside',True)]:
            with self.assertRaises(ValueError):self.store.submit(ident,image_path=path,input_authorized=authorized)
        self.assertFalse((self.root/'.same-energy-inputs').exists())
        for data in [b'<svg>not a photo</svg>',b'x'*(20*1024*1024+1)]:
            with self.assertRaises(ValueError):self.store.submit(ident,image_data=data,input_authorized=True)
        result=self.store.submit(ident,image_data=image_bytes(),input_authorized=True)
        self.assertEqual(Path(result['image_path']).read_bytes(),image_bytes())
        self.assertEqual(self.photo.read_bytes(),image_bytes())
        with self.assertRaises(ValueError):self.store.submit(ident,image_data=image_bytes(),input_authorized=True)

    def test_input_symlink_and_cross_input_type_are_rejected(self):
        ident,_=self.brief(kind='image')
        (self.root/'.same-energy-inputs').symlink_to(self.root/'data')
        with self.assertRaises(ValueError):self.store.submit(ident,image_data=image_bytes(),input_authorized=True)
        ident,_=self.brief(kind='text')
        with self.assertRaises(ValueError):self.store.submit(ident,image_path=str(self.photo),input_authorized=True)
        with self.assertRaises(ValueError):self.store.submit(ident,description='')

    def test_color_only_plan_excludes_theme_and_never_uploads_photo(self):
        ident=self.ready('color_only','image');plan=search_plan(self.store.ready(ident))
        self.assertEqual(plan['method'],'text');self.assertFalse(plan['original_photo_uploaded']);self.assertIn('palette',plan)
        ident,_=self.brief('color_only','text')
        self.store.submit(ident,description='A red car on a blue street, low contrast',theme='cars')
        query=search_plan(self.store.ready(ident))['query']
        self.assertNotIn('car',query);self.assertNotIn('street',query);self.assertIn('red',query);self.assertIn('blue',query)
        self.assertEqual(color_histogram(image_bytes()),color_histogram(image_bytes()))
        with self.assertRaises(ValueError):color_terms('somente uma cidade')
        self.assertIn('blue',color_terms('sombras azuladas e #1020ff'))
        task=self.store.ready(ident);task['input']='image';task['image_path']=str(self.photo);task['image_sha256']='0'*64
        with self.assertRaises(ValueError):search_plan(task)

    def test_color_theme_requires_separate_theme_and_keeps_it_in_search(self):
        ident,_=self.brief('color_theme','text')
        with self.assertRaises(ValueError):self.store.submit(ident,description='blue and orange')
        self.store.submit(ident,description='blue and orange',theme='portraits in a city')
        self.assertIn('portraits in a city',search_plan(self.store.ready(ident))['query'])
        self.assertTrue(profile(self.store.ready(ident))['photographs_only'])


class WorkflowClientTests(WorkflowFixture,unittest.IsolatedAsyncioTestCase):
    async def test_search_plan_is_executed_and_color_rank_uses_only_palette(self):
        ident=self.ready('color_only','image');client=SameEnergy()
        rows=[{'image_id':'red','thumbnail_url':'https://blobcdn.same.energy/thumbnails/red'},
              {'image_id':'blue','thumbnail_url':'https://blobcdn.same.energy/thumbnails/blue'}]
        client.search_text=AsyncMock(return_value={'results':rows,'gallery_url':'https://same.energy/search?q=blue'})
        client.search_image=AsyncMock();client.fetch=AsyncMock(side_effect=[image_bytes('#ff0000'),image_bytes()])
        try:
            result=await client.run_task(ident,2)
            self.assertEqual(result['results'][0]['image_id'],'blue');client.search_image.assert_not_awaited()
            self.assertEqual(result['reference_profile']['mode'],'color_only')
            client.task_profile(ident,'blue')
            with self.assertRaises(ValueError):client.task_profile(ident,'unknown')
            self.store.choose(ident,'back')
            with self.assertRaises(ValueError):client.task_profile(ident,'blue')
        finally:await client.close()

    async def test_only_finished_ads_can_save_nonphotographic_layout_and_review_is_scoped(self):
        for mode in PATHS:
            with self.subTest(mode=mode):
                ident=self.ready(mode);client=SameEnergy();data=image_bytes()
                client.search_text=AsyncMock(return_value={'results':[{'image_id':'fixture'}]})
                client.detail=AsyncMock(return_value={'asset':{'url':'https://blobcdn.same.energy/a/fixture'}})
                client.fetch=AsyncMock(return_value=data)
                try:
                    await client.run_task(ident,1);preview,_=await client.preview('fixture',ident)
                    review={'sha256':preview['sha256'],'is_photograph':False,'is_advertisement':True,
                            'matches_reference_brief':True,'has_markings':False,'clearly_ai_generated':False,'uncertain':False}
                    result=await client.save('fixture',str(self.root),search_name=mode,destination_confirmed=True,visual_review=review,task_id=ident)
                    self.assertEqual(result['saved'],mode=='ads')
                    if mode=='ads':
                        self.assertEqual(Path(result['path']).read_bytes(),data)
                        self.assertEqual(json.loads(Path(result['metadata_path']).read_text())['reference_profile']['mode'],'ads')
                        for key,value in [('clearly_ai_generated',True),('has_markings',True),('uncertain',True),('is_advertisement',False),('matches_reference_brief',False)]:
                            denied=await client.save('fixture',str(self.root),destination_confirmed=True,visual_review={**review,key:value},task_id=ident)
                            self.assertFalse(denied['saved'])
                    if mode=='reference':
                        review.update(is_photograph=True)
                        # A guided preview cannot authorize a legacy save or another task.
                        legacy=await client.save('fixture',str(self.root),destination_confirmed=True,visual_review=review)
                        self.assertTrue(legacy['requires_visual_review'])
                finally:await client.close()

    async def test_legacy_search_tools_show_selector_without_network_and_task_waits_for_input(self):
        from same_energy_mcp.server import mcp
        from same_energy_mcp.workflow_tools import register_workflow_tools
        from mcp.server.fastmcp import FastMCP
        server=FastMCP('fixture');client=SameEnergy();client.search_text=AsyncMock();client.search_image=AsyncMock()
        async def response(_c,result):return result
        register_workflow_tools(server,lambda ctx:client,response)
        try:
            result=await server.call_tool('same_energy_start_task',{'initial_description':'already supplied'})
            if isinstance(result,tuple):result=result[0]
            # Framework returns native TextContent; inspect its JSON, rather than calling a Python helper.
            data=json.loads(result[0].text);self.assertEqual(len(data['options']),3)
            ident=data['task_id']
            read=await server.call_tool('same_energy_task',{'task_id':ident})
            if isinstance(read,tuple):read=read[0]
            self.assertFalse(json.loads(read[0].text)['ready'])
            with patch('same_energy_mcp.server.client',return_value=client):
                for tool,args in [('same_energy_search_by_text',{'query':'already supplied'}),('same_energy_search_by_image',{'image_path':'/not-authorized.jpg'})]:
                    response=await mcp.call_tool(tool,args)
                    if isinstance(response,tuple):response=response[0]
                    menu=json.loads(response[0].text)
                    self.assertTrue(menu['requires_guided_setup']);self.assertEqual(len(menu['options']),3)
            client.search_text.assert_not_awaited();client.search_image.assert_not_awaited()
        finally:await client.close()


class WorkflowBrowserTests(WorkflowFixture,unittest.TestCase):
    def setUp(self):
        super().setUp();self.server=make_server(('127.0.0.1',0));self.server.public_port=self.server.server_port
        self.port_env=patch.dict(os.environ,{'SAME_ENERGY_CATALOG_PORT':str(self.server.server_port)});self.port_env.start()
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.port_env.stop();super().tearDown()

    def test_browser_all_branches_photo_description_back_and_mobile(self):
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            for mode in PATHS:
                for kind in ['text','image']:
                    with self.subTest(mode=mode,kind=kind):
                        view=self.store.new();page=browser.new_page(viewport={'width':390 if kind=='image' else 1440,'height':900})
                        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                        page.goto(view['url']);expect(page.locator('.option')).to_have_count(3)
                        for choice in [*PATHS[mode],kind]:
                            task=self.store.view(self.store.task(view['task_id']));label=next(x['label'] for x in task['options'] if x['value']==choice)
                            page.get_by_role('button',name=label,exact=False).click()
                            expect(page.locator('#title')).to_have_text(self.store.view(self.store.task(view['task_id']))['question'])
                        expect(page.locator('#brief')).to_be_visible()
                        if kind=='text':
                            page.locator('#description').fill('blue shadows and warm highlights' if mode.startswith('color') else 'urban commercial portrait')
                            if mode=='color_theme':page.locator('#theme').fill('urban portrait')
                        else:
                            page.locator('#photo').set_input_files(str(self.photo));page.locator('#consent').check()
                        page.get_by_role('button',name='Concluir orientação').click();expect(page.locator('#ready')).to_be_visible()
                        self.assertEqual(profile(self.store.ready(view['task_id']))['mode'],mode)
                        self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth'));self.assertEqual(errors,[])
                        page.get_by_role('button',name='Voltar',exact=False).click();expect(page.locator('#brief')).to_be_visible()
                        self.assertFalse(self.store.view(self.store.task(view['task_id']))['ready'])
                        if mode=='color_only' and kind=='image':
                            for _ in range(2):
                                with page.expect_response(lambda r:r.url.endswith('/choose')):
                                    page.get_by_role('button',name='Voltar',exact=False).click()
                            for label in ['Color e temática','Enviar foto']:
                                with page.expect_response(lambda r:r.url.endswith('/choose')):
                                    page.get_by_role('button',name=label,exact=False).click()
                            expect(page.locator('#brief')).to_be_visible()
                            self.assertFalse(page.locator('#consent').is_checked())
                        page.close()
            browser.close()

    def test_http_capability_csrf_bad_bytes_and_paths_do_not_create_inputs(self):
        view=self.store.new();url=view['url'];origin=f'http://127.0.0.1:{self.server.server_port}'
        with httpx.Client(timeout=10,trust_env=False) as http:
            self.assertEqual(http.post(url+'choose',json={'choice':'reference'}).status_code,403)
            self.assertEqual(http.get(url+'api',headers={'Host':'evil.example'}).status_code,403)
            wrong=url.replace(url.split('/')[5],'0'*48)
            self.assertNotEqual(http.get(wrong+'api').status_code,200)
            for choice in ['reference','image']:
                result=http.post(url+'choose',json={'choice':choice},headers={'Origin':origin,'X-Guide-Action':'edit'})
                self.assertEqual(result.status_code,200)
            headers={'Origin':origin,'X-Guide-Action':'edit'}
            for data in [{'image_path':'/etc/passwd','input_authorized':True},{'image_base64':'<not base64>','input_authorized':True},{'image_base64':base64.b64encode(b'<html>no photo</html>').decode(),'input_authorized':True}]:
                self.assertEqual(http.post(url+'submit',json=data,headers=headers).status_code,400)
            self.assertFalse((self.root/'.same-energy-inputs').exists())
