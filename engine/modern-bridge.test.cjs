const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm');
const {readFileSync}=require('node:fs'),{webcrypto,createHash}=require('node:crypto');
const source=readFileSync(__dirname+'/modern-bridge.js','utf8');
async function setup(observer=true) {
  const calls=[],events={},files=new Map([['civ2/TUTORIAL.SAV',new Uint8Array([1,2,3])],['civ2/CIV2.EXE',new Uint8Array([4,5])],['CIV2OBS.EXE',new Uint8Array([6,7])]]);
  const canvas={width:640,height:480,addEventListener(){},getContext(){return {putImageData(image){calls.push(['paint',image]);}};},toDataURL(){return 'data:image/png;base64,original';}};
  const ci={events(){return {onFrameSize:f=>events.size=f,onFrame:f=>events.frame=f,onExit:f=>events.exit=f};},
    pause(){calls.push(['pause']);},resume(){calls.push(['resume']);},
    sendKeyEvent(k,d){calls.push(['key',k,d]);if(ci.failKey===k&&d)throw Error('key rejected');},
    sendMouseMotion(x,y){calls.push(['absolute',x,y]);},sendMouseRelativeMotion(x,y){calls.push(['relative',x,y]);},sendMouseButton(b,d){calls.push(['button',b,d]);},
    async fsTree(){calls.push(['tree']);const nodes=[{name:'civ2',nodes:[]}];for(const [p,b]of files){const n={name:p.split('/').at(-1),nodes:null,size:b.length};if(p.startsWith('civ2/'))nodes[0].nodes.push(n);else nodes.push(n);}return {name:'.',nodes};},
    async fsReadFile(p){calls.push(['read',p]);if(!files.has(p))throw Error('missing');return new Uint8Array(files.get(p));},
    async fsWriteFile(p,b){calls.push(['write',p]);files.set(p,new Uint8Array(b));structuredClone(b,{transfer:[b.buffer]});}};
  const context={URL,URLSearchParams,Uint8Array,Uint8ClampedArray,TextEncoder,Date,Promise,setTimeout,clearTimeout,crypto:webcrypto,
    ImageData:class{constructor(data,width,height){Object.assign(this,{data,width,height});}},
    document:{currentScript:{src:'http://127.0.0.1:3920/engine/modern-bridge.js'},querySelector:()=>canvas},
    emulators:{version:'8.4.2 (7fb80db8afda9ca5cde776abb7313545)',async dosboxWorker(init){calls.push(['boot',init]);for(const n of init)if(n.path)files.set(n.path,new Uint8Array(n.contents));setTimeout(()=>{events.size(640,480);events.frame(new Uint8Array(640*480*3),null);},1);return ci;}},
    fetch:async()=>({ok:true,arrayBuffer:async()=>new ArrayBuffer(1000001)})};
  context.window=context;vm.createContext(context);vm.runInContext(source,context);await context.Civ2Runtime.boot({observer});
  return {api:context.Civ2Runtime,context,calls,files,ci,events,canvas};
}
test('boots pinned worker once, seeds only helper mailboxes, pause fences are idempotent',async()=>{
  const {api,calls,files}=await setup();await api.boot({observer:true});assert.equal(calls.filter(x=>x[0]==='boot').length,1);
  assert.equal(files.get('OBSREQ.TXT').length,128);assert.equal(files.get('OBSRESP.BIN').length,524288);
  assert.equal(calls[0][1].find(x=>x.dosboxConf).dosboxConf.includes('cycles=auto'),true);
  await api.pause();await api.pause();await api.resume();await api.resume();
  assert.equal(calls.filter(x=>x[0]==='pause').length,1);assert.equal(calls.filter(x=>x[0]==='resume').length,1);
  assert.equal(api.status().paused,false);assert.equal(api.status().runtime,'js-dos/8.4.2/Win3.1');
});
test('pause waits for the original late frame from an already queued worker wake-up',async()=>{
  const {api,ci,events}=await setup();let replies=0,releaseFirst,releaseSecond;
  ci.fsTree=()=>new Promise(resolve=>{replies++;if(replies===1)releaseFirst=resolve;else releaseSecond=resolve;});
  let completed=false;const waiting=api.pause().then(value=>{completed=true;return value;});
  assert.equal(replies,1);assert.equal(api.status().paused,false);
  // ws-sync-sleep was posted before wc-pause. Its wc-sync-sleep reply can sit
  // behind the first tree request, so that response alone is not a frame fence.
  releaseFirst({});await new Promise(resolve=>setImmediate(resolve));
  assert.equal(completed,false);assert.equal(replies,2);
  const before=api.status().frames;events.frame(new Uint8Array(640*480*3).fill(17),null);
  releaseSecond({});const fenced=await waiting;
  assert.equal(fenced.frames,before+1);assert.equal(fenced.paused,true);
  assert.equal(fenced.pauseFence,'worker-two-roundtrips-v1');
  await api.pause();assert.equal(replies,2,'a completed fence stays idempotent');
});
test('physical code mapping and chord cleanup use actual modern enum',async()=>{
  const {api,calls,ci}=await setup();await api.chord(['ControlLeft','KeyS'],{holdMs:1});
  assert.deepEqual(calls.filter(x=>x[0]==='key'),[['key',341,true],['key',83,true],['key',83,false],['key',341,false]]);
  await api.key('Enter',{holdMs:1});assert.deepEqual(calls.at(-2),['key',257,true]);
  ci.failKey=83;await assert.rejects(api.chord(['ShiftLeft','KeyS'],{holdMs:1}));assert.equal(api.status().heldKeys.length,0);
  assert.throws(()=>api.keyDown('constructor'),/Unsupported/);await assert.rejects(api.chord(['KeyA','KeyB']));
});
test('feedback click buttons introduce no extra motion and relative deltas stay bounded',async()=>{
  const {api,calls}=await setup();api.moveRelative(5,-7);api.mouse({type:'mousedown',x:0,y:0,button:2});api.mouse({type:'mouseup',x:0,y:0,button:2});
  assert.deepEqual(calls.filter(x=>['relative','button','absolute'].includes(x[0])),[['relative',5,-7],['button',1,true],['button',1,false]]);
  assert.equal(api.inputDiagnostics().sdlMouse,null);assert.equal(api.inputDiagnostics().hostMouse.source,'js-dos adapter input bookkeeping');
  for(const pair of [[0,0],[33,0],[0,-33],[.5,1],[true,1]])assert.throws(()=>api.moveRelative(...pair));
  assert.equal(api.status().buttons,0);
});
test('frame capture copies original RGB rows and refuses absent or malformed frames',async()=>{
  const {api,events,calls}=await setup();assert.equal(api.capture(),'data:image/png;base64,original','boot waits for a real frame');
  events.size(2,1);events.frame(new Uint8Array([1,2,3,4,5,6]),null);
  assert.deepEqual([...calls.filter(x=>x[0]==='paint').at(-1)[1].data],[1,2,3,255,4,5,6,255]);assert.equal(api.capture(),'data:image/png;base64,original');
  const count=api.status().frames;events.frame(new Uint8Array([1]),null);assert.equal(api.status().frames,count);
});
test('observer fixed paths preserve input sequence and validate size/provenance',async()=>{
  const {api,calls,files}=await setup();const seq=api.status().inputSequence;
  const r=await api.observerRequest('a'.repeat(32));assert.equal(r.gameInput,false);assert.equal(r.inputSequence,seq);
  assert.equal(Buffer.from(files.get('OBSREQ.TXT')).toString(),'C2OBS2 '+'a'.repeat(32)+'\n'+' '.repeat(88));
  for(const n of ['A'.repeat(32),'../x',12])await assert.rejects(api.observerRequest(n));
  await assert.rejects(api.readObserver('/arbitrary'));files.set('OBSRESP.BIN',new Uint8Array(12));await assert.rejects(api.readObserver());
  const p=await api.observerProvenance();assert.equal(p.helper_sha256,createHash('sha256').update(new Uint8Array([6,7])).digest('hex'));
  assert.equal(calls.some(x=>x[0]==='key'),false);assert.equal(api.writeMemory,undefined);
});
test('native inventory detects same-size edits with actual digest, imports never overwrite',async()=>{
  const {api,files}=await setup();const before=await api.listSaves();assert.equal(before[0].modifiedAt,null);
  files.set('civ2/TUTORIAL.SAV',new Uint8Array([9,2,3]));assert.notEqual((await api.listSaves())[0].sha256,before[0].sha256);
  await assert.rejects(api.importSave('tutorial.sav',new Uint8Array([3])));await assert.rejects(api.importSave('../x.sav',new Uint8Array([3])));
  const r=await api.importSave('restore.sav',new Uint8Array([4,5,6]));assert.equal(r.loaded,false);assert.equal(r.verified,true);assert.equal(r.name,'RESTORE.SAV');assert.equal(files.has('civ2/RESTORE.SAV'),true);
  assert.deepEqual([...await api.readSave('restore.sav')],[4,5,6]);
  files.set('civ2/restore.sav',new Uint8Array([8]));await assert.rejects(api.listSaves(),/invalid/);
});
test('legacy selector remains default and unsupported backend cannot inject a script',async()=>{
  const loader=readFileSync(__dirname+'/runtime-loader.js','utf8');
  async function selected(search){const loaded=[];const c={URLSearchParams,Promise,location:{search},document:{createElement(){return {};},head:{appendChild(s){loaded.push(s.src);s.onload();}}}};c.window=c;vm.createContext(c);vm.runInContext(loader,c);await c.Civ2RuntimeReady;return loaded;}
  assert.deepEqual(await selected(''),['vendor/es6-promise.js','vendor/browserfs.min.js','vendor/loader.js','bridge.js','/transport.js']);
  assert.deepEqual(await selected('?backend=modern'),['vendor/modern/emulators.js','modern-bridge.js','/transport.js']);
  await assert.rejects(selected('?backend=https://elsewhere'),/Unsupported/);
});
