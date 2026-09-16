const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');
const source = readFileSync(__dirname + '/bridge.js', 'utf8');

async function runtime(extra = {}) {
  const events = [], calls = [], files = new Map([['TUTORIAL.SAV',new Uint8Array([1,2,3])]]);
  const canvas = {width:640,height:480,
    getContext(type,attrs) { calls.push(['context',type,attrs]); return {}; },
    addEventListener() {}, focus() {}, dispatchEvent(event) { events.push(event); },
    getBoundingClientRect() {return {left:10,top:20,width:320,height:240};},
    toDataURL() {return 'data:image/png;base64,original';}};
  function Loader(...args) {this.options=args;}
  for (const name of ['emulatorJS','locateAdditionalEmulatorJS','nativeResolution','fileSystemKey','mountZip','fetchFile','mountFile','extraArgs','startExe'])
    Loader[name] = (...args) => ({[name]:args});
  const context = {URL,Uint8Array,Date,Promise,setTimeout,clearTimeout,KeyboardEvent:class {
    constructor(type,props) {this.type=type;Object.assign(this,props);}
  },MouseEvent:class {constructor(type,props) {this.type=type;Object.assign(this,props);}},
    document:{currentScript:{src:'http://127.0.0.1:3920/engine/bridge.js'},querySelector:()=>canvas},
    Module:{pauseMainLoop(){calls.push('pause');},resumeMainLoop(){calls.push('resume');}},
    FS:{readdir(){return [...files.keys()];},stat(path){return {size:files.get(path.split('/').at(-1)).length,mtime:new Date(0)};},
      readFile(path){return files.get(path.split('/').at(-1));},
      open(path,flags){const name=path.split('/').at(-1);assert.equal(flags,'wx');assert.equal(files.has(name),false);files.set(name,new Uint8Array());return {name};},
      write(stream,bytes,offset,length,position){assert.equal(position,0);files.set(stream.name,new Uint8Array(bytes.subarray(offset,offset+length)));return length;},
      close(stream){calls.push(['close',stream.name]);},unlink(path){files.delete(path.split('/').at(-1));}},
    DosBoxLoader:Loader,
    Emulator:class {constructor(canvas,callbacks,loader){this.callbacks=callbacks;calls.push(['loader',loader]);}start(){this.callbacks.before_run();}},
    fetch:async()=>({ok:true,json:async()=>({game:{version:'1.06 27-Mar-96'}})})};
  Object.assign(context,extra);context.window=context;vm.createContext(context);vm.runInContext(source,context);
  await context.Civ2Runtime.boot();
  return {api:context.Civ2Runtime,canvas,events,calls,files,module:context.Module,fs:context.FS};
}

