"""Actual Chromium smoke: uses temporary credentials/cache, real bundled prices."""
import os,sys,time,json,tempfile,subprocess,urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright
root=Path(__file__).resolve().parents[2];out=Path(os.getenv('QTA_BROWSER_OUTPUT','/tmp/qta8-browser'));out.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory() as tmp:
    env={**os.environ,'QTA_PRICE_DB':str(root/'data/state/qta_phase3_test.db'),'QTA_AUTH_DB':tmp+'/auth.db','QTA_USER_DB':tmp+'/users.db','QTA8_CACHE':tmp+'/cache.db','QTA8_RESEARCH_DB':tmp+'/research.db'}
    with (out/'server.log').open('w') as log:
        server=subprocess.Popen([sys.executable,'-m','uvicorn','src.web.app:app','--host','127.0.0.1','--port','8768'],cwd=root,env=env,stdout=log,stderr=log)
        try:
            for _ in range(100):
                try:urllib.request.urlopen('http://127.0.0.1:8768/login');break
                except Exception:time.sleep(.2)
            with sync_playwright() as p:
                browser=p.chromium.launch(headless=True,args=['--no-sandbox']);ctx=browser.new_context(viewport={'width':1440,'height':1000},accept_downloads=True);page=ctx.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)));url='http://127.0.0.1:8768'
                assert ctx.request.get(url+'/api/p8/dashboard').status==401
                creds={'username':'phase8tester','password':'qta8-test-password-123'}
                assert ctx.request.post(url+'/api/auth/register',data=creds).status==201;assert ctx.request.post(url+'/api/auth/login',data=creds).status==200
                def done():page.wait_for_function('jobs.size===0',timeout=120000)
                page.goto(url+'/phase8');page.wait_for_function("document.querySelectorAll('#rows tr').length===407",timeout=120000);done();page.screenshot(path=str(out/'dashboard.png'),full_page=True)
                page.locator('#search').fill('HPG');assert page.locator('#rows tr').count()==1;page.locator('#rows button').click();assert page.locator('#why').is_visible();assert 'HPG' in page.locator('#why-title').inner_text();page.locator('#why form button').click()
                page.reload();page.wait_for_function("document.querySelectorAll('#rows tr').length===1",timeout=120000);assert page.locator('#search').input_value()=='HPG'
                page.locator('[data-tab=research]').click();page.locator('#run').click();done();assert 'Chưa đủ bằng chứng' in page.locator('#research-result').inner_text();assert '873' in page.locator('#research-result').inner_text();page.screenshot(path=str(out/'research.png'),full_page=True)
                page.locator('[data-tab=health]').click();page.locator('#health-run').click();done();assert '407' in page.locator('#health-summary').inner_text()
                with page.expect_download() as download:page.get_by_text('Xuất báo cáo CSV',exact=True).click()
                download.value.save_as(str(out/'health.csv'));assert (out/'health.csv').stat().st_size>1000
                page.locator('[data-tab=execution]').click();page.locator('#exec-run').click();done();assert 'BLOCKED' in page.locator('#execution-result').inner_text()
                page.locator('#theme').click();assert page.locator('html').get_attribute('data-theme')=='light'
                page.locator('[data-tab=scan]').click();page.locator('#search').fill('');page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(out/'mobile.png'),full_page=False);assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth+2');assert not errors,errors
                r={'status':'passed','engine':browser.version,'desktop':'1440x1000','mobile':'390x844','page_errors':errors,'checks':['authentication','407-symbol scan','filter persistence','why dialog','pooled OOS','health','CSV download','strict execution blocked','theme','mobile overflow']};(out/'result.json').write_text(json.dumps(r,indent=2));print(json.dumps(r));browser.close()
        finally:server.terminate();server.wait(timeout=10)
