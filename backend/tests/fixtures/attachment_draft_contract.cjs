const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = process.argv[2];
const records = new Map();
const files = new Map();
const storage = {get length(){return records.size;}, key:i=>[...records.keys()][i],
  getItem:k=>records.get(k)??null, setItem:(k,v)=>records.set(k,v), removeItem:k=>records.delete(k)};
const window = {localStorage:storage, location:{href:'https://local/web/pending',origin:'https://local'}, TicketboxDraftFiles:{
  async put(key, scope, file){files.set(key,{scope,file});return {file_sha256:'d'.repeat(64),file_name:file.name,file_type:'image/png',file_last_modified:'1'};},
  async get(key,scope,values,matches){const item=files.get(key);assert(matches(scope,item.scope));return item.file;},
  async remove(key){files.delete(key);},
}};
for(const file of ['manual-drafts.js','attachment-drafts.js']) vm.runInNewContext(fs.readFileSync(path.join(root,file),'utf8'),{window,URL});
const api=window.TicketboxAttachmentDrafts;
const scope={datasetId:'d',clientGeneration:'g',accountId:'a',ledgerId:'l',deviceId:'device'};
const ref='a'.repeat(32);
const query=new URLSearchParams({ledger_id:scope.ledgerId,idempotency_key:ref,draft_scope:JSON.stringify(scope),expected_row_version:'3'});
const values={action:'https://local/web/expenses/7/original/replenish?'+query,
  reviewed_sha256:'',request_id:'',file_sha256:'',file_name:'',file_type:'',file_last_modified:''};
(async()=>{
  const file={name:'original.png',bytes:Buffer.from('original file')};
  await api.retain(scope,ref,values,file);
  const first=await api.submitted(scope,ref);
  assert.equal(first.file,file);
  assert.equal(first.record.values.action,values.action);
  await assert.rejects(api.retain(scope,ref,values,{name:'different.png'}));
  api.store.save(scope,ref,'blocked',first.record.values);
  const replay=await api.submitted(scope,ref);
  assert.equal(replay.file,file);
  for(const axis of Object.keys(scope)) {
    await assert.rejects(api.submitted({...scope,[axis]:'changed'},ref));
    assert.equal(await api.acknowledge({scope:{...scope,[axis]:'changed'},clientRef:ref}),false);
    assert.equal(files.size,1);
  }
  window.TicketboxDraftFiles.remove=async()=>{throw Error('cleanup failed after ACK');};
  await assert.rejects(api.acknowledge({scope,clientRef:ref}));
  assert.equal(api.store.read(ref),null);
  await assert.rejects(api.submitted(scope,ref));
  console.log('attachment intent: original bytes/key/OCC, 5-axis fence, blocked retry, ACK cleanup failure passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