test('boots once, uses real main-loop functions and captures original canvas', async()=>{
  const {api,canvas,calls}=await runtime();
  await api.boot(); assert.equal(calls.filter(x=>Array.isArray(x)&&x[0]==='loader').length,1);
  const loader=calls.find(x=>Array.isArray(x)&&x[0]==='loader')[1];
  assert.equal(loader.options.find(x=>x.emulatorJS).emulatorJS[0],'http://127.0.0.1:3920/engine/vendor/dosbox-input.js');
  const config=loader.options.find(x=>x.mountFile).mountFile;
  assert.equal(config[0],'/dosbox.conf');
  assert.equal(config[1].fetchFile[1],'http://127.0.0.1:3920/engine/dosbox.conf');
  assert.equal(loader.options.some(x=>x.extraArgs),false,'mouse setting is startup config, not a late shell command');
  api.pause();api.pause();assert.equal(api.status().paused,true);api.resume();api.resume();assert.equal(api.status().paused,false);
  assert.ok(calls.includes('pause'));assert.ok(calls.includes('resume'));
  assert.equal(calls.filter(x=>x==='pause').length,1);assert.equal(calls.filter(x=>x==='resume').length,1);
  assert.equal(api.capture(),'data:image/png;base64,original');
  canvas.getContext('webgl',{alpha:false});assert.equal(calls.at(-1)[2].preserveDrawingBuffer,true);
  assert.equal(calls.at(-1)[2].alpha,false);
});
test('Emterpreter pause survives yield-resume callbacks and drains exactly once',async()=>{
  const timers=[],browser={allowAsyncCallbacks:true,queuedAsyncCallbacks:[],mainLoop:{func:null}};
  browser.pauseAsyncCallbacks=()=>{browser.allowAsyncCallbacks=false;};
  browser.resumeAsyncCallbacks=()=>{
    browser.allowAsyncCallbacks=true;const callbacks=browser.queuedAsyncCallbacks;browser.queuedAsyncCallbacks=[];
    callbacks.forEach(callback=>callback());
  };
  const {api,calls}=await runtime({Browser:browser,EmterpreterAsync:{state:1}});
  let ticks=0;
  const tick=()=>{if(browser.allowAsyncCallbacks)ticks++;else browser.queuedAsyncCallbacks.push(()=>ticks++);};
  api.pause();browser.resumeAsyncCallbacks();tick();
  assert.equal(browser.allowAsyncCallbacks,false);assert.equal(ticks,0);
  assert.equal(api.inputDiagnostics().scheduler.queuedCallbacks,1);
  api.resume();api.resume();assert.equal(ticks,1);assert.equal(browser.queuedAsyncCallbacks.length,0);
  assert.equal(calls.includes('resume'),false,'does not call empty Browser.mainLoop.resume');
  assert.equal(api.status().pauseBackend,'emterpreter_async_callbacks');
});
test('relative mouse exposes only bounded deltas through the original SDL API',async()=>{
  const {api,module}=await runtime();const calls=[];
  module.HEAPU8=new Uint8Array(30064344);module.HEAP32=new Int32Array(module.HEAPU8.buffer);
  module.HEAP32[7175725]=64;
  module.asm={_tsai_sdl_send_mouse_motion(...args){calls.push(args);return 1;}};
  const result=api.moveRelative(12,-8);
  assert.deepEqual(calls,[[64,0,1,12,-8]]);assert.equal(result.queued,true);
  assert.equal(module.HEAP32[7175725],64);
  for(const delta of [[0,0],[33,0],[0,-33],[1.5,0],['1',0],[true,0]])assert.throws(()=>api.moveRelative(...delta),/integer/);
  assert.equal(calls.length,1);
  module.HEAP32[7175725]=-1;assert.throws(()=>api.moveRelative(1,0),/focus/);
  module.HEAP32[7175725]=64;module.asm._tsai_sdl_send_mouse_motion=()=>0;
  assert.throws(()=>api.moveRelative(1,0),/queue/);
});
test('input diagnostics expose bounded host symbols without a memory-write path',async()=>{
  const {api,module,files}=await runtime();
  const diagnostic=api.inputDiagnostics();
  assert.equal(diagnostic.dosboxMouse,null);assert.equal(diagnostic.sdlMouse,null);
  assert.equal(diagnostic.startupConfig,null);assert.equal(diagnostic.mouseHandlers.length,0);
  assert.equal(api.writeMemory,undefined);
  module.HEAPU8=new Uint8Array(30064344);module.HEAP32=new Int32Array(module.HEAPU8.buffer);
  module.HEAPU8[406184]=1;module.HEAPU8[406185]=0;module.HEAPU8[406186]=0;module.HEAPU8[406187]=0;
  module.HEAPU8[30064341]=1;module.HEAP32[7175726]=403;module.HEAP32[7175727]=337;
  files.set('dosbox.conf',new Uint8Array(Buffer.from('[sdl]\nautolock=false\n')));
  const observed=api.inputDiagnostics();
  assert.equal(observed.dosboxMouse.autoenable,0);assert.equal(observed.dosboxMouse.locked,0);
  assert.equal(observed.sdlMouse.x,403);assert.equal(observed.sdlMouse.y,337);
  assert.equal(observed.startupConfig,'[sdl]\nautolock=false\n');
  assert.equal(module.HEAPU8[406184],1);assert.equal(module.HEAPU8[406185],0);
  assert.equal(module.HEAP32[7175726],403,'diagnostic leaves sampled memory unchanged');
});
test('physical keys preserve Ctrl and release inputs without stuck modifiers',async()=>{
  const {api,events}=await runtime();
  api.keyDown('ControlLeft');await api.key('KeyS',{holdMs:1});api.releaseInputs();
  assert.deepEqual(events.map(e=>[e.type,e.code,e.ctrlKey]),[
    ['keydown','ControlLeft',true],['keydown','KeyS',true],['keyup','KeyS',true],['keyup','ControlLeft',false]]);
  assert.equal(events[1].keyCode,83);assert.equal(api.status().heldKeys.length,0);
  assert.throws(()=>api.keyDown('arbitrary'),/Unsupported/);
  await assert.rejects(api.key('KeyS',{holdMs:1001}),/hold/);
});
test('mouse converts canvas pixels and preserves buttons and modifier receipts',async()=>{
  const {api,events}=await runtime();
  api.keyDown('ShiftLeft');const receipts=await api.click(100,200,{button:2,holdMs:1});
  assert.equal(receipts.length,3);assert.equal(events[2].clientX,60);assert.equal(events[2].clientY,120);
  assert.equal(events[2].buttons,2);assert.equal(events[2].shiftKey,true);
  assert.equal(events.at(-1).buttons,0);assert.equal(api.status().buttons,0);
  assert.throws(()=>api.mouse({type:'mousedown',x:640,y:0}),/Invalid/);
  assert.throws(()=>api.mouse({type:'mousedown',x:0.5,y:0}),/Invalid/);
});
test('native save reads are bounded and traversal or overwrites are refused',async()=>{
  const {api,files}=await runtime();
  assert.equal(api.listSaves()[0].name,'TUTORIAL.SAV');
  assert.deepEqual([...api.readSave('tutorial.sav')],[1,2,3]);
  assert.throws(()=>api.readSave('../civ2/TUTORIAL.SAV'),/filename/);
  assert.throws(()=>api.importSave('TUTORIAL.SAV',new Uint8Array([1])),/overwrite/);
  assert.throws(()=>api.importSave('NEW.SAV',new Uint8Array(4*1024*1024+1)),/bounded/);
  const imported=api.importSave('NEW.SAV',new Uint8Array([0,4,128,255]));
  assert.equal(imported.verified,true);assert.equal(imported.loaded,false);
  assert.deepEqual([...api.readSave('new.sav')],[0,4,128,255]);
  files.set('HUGE.SAV',new Uint8Array(4*1024*1024+1));assert.throws(()=>api.readSave('HUGE.SAV'),/bounds/);
  files.set('tutorial.sav',new Uint8Array([9]));assert.throws(()=>api.readSave('tutorial.sav'),/ambiguous/);
});
test('failed save imports close streams, remove only their new file and report bounded diagnostics',async()=>{
  for(const failure of ['throw','short','corrupt']) {
    const {api,fs,files,calls}=await runtime();
    const write=fs.write;
    fs.write=(stream,bytes,offset,length,position)=>{
      if(failure==='throw')throw new Error('test write failure\n'+'x'.repeat(400));
      const result=write(stream,bytes,offset,length,position);
      if(failure==='corrupt')files.get(stream.name)[0]^=1;
      return failure==='short' ? result-1 : result;
    };
    assert.throws(()=>api.importSave('RESTORE.SAV',new Uint8Array([0,128,255])),/Binary save import failed/);
    assert.equal(calls.filter(x=>Array.isArray(x)&&x[0]==='close').length,1);
    assert.equal(files.has('RESTORE.SAV'),false);
    assert.deepEqual([...files.get('TUTORIAL.SAV')],[1,2,3]);
    const error=api.inputDiagnostics().lastHostError;
    assert.equal(error.operation,'importSave');assert.ok(error.message.length<=240);assert.ok(!error.message.includes('\n'));
    fs.write=write;
    assert.equal(api.importSave('RESTORE.SAV',new Uint8Array([1,2])).verified,true);
    assert.equal(api.inputDiagnostics().lastHostError,null);
  }
});
test('atomic chord validates all codes before input and releases modifiers in reverse order',async()=>{
  const {api,events}=await runtime();
  const receipts=await api.chord(['ControlLeft','ShiftLeft','KeyS'],{holdMs:1});
  assert.deepEqual(events.map(e=>[e.type,e.code]),[
    ['keydown','ControlLeft'],['keydown','ShiftLeft'],['keydown','KeyS'],
    ['keyup','KeyS'],['keyup','ShiftLeft'],['keyup','ControlLeft']]);
  assert.equal(events[2].key,'S');assert.equal(events[2].ctrlKey,true);assert.equal(events[2].shiftKey,true);
  assert.equal(receipts.length,6);assert.equal(api.status().heldKeys.length,0);
  for (const codes of [['KeyS'],['KeyA','KeyS'],['ControlLeft','ShiftLeft'],
    ['ControlLeft','ControlLeft','KeyS'],['ControlLeft','Unsupported'],
    ['ControlLeft','ShiftLeft','AltLeft','ControlRight','KeyS']]) {
    await assert.rejects(api.chord(codes,{holdMs:1}));
  }
  await assert.rejects(api.chord(['ControlLeft','KeyS'],{holdMs:1001}));
  assert.equal(events.length,6,'invalid chord emits no partial modifier input');
  api.keyDown('ControlLeft');await assert.rejects(api.chord(['ControlLeft','KeyS'],{holdMs:1}),/already/);
  api.releaseInputs();
});
test('atomic chord clears attempted keys after a dispatch failure',async()=>{
  const {api,canvas,events}=await runtime();
  const dispatch=canvas.dispatchEvent;
  canvas.dispatchEvent=event=>{
    dispatch(event);
    if(event.code==='KeyS'&&event.type==='keydown')throw new Error('Test dispatch failure');
  };
  await assert.rejects(api.chord(['ControlLeft','ShiftLeft','KeyS'],{holdMs:1}),/dispatch failure/);
  assert.deepEqual(events.slice(-3).map(e=>[e.type,e.code]),[
    ['keyup','KeyS'],['keyup','ShiftLeft'],['keyup','ControlLeft']]);
  assert.equal(api.status().heldKeys.length,0);
});
