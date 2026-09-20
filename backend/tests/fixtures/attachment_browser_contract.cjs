/* Standalone real-browser companion to the Node and HTTP adapter tests.
 * Run with an installed Playwright module and CHROME_EXECUTABLE if needed. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const {chromium} = require(process.env.TICKETBOX_PLAYWRIGHT_MODULE || 'playwright');
const root = process.argv[2];
const scope = {datasetId:'d',clientGeneration:'g',accountId:'a',ledgerId:'owner',deviceId:'device'};
const receipt = new Map();
const attempts = [];
let serial = 0;
let mode = 'success';
let device = 'device';
function page() {
  const ref = (++serial).toString(16).padStart(32,'0');
  const query = new URLSearchParams({ledger_id:'owner',idempotency_key:ref,draft_scope:JSON.stringify({...scope,deviceId:device})});
  return `<!doctype html><html><head><meta charset='utf-8'></head><body><form data-inbox-capture data-attachment-scope='${JSON.stringify({...scope,deviceId:device})}'
    data-attachment-ref='${ref}' action='/web/pending/upload?${query}' method='post' enctype='multipart/form-data'>
    <input name='csrf_token' value='synthetic-csrf' type='hidden'><input name='file' type='file' required>
    <button type='submit'>上传小票</button><p data-attachment-status></p></form><section data-attachment-shelf></section>
    ${['manual-drafts','manual-draft-files','attachment-drafts','attachment-entry'].map(s=>`<script data-upload-max-bytes='1024' src='/static/${s}.js'></script>`).join('')}
    </body></html>`;
}
const imageBytes=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jS1sAAAAASUVORK5CYII=','base64');
function reviewPage() {
  const ref='b'.repeat(32);
  const query=new URLSearchParams({ledger_id:'owner',idempotency_key:ref,draft_scope:JSON.stringify(scope),expected_row_version:'7'});
  return `<!doctype html><meta charset='utf-8'><button data-original-preview data-image-href='/image'>打开实际原图</button>
    <p data-original-preview-status></p><img data-original-reviewed-image hidden>
    <form action='/web/expenses/17/original/verify?${query}' data-original-verification data-attachment-scope='${JSON.stringify(scope)}' data-attachment-ref='${ref}'>
    <input name='csrf_token' value='synthetic'><input type='hidden' name='reviewed_sha256' value=''>
    <input type='checkbox' data-original-reviewed disabled required><button type='submit' disabled>确认所见原件</button>
    <p data-attachment-status></p></form><section data-attachment-shelf></section>
    ${['manual-drafts','manual-draft-files','attachment-drafts','attachment-entry','originals'].map(s=>`<script data-upload-max-bytes='1024' src='/static/${s}.js'></script>`).join('')}`;
}
const server = http.createServer(async (req,res)=>{
  const url = new URL(req.url,'http://127.0.0.1');
  if(url.pathname.startsWith('/static/')) {
    res.setHeader('Content-Type','text/javascript; charset=utf-8');
    return res.end(fs.readFileSync(path.join(root,path.basename(url.pathname))));
  }
  if(url.pathname==='/image'){res.writeHead(200,{'Content-Type':'image/png','ETag':'"'+'e'.repeat(64)+'"'});return res.end(imageBytes);}
  if(url.pathname==='/review'){res.setHeader('Content-Type','text/html; charset=utf-8');return res.end(reviewPage());}
  if(req.method==='GET') {res.setHeader('Content-Type','text/html; charset=utf-8');return res.end(page());}
  const chunks=[];for await(const chunk of req)chunks.push(chunk);
  const body=Buffer.concat(chunks);
  const parsed=await new Request('http://localhost/',{method:'POST',headers:req.headers,body}).formData();
  const file=parsed.get('file');
  const intent={key:url.searchParams.get('idempotency_key'),query:url.search,
    name:file.name,type:file.type,bytes:Buffer.from(await file.arrayBuffer()).toString('hex')};
  attempts.push(intent);
  if(['conflict','mismatch','not-needed'].includes(mode)){res.writeHead(409,{'Content-Type':'application/json'});return res.end(JSON.stringify({error:mode==='conflict'?'state_conflict':mode==='mismatch'?'image_replenishment_mismatch':'original_replenishment_not_needed',message:'版本已更新'}));}
  if(!receipt.has(intent.key))receipt.set(intent.key,{id:17,enrichment_task_public_id:'durable-task'});
  res.setHeader('Content-Type','application/json');
  res.end(JSON.stringify({ack:{scope:JSON.parse(url.searchParams.get('draft_scope')),clientRef:intent.key},
    receipt:receipt.get(intent.key),next:'/web/pending?accepted=1'}));
});
let browser;
(async()=>{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const origin=`http://127.0.0.1:${server.address().port}`;
  browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_EXECUTABLE});
  const context=await browser.newContext();
  const tab=await context.newPage();
  tab.setDefaultTimeout(8000);
  tab.on('pageerror',error=>console.error('BROWSER',error.message));
  await tab.goto(origin+'/web/pending');
  await tab.waitForFunction(()=>!document.querySelector('button').disabled);
  const file={name:'original.png',mimeType:'image/png',buffer:Buffer.from('exact original file bytes')};
  await tab.setInputFiles('input[type=file]',file);
  await tab.waitForFunction(()=>document.querySelector('[data-attachment-status]').textContent.includes('已保留'));
  const originalURL=tab.url();
  // Metadata publication failure compensates only the new digest's blob.
  await tab.evaluate(async () => {
    const api=window.TicketboxAttachmentDrafts, ref=location.hash.slice(12);
    const record=api.store.read(ref), original=Storage.prototype.setItem;
    Storage.prototype.setItem=()=>{throw Error('quota');};
    try {await api.retain(record.scope,ref,record.values,new File(['different'], 'new.png'));}
    catch (_) {} finally {Storage.prototype.setItem=original;}
  });
  async function blobCount(page) {
    return page.evaluate(()=>new Promise((resolve,reject)=>{
      const r=indexedDB.open('ticketbox-draft-files',1);
      r.onsuccess=()=>{const db=r.result;const q=db.transaction('files').objectStore('files').count();
        q.onsuccess=()=>{resolve(q.result);db.close();};q.onerror=()=>reject(q.error);};
    }));
  }
  assert.equal(await blobCount(tab),1,'metadata failure leaves no orphan blob');
  await tab.reload();
  await tab.waitForFunction(()=>document.querySelector('[data-attachment-status]').textContent.includes('已恢复'));
  assert.equal(await tab.locator('input[type=file]').inputValue(),'');
  await context.setOffline(true);
  await tab.click('button[type=submit]');
  await tab.waitForFunction(()=>document.querySelector('[data-attachment-status]').textContent.includes('暂未收到'));
  assert.equal(attempts.length,0);
  assert.equal(await tab.locator('[data-attachment-discard]').isVisible(),false,'unknown result cannot discard');
  await context.setOffline(false);
  let drop=true;
  await tab.route('**/web/pending/upload?**',async route=>{
    if(drop){drop=false;await route.fetch();await route.abort('failed');}
    else await route.continue();
  });
  await tab.click('button[type=submit]');
  await tab.waitForFunction(()=>document.querySelector('[data-attachment-status]').textContent.includes('暂未收到'));
  await tab.waitForFunction(()=>!document.querySelector('button').disabled);
  assert.equal(receipt.size,1);
  assert.equal(attempts[0].bytes,file.buffer.toString('hex'));
  await tab.reload();
  await tab.waitForFunction(()=>document.querySelector('[data-attachment-status]').textContent.includes('已恢复'));
  await tab.click('button[type=submit]');
  await tab.waitForURL('**/web/pending?accepted=1');
  assert.equal(receipt.size,1);assert.deepEqual(attempts[0],attempts[1]);
  await tab.goBack();
  await tab.waitForFunction(()=>document.querySelector('[data-attachment-status]').textContent.includes('已收起'));
  assert.equal(await tab.locator('button[type=submit]').isDisabled(),true);
  await tab.goto(originalURL);
  await tab.waitForFunction(()=>document.querySelector('[data-attachment-status]').textContent.includes('已收起'));
  assert.equal(await tab.locator('button[type=submit]').isDisabled(),true);
  // OCC refusal keeps the Blob and the original URL/key, including after reload.
  mode='conflict';await tab.goto(origin+'/web/pending');
  await tab.waitForFunction(()=>!document.querySelector('button').disabled);
  await tab.setInputFiles('input[type=file]',file);
  await tab.waitForFunction(()=>document.querySelector('[data-attachment-status]').textContent.includes('已保留'));
  const conflictURL=tab.url();await tab.click('button[type=submit]');
  await tab.waitForFunction(()=>document.querySelector('[data-attachment-status]').textContent.includes('版本已更新'));
  await tab.reload();await tab.waitForFunction(()=>document.querySelector('[data-attachment-status]').textContent.includes('已恢复'));
  assert.equal(await tab.locator('input[type=file]').isDisabled(),true);
  await tab.click('button[type=submit]');await tab.waitForFunction(()=>document.querySelector('[data-attachment-status]').textContent.includes('版本已更新'));
  assert.deepEqual(attempts[2],attempts[3]);
  device='other-device';await tab.reload();
  await tab.waitForFunction(()=>document.querySelector('[data-attachment-status]').textContent.includes('旧身份'));
  assert.equal(await tab.locator('button[type=submit]').isDisabled(),true);
  assert.equal(await tab.evaluate(()=>window.TicketboxAttachmentDrafts.store.read(location.hash.slice(12)).values.file_name),'original.png');
  device='device';await tab.reload();
  await tab.waitForFunction(()=>document.querySelector('[data-attachment-status]').textContent.includes('已恢复'));
  await tab.click('button[type=submit]');
  await tab.waitForFunction(()=>document.querySelector('[data-attachment-status]').textContent.includes('版本已更新'));
  const discardButton=tab.locator('[data-attachment-discard]');
  assert.equal(await discardButton.isVisible(),true,'deterministic refusal offers discard');
  tab.once('dialog',dialog=>dialog.dismiss());await discardButton.click();
  assert.equal(await blobCount(tab),1,'cancel preserves blob');
  tab.once('dialog',dialog=>dialog.accept());await discardButton.click();
  await tab.waitForFunction(()=>document.querySelector('[data-attachment-status]').textContent.includes('已丢弃'));
  assert.equal(await blobCount(tab),0,'confirmed refusal discard removes blob');
  assert.equal(await tab.evaluate(()=>window.TicketboxAttachmentDrafts.store.read(location.hash.slice(12))),null);
  const oversized=await context.newPage();await oversized.goto(origin+'/web/pending');
  await oversized.waitForFunction(()=>!document.querySelector('button').disabled);
  await oversized.evaluate(()=>{window.readCount=0;File.prototype.arrayBuffer=()=>{window.readCount++;throw Error('must not read');};});
  await oversized.setInputFiles('input[type=file]',{name:'large.png',mimeType:'image/png',buffer:Buffer.alloc(1025)});
  await oversized.waitForFunction(()=>document.querySelector('[data-attachment-status]').textContent.includes('超过服务器上传上限'));
  assert.equal(await oversized.evaluate(()=>window.readCount),0);
  assert.equal(await oversized.locator('button[type=submit]').isDisabled(),true);
  await oversized.close();
  for (const refusal of ['mismatch','not-needed']) {
    mode=refusal;await tab.goto(origin+'/web/pending');
    await tab.waitForFunction(()=>!document.querySelector('button').disabled);
    await tab.setInputFiles('input[type=file]',file);
    await tab.waitForFunction(()=>document.querySelector('[data-attachment-status]').textContent.includes('已保留'));
    await tab.click('button[type=submit]');
    await tab.waitForFunction(()=>!document.querySelector('[data-attachment-discard]').hidden);
    tab.once('dialog',dialog=>dialog.accept());await tab.locator('[data-attachment-discard]').click();
    await tab.waitForFunction(()=>document.querySelector('[data-attachment-status]').textContent.includes('已丢弃'));
    assert.equal(await blobCount(tab),0);
  }
  // Unavailable IndexedDB does not remove the original online native upload.
  device='device';mode='success';const fallback=await context.newPage();
  await fallback.addInitScript(()=>Object.defineProperty(window,'indexedDB',{value:undefined}));
  await fallback.goto(origin+'/web/pending');
  await fallback.waitForFunction(()=>document.querySelector('[data-attachment-status]').textContent.includes('仍可在本页在线提交'));
  await fallback.setInputFiles('input[type=file]',file);
  await fallback.click('button[type=submit]');await fallback.waitForURL('**/web/pending/upload?**');
  assert.equal(attempts.at(-1).bytes,file.buffer.toString('hex'));
  assert(attempts.at(-1).key);
  const denied=await context.newPage();
  await denied.addInitScript(()=>Object.defineProperty(window,'localStorage',{
    get(){throw new DOMException('Storage unavailable','SecurityError');}}));
  await denied.goto(origin+'/web/pending');
  await denied.waitForFunction(()=>document.querySelector('[data-attachment-status]').textContent.includes('仍可在本页在线提交'));
  await denied.setInputFiles('input[type=file]',file);
  await denied.click('button[type=submit]');await denied.waitForURL('**/web/pending/upload?**');
  assert.equal(attempts.at(-1).bytes,file.buffer.toString('hex'));
  assert(attempts.at(-1).key);
  const beforeDeniedRecovery=attempts.length;
  await denied.goto(conflictURL);
  await denied.waitForFunction(()=>document.querySelector('[data-attachment-status]').textContent.includes('不能安全恢复'));
  assert.equal(await denied.locator('button[type=submit]').isDisabled(),true);
  assert.equal(attempts.length,beforeDeniedRecovery);
  const review=await context.newPage();await review.goto(origin+'/review');
  assert.equal(await review.locator('[data-original-reviewed]').isDisabled(),true);
  assert.equal(await review.locator('[name=reviewed_sha256]').inputValue(),'');
  await review.click('[data-original-preview]');
  await review.waitForFunction(()=>!document.querySelector('[data-original-reviewed]').disabled);
  assert.equal(await review.locator('[name=reviewed_sha256]').inputValue(),'');
  await review.check('[data-original-reviewed]');
  await review.waitForFunction(()=>document.querySelector('[data-attachment-status]').textContent.includes('已保留'));
  assert.equal(await review.locator('[name=reviewed_sha256]').inputValue(),'e'.repeat(64));
  assert.equal(await review.locator('[data-original-reviewed-image]').evaluate(img=>img.naturalWidth),1);
  console.log('PASS real Chromium: IndexedDB Blob reload; offline/ACK-loss original replay; one accepted receipt; OCC file retention; changed device fence; storage-unavailable native upload');
  console.log('PASS real Chromium: failed metadata blob compensation; state conflict/mismatch/not-needed confirmed discard; unknown outcome retained; configured size rejects before arrayBuffer');
  console.log('PASS real Chromium: legacy verification empty until actual snapshot decoded and user checked; digest bound to response ETag');
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();server.close();});
