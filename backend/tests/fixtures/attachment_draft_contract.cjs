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
  async put(key, scope, file){const hash=file.hash || 'd'.repeat(64);files.set(key+':'+hash,{scope,file});return {file_sha256:hash,file_name:file.name,file_type:'image/png',file_last_modified:'1'};},
  async get(key,scope,values,matches){const item=files.get(key+':'+values.file_sha256);assert(matches(scope,item.scope));return item.file;},
  async remove(key,hash){for(const k of files.keys())if(hash?k===key+':'+hash:k.startsWith(key+':'))files.delete(k);},
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
  const originalSet=storage.setItem;
  storage.setItem=()=>{throw Error('quota');};
  await assert.rejects(api.retain(scope,ref,values,{name:'replacement.png',hash:'e'.repeat(64)}));
  assert.equal(files.size,1,'failed metadata publication must remove only the new blob');
  await assert.rejects(api.retain(scope,ref,values,file));
  assert.equal(files.size,1,'same-hash failure must retain the previous valid blob');
  storage.setItem=originalSet;
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
  api.store.save(scope,ref,'blocked',first.record.values);
  const proof={scope,clientRef:ref,values:first.record.values,serverResult:'rejected'};
  const originalRemove=window.TicketboxDraftFiles.remove;
  assert.equal(await api.discardRejected({...proof,serverResult:'unknown'}),false);
  assert.equal(await api.discardRejected({...proof,values:{...proof.values,request_id:'other'}}),false);
  assert.equal(files.size,1);
  window.TicketboxDraftFiles.remove=async()=>{throw Error('IDB unavailable');};
  await assert.rejects(api.discardRejected(proof));
  assert.equal(api.store.read(ref)?.phase,'blocked','failed blob deletion must preserve retry metadata');
  assert.equal(files.size,1);
  window.TicketboxDraftFiles.remove=originalRemove;
  assert.equal(await api.discardRejected(proof),true);
  assert.equal(api.store.read(ref),null);
  assert.equal(files.size,0);
  await api.retain(scope,ref,values,file);
  // A proof from the old rejected attempt cannot discard a new editing intent.
  assert.equal(await api.discardRejected(proof),false);
  assert.equal(files.size,1);
  await api.submitted(scope,ref);
  window.TicketboxDraftFiles.remove=async()=>{throw Error('cleanup failed after ACK');};
  await assert.rejects(api.acknowledge({scope,clientRef:ref}));
  assert.equal(api.store.read(ref),null);
  await assert.rejects(api.submitted(scope,ref));
  console.log('attachment intent: original bytes/key/OCC, 5-axis fence, blocked retry, ACK cleanup failure passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
