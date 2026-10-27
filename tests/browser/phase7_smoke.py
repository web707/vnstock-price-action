"""Run at project root: python tests/browser/phase7_smoke.py (Playwright Chromium required)."""
import os,sys,time,json,tempfile,subprocess,urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright
root=Path(__file__).resolve().parents[2];price=os.getenv('QTA_PRICE_DB',str(root/'data/state/qta_phase3_test.db'));out=Path(os.getenv('QTA_BROWSER_OUTPUT',str(Path(tempfile.gettempdir())/'qta7-browser')));out.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory() as temp:
    env={**os.environ,'QTA_PRICE_DB':price,'QTA_AUTH_DB':temp+'/auth.db','QTA_USER_DB':temp+'/users.db'}
    log=(out/'server.log').open('w');proc=subprocess.Popen([sys.executable,'-m','uvicorn','src.web.app:app','--host','127.0.0.1','--port','8767'],cwd=root,env=env,stdout=log,stderr=log)
    try:
        for _ in range(100):
            try:urllib.request.urlopen('http://127.0.0.1:8767/login');break
            except Exception:time.sleep(.2)
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,args=['--no-sandbox']);context=browser.new_context(viewport={'width':1440,'height':1000},accept_downloads=True);page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            data={'username':'phase7tester','password':'safe-test-pass-123'};assert context.request.post('http://127.0.0.1:8767/api/auth/register',data=data).status==201;assert context.request.post('http://127.0.0.1:8767/api/auth/login',data=data).status==200
            def complete():
                page.wait_for_function('jobs.size===0',timeout=120000)
                assert 'error' not in page.locator('#status').get_attribute('class'),page.locator('#status').inner_text()
            page.goto('http://127.0.0.1:8767/phase7');page.wait_for_function("document.querySelectorAll('#market-table tbody tr').length>0",timeout=120000);complete();page.screenshot(path=str(out/'overview.png'),full_page=True)
            page.locator('#filter-search').fill('HPG');assert page.locator('#market-table tbody tr').count()==1;page.locator('#save-filters').click();complete();page.reload();page.wait_for_function("document.querySelectorAll('#market-table tbody tr').length===1",timeout=120000);assert page.locator('#filter-search').input_value()=='HPG'
            page.locator('#market-table .linkbutton').click();complete();assert 'HPG' in page.locator('#detail-summary').inner_text();page.locator('#chart').hover();page.mouse.wheel(0,100);page.screenshot(path=str(out/'study.png'),full_page=True)
            page.locator('#add-watch').click();complete();assert 'HPG' in page.locator('#watch-result').inner_text()
            page.locator('nav button[data-tab="model"]').click();page.locator('#model-run').click();complete();assert 'CHUA_CO_BANG_CHUNG' in page.locator('#model-result').inner_text() or 'INSUFFICIENT_DATA' in page.locator('#model-result').inner_text()
            page.locator('nav button[data-tab="portfolio"]').click();page.locator('#portfolio-run').click();page.wait_for_function('jobs.size===0',timeout=30000);assert 'STRICT' in page.locator('#status').inner_text()
            page.locator('#portfolio-approx').check();page.locator('#portfolio-run').click();complete();assert 'APPROXIMATE_RESEARCH' in page.locator('#portfolio-result').inner_text()
            page.locator('nav button[data-tab="personal"]').click();complete();page.locator('#poll').click();complete()
            for name,value in {'entry_date':'2026-10-20','entry':'25000','qty':'100','exit_date':'2026-10-21','exit':'26000','costs':'10000','notes':'browser smoke test'}.items():page.locator(f'#journal-form [name="{name}"]').fill(value)
            page.locator('#journal-form button').click();complete();assert 'browser smoke test' in page.locator('#journal-result').inner_text()
            page.locator('nav button[data-tab="health"]').click();page.locator('#health-run').click();complete();assert 'UNVERIFIED' in page.locator('#health-result').inner_text()
            page.locator('nav button[data-tab="study"]').click();page.locator('#compare-run').click();complete();assert 'HPG' in page.locator('#compare-result').inner_text()
            with page.expect_download(timeout=30000) as d:page.get_by_role('button',name='PDF mã',exact=True).click()
            d.value.save_as(str(out/'symbol.pdf'));complete()
            page.locator('#theme').click();assert page.locator('html').get_attribute('data-theme')=='light'
            page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(out/'mobile.png'),full_page=True);assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth+2')
            assert not errors,errors
            result={'status':'passed','desktop':'1440x1000','mobile':'390x844','checks':['API authentication','market snapshot','filters and persistence','candlestick zoom','watchlist','walk-forward sensitivity','strict gate','approximate portfolio','journal','alerts poll','data health','compare','PDF download','theme','mobile overflow'],'page_errors':errors};(out/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result));browser.close()
    finally:proc.terminate();proc.wait(timeout=10);log.close()
