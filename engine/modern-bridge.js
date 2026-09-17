/* Optional js-dos 8.4.2 backend. Only ordinary input and bounded original-file reads. */
(function () {
  'use strict';
  const base = new URL('.', document.currentScript.src), canvas = document.querySelector('#canvas');
  const MAX_SAVE = 4 * 1024 * 1024, MAX_TOTAL_SAVES = 64 * 1024 * 1024;
  const CONFIG = '[sdl]\nautolock=false\nsensitivity=100\n[dosbox]\nmemsize=16\n[cpu]\ncore=auto\ncycles=auto\n[autoexec]\nmount c .\nc:\nwindows.bat\n';
  let ci, bootPromise, started = false, paused = false, observer = false, sequence = 0, frames = 0;
  let mouseX = 0, mouseY = 0, buttons = 0, lastMouse = null, lastHostError = null;
  let frameWidth = 640, frameHeight = 480, firstFrameReady = null;
  const heldKeys = new Set(), delay = ms => new Promise(resolve => setTimeout(resolve, ms));
  const int = (x, lo, hi) => Number.isInteger(x) && x >= lo && x <= hi;
  const receipt = (type, data) => ({sequence:++sequence,type,...data});
  function ready() { if (!started || !ci) throw Error('Runtime has not started'); }
  const named = {Enter:257,Escape:256,Tab:258,Backspace:259,Space:32,Delete:261,Insert:260,
    Home:268,End:269,PageUp:266,PageDown:267,ArrowLeft:263,ArrowRight:262,ArrowUp:265,ArrowDown:264,
    ControlLeft:341,ControlRight:345,ShiftLeft:340,ShiftRight:344,AltLeft:342,AltRight:346,
    CapsLock:280,NumLock:282,Minus:45,Equal:61,Comma:44,Period:46,Slash:47,Semicolon:59,Quote:39,
    BracketLeft:91,BracketRight:93,Backslash:92,NumpadDecimal:330,NumpadDivide:331,
    NumpadMultiply:332,NumpadSubtract:333,NumpadAdd:334,NumpadEnter:335};
  function keyCode(code) {
    if (typeof code !== 'string') throw Error('Keyboard code must be a string');
    if (/^Key[A-Z]$/.test(code)) return code.charCodeAt(3);
    if (/^Digit[0-9]$/.test(code)) return code.charCodeAt(5);
    if (/^Numpad[0-9]$/.test(code)) return 320 + Number(code[6]);
    if (/^F(?:[1-9]|1[0-2])$/.test(code)) return 289 + Number(code.slice(1));
    if (Object.hasOwn(named,code)) return named[code];
    throw Error('Unsupported physical keyboard code');
  }
  function keyEvent(code, down) {
    ready(); const value = keyCode(code), repeat = down && heldKeys.has(code);
    ci.sendKeyEvent(value,down);
    if (down) heldKeys.add(code); else heldKeys.delete(code);
    return receipt('key',{code,down,repeat});
  }
  function saveName(name) {
    if (typeof name !== 'string' || !/^[A-Za-z0-9_-]{1,32}\.sav$/i.test(name)) throw Error('Use a simple .sav filename');
    return name;
  }
  async function sha(bytes) {
    return Array.from(new Uint8Array(await window.crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');
  }
  async function directory(parts) {
    let node = await ci.fsTree();
    for (const part of parts) {
      const matches = (node.nodes || []).filter(n=>n.name.toLowerCase()===part.toLowerCase());
      if (matches.length !== 1 || !Array.isArray(matches[0].nodes)) throw Error('Original directory missing or ambiguous');
      node = matches[0];
    }
    return node;
  }
  async function entries() {
    ready();const node = await directory(['civ2']);
    const result = node.nodes.filter(n=>/\.sav$/i.test(n.name));
    if (result.length > 4096) throw Error('Too many native saves');
    const seen = new Set();let total = 0;
    for (const n of result) {
      if (n.nodes !== null || typeof n.name !== 'string' || n.name.length > 255 || /[\x00-\x1f\\/]/.test(n.name) ||
          seen.has(n.name.toLowerCase()) || !int(n.size,0,MAX_SAVE)) throw Error('Native save inventory is invalid');
      seen.add(n.name.toLowerCase());total += n.size;
    }
    if (total > MAX_TOTAL_SAVES) throw Error('Native save inventory exceeds read bound');
    return {directory:node.name,files:result};
  }
  async function readFile(path, size, maximum) {
    if (!int(size,0,maximum)) throw Error('Original file exceeds read bound');
    const value = new Uint8Array(await ci.fsReadFile(path));
    if (value.length !== size) throw Error('Original file changed while reading');
    return value;
  }
  function paint(rgb, rgba) {
    const data = rgba || rgb, channels = rgba ? 4 : 3;
    if (!data || !int(frameWidth,1,2048) || !int(frameHeight,1,2048) || data.length !== frameWidth*frameHeight*channels) return;
    if (canvas.width !== frameWidth) canvas.width = frameWidth;
    if (canvas.height !== frameHeight) canvas.height = frameHeight;
    const pixels = new Uint8ClampedArray(frameWidth*frameHeight*4);
    if (rgba) pixels.set(rgba); else for (let i=0,j=0;i<data.length;i+=3,j+=4) {
      pixels[j]=data[i];pixels[j+1]=data[i+1];pixels[j+2]=data[i+2];pixels[j+3]=255;
    }
    canvas.getContext('2d',{alpha:false}).putImageData(new ImageData(pixels,frameWidth,frameHeight),0,0);frames++;
    if (firstFrameReady) {firstFrameReady();firstFrameReady=null;}
  }
  const api = {
    async boot({profile='default',observer:useObserver=false}={}) {
      if (typeof profile !== 'string' || !/^[A-Za-z0-9_-]{1,48}$/.test(profile)) throw Error('Invalid local runtime profile');
      if (typeof useObserver !== 'boolean') throw Error('Observer mode must be boolean');
      if (bootPromise) return bootPromise;
      bootPromise = (async()=>{
        if (!window.emulators || window.emulators.version !== '8.4.2 (7fb80db8afda9ca5cde776abb7313545)') throw Error('Fetch the pinned modern runtime assets first');
        observer = useObserver;
        window.emulators.pathPrefix = new URL('vendor/modern/',base).href;
        const response = await fetch(new URL(observer?'game/civ2-win31-observer.zip':'game/civ2-win31.zip',base));
        if (!response.ok) throw Error('Original game archive unavailable');
        const bytes = new Uint8Array(await response.arrayBuffer());
        if (bytes.length < 1000000 || bytes.length > 100000000) throw Error('Original archive size invalid');
        const init = [bytes,{dosboxConf:CONFIG,jsdosConf:{version:'8.xx'}}];
        // Existing fixed files avoid js-dos' unresolved missing-file read path,
        // and DOS directory-cache misses. These are helper mailboxes, not saves.
        if (observer) init.splice(1,0,{path:'OBSREQ.TXT',contents:new Uint8Array(128).fill(32)},
          {path:'OBSRESP.BIN',contents:new Uint8Array(524288).fill(32)});
        ci = await window.emulators.dosboxWorker(init);
        const firstFrame = new Promise((resolve,reject)=>{
          const timeout=setTimeout(()=>reject(Error('Original runtime did not produce a frame')),120000);
          firstFrameReady=()=>{clearTimeout(timeout);resolve();};
        });
        ci.events().onFrameSize((w,h)=>{frameWidth=w;frameHeight=h;});
        ci.events().onFrame(paint);
        ci.events().onExit(()=>{started=false;paused=true;});
        try {await firstFrame;} catch(error) {firstFrameReady=null;await ci.exit();throw error;}
        started=true;paused=false;
        return api.status();
      })();
      return bootPromise;
    },
    status() {return {started,paused,width:canvas.width,height:canvas.height,inputSequence:sequence,
      version:'1.06 27-Mar-96',runtime:'js-dos/8.4.2/Win3.1',heldKeys:[...heldKeys],buttons,pauseBackend:'js-dos-worker',frames};},
    async pause() {ready();if (!paused) {ci.pause();await ci.fsTree();paused=true;}return api.status();},
    async resume() {ready();if (paused) {ci.resume();await ci.fsTree();paused=false;}return api.status();},
    inputDiagnostics() {ready();return {paused,lastMouse,lastHostError,sdlMouse:null,
      hostMouse:{x:mouseX,y:mouseY,buttons,source:'js-dos adapter input bookkeeping'},
      scheduler:{backend:'js-dos-worker'},startupConfig:CONFIG,frames};},
    keyDown(code) {return keyEvent(code,true);}, keyUp(code) {return keyEvent(code,false);},
    async key(code,{holdMs=60}={}) {
      keyCode(code);if (!int(holdMs,1,1000)) throw Error('Key hold must be 1..1000 milliseconds');
      const inputs=[];try {inputs.push(keyEvent(code,true));await delay(holdMs);}finally {inputs.push(keyEvent(code,false));}return inputs;
    },
    async chord(codes,{holdMs=70}={}) {
      const modifier=code=>/^(Control|Shift|Alt)(Left|Right)$/.test(code);
      if (!Array.isArray(codes) || codes.length<2 || codes.length>4 || new Set(codes).size!==codes.length ||
          !codes.slice(0,-1).every(modifier) || modifier(codes.at(-1))) throw Error('Chord requires modifiers followed by one key');
      codes.forEach(keyCode);if (!int(holdMs,1,1000)) throw Error('Key hold must be 1..1000 milliseconds');
      ready();if (codes.some(c=>heldKeys.has(c))) throw Error('Chord keys must not already be held');
      const inputs=[],pressed=[];
      try {for (const c of codes.slice(0,-1)) {pressed.push(c);inputs.push(keyEvent(c,true));}inputs.push(...await api.key(codes.at(-1),{holdMs}));}
      finally {let error;for (const c of pressed.reverse()) {try {inputs.push(keyEvent(c,false));}catch(e){error ||= e;}}if(error)throw error;}
      return inputs;
    },
    mouse({type,x,y,button=0}) {
      ready();if (!['mousemove','mousedown','mouseup'].includes(type) || !int(x,0,canvas.width-1) || !int(y,0,canvas.height-1) || !int(button,0,2)) throw Error('Invalid canvas mouse event');
      if (type==='mousemove') {ci.sendMouseMotion(x/canvas.width,y/canvas.height);mouseX=x;mouseY=y;}
      else {ci.sendMouseButton([0,2,1][button],type==='mousedown');const mask=[1,4,2][button];if(type==='mousedown')buttons|=mask;else buttons&=~mask;}
      lastMouse={type,x:mouseX,y:mouseY,button,buttons};return receipt('mouse',{event:type,x,y,button,buttons});
    },
    moveRelative(dx,dy) {
      ready();if (!int(dx,-32,32) || !int(dy,-32,32) || (dx===0&&dy===0)) throw Error('Relative mouse movement requires nonzero integer deltas within -32..32');
      ci.sendMouseRelativeMotion(dx,dy);
      return receipt('relativeMouse',{dx,dy,dispatched:true,emulate:true,via:'DOSBox Mouse_CursorMoved'});
    },
    async click(x,y,{button=0,holdMs=60}={}) {
      if (!int(holdMs,1,1000)) throw Error('Mouse hold must be 1..1000 milliseconds');
      const inputs=[api.mouse({type:'mousemove',x,y,button})];
      try {inputs.push(api.mouse({type:'mousedown',x,y,button}));await delay(holdMs);}finally {inputs.push(api.mouse({type:'mouseup',x,y,button}));}return inputs;
    },
    releaseInputs() {ready();const inputs=[];let error;
      for (const c of [...heldKeys]) {try {inputs.push(keyEvent(c,false));}catch(e){error ||= e;}}
      for (const b of [0,1,2]) if(buttons&[1,4,2][b]) {try {inputs.push(api.mouse({type:'mouseup',x:mouseX,y:mouseY,button:b}));}catch(e){error ||= e;}}
      if(error)throw error;return inputs;
    },
    capture() {ready();if(!frames)throw Error('Original frame not ready');return canvas.toDataURL('image/png');},
    async listSaves() {
      const {directory:dir,files}=await entries(),result=[];
      for (const n of files) result.push({name:n.name,size:n.size,modifiedAt:null,sha256:await sha(await readFile(dir+'/'+n.name,n.size,MAX_SAVE))});
      return result.sort((a,b)=>a.name.localeCompare(b.name));
    },
    async readSave(name) {
      saveName(name);const {directory:dir,files}=await entries(),matches=files.filter(n=>n.name.toLowerCase()===name.toLowerCase());
      if(matches.length!==1||matches[0].size===0)throw Error('Save missing or ambiguous');return readFile(dir+'/'+matches[0].name,matches[0].size,MAX_SAVE);
    },
    async observerRequest(nonce) {
      ready();if (!observer || arguments.length!==1 || typeof nonce!=='string' || !/^[a-f0-9]{32}$/.test(nonce)) throw Error('Observer requires a fixed hexadecimal nonce');
      const bytes=new Uint8Array(128).fill(32);bytes.set(new TextEncoder().encode('C2OBS2 '+nonce+'\n'));await ci.fsWriteFile('OBSREQ.TXT',new Uint8Array(bytes));
      const actual=await readFile('OBSREQ.TXT',128,128);if(actual.some((b,i)=>b!==bytes[i]))throw Error('Observer request readback differs');
      return {nonce,bytes:128,inputSequence:sequence,gameInput:false};
    },
    async readObserver() {ready();if(!observer||arguments.length)throw Error('Observer reads accept no paths or addresses');return readFile('OBSRESP.BIN',524288,524288);},
    async observerProvenance() {
      ready();if(!observer||arguments.length)throw Error('Observer provenance accepts no paths');
      async function digest(parts,name,max) {
        const dir=await directory(parts),matches=dir.nodes.filter(n=>n.name.toLowerCase()===name.toLowerCase());
        if(matches.length!==1||matches[0].nodes!==null||!int(matches[0].size,1,max))throw Error('Pinned executable missing or invalid');
        return sha(await readFile((parts.length?dir.name+'/':'')+matches[0].name,matches[0].size,max));
      }
      return {original_exe_sha256:await digest(['civ2'],'CIV2.EXE',MAX_SAVE),helper_sha256:await digest([],'CIV2OBS.EXE',524288)};
    },
    async importSave(name,bytes) {
      ready();saveName(name);if(!(bytes instanceof Uint8Array)||!int(bytes.length,1,MAX_SAVE))throw Error('Expected a bounded Uint8Array save');
      const {directory:dir,files}=await entries();if(files.some(n=>n.name.toLowerCase()===name.toLowerCase()))throw Error('Save import will not overwrite an existing file');
      const path=dir+'/'+name;
      try {await ci.fsWriteFile(path,new Uint8Array(bytes));const actual=await readFile(path,bytes.length,MAX_SAVE);
        if(actual.some((b,i)=>b!==bytes[i]))throw Error('Binary save readback mismatch');lastHostError=null;return {name,size:bytes.length,loaded:false,verified:true};
      }catch(error){lastHostError={operation:'importSave',message:String(error?.message||error).replace(/[\r\n]/g,' ').slice(0,240)};throw Error('Binary save import failed; inspect inputDiagnostics');}
    },
  };
  canvas.addEventListener('contextmenu',event=>event.preventDefault());
  window.Civ2Runtime=Object.freeze(api);
})();
