/* Game-only interface over the original emulator's DOM inputs and save filesystem. */
(function () {
  'use strict';
  const base = new URL('.', document.currentScript.src);
  const canvas = document.querySelector('#canvas');
  const SAVE_DIR = '/emulator/c/civ2';
  const MAX_SAVE = 4 * 1024 * 1024;
  let bootPromise = null, started = false, paused = false, manifest = null, sequence = 0;
  let mouseX = 0, mouseY = 0, buttons = 0;
  let lastMouse = null;
  let pauseBackend = 'main_loop', pauseGateInstalled = false, lastControlError = null, lastHostError = null;
  const heldKeys = new Set();
  const delay = (ms) => new Promise(resolve => setTimeout(resolve, ms));
  const isInt = (n, min, max) => Number.isInteger(n) && n >= min && n <= max;
  function requireStarted() { if (!started || !window.Module || !window.FS) throw new Error('Runtime has not started'); }
  function receipt(type, data) { return {sequence: ++sequence, type, ...data}; }
  function installPauseGate() {
    if (pauseGateInstalled) return;
    const browser = window.Browser;
    if (!window.EmterpreterAsync || typeof browser?.pauseAsyncCallbacks !== 'function' ||
        typeof browser?.resumeAsyncCallbacks !== 'function') return;
    // dosbox-sync yields its interpreter through Browser.safeSetTimeout.
    // Its own zero-delay resumeCallbacksForYield must not override a user pause.
    const resumeCallbacks = browser.resumeAsyncCallbacks;
    browser.resumeAsyncCallbacks = function(...args) {
      if (paused) return;
      return resumeCallbacks.apply(this,args);
    };
    pauseBackend = 'emterpreter_async_callbacks';
    pauseGateInstalled = true;
  }
  function setPaused(value) {
    requireStarted();
    if (paused === value) return api.status();
    installPauseGate();
    try {
      if (pauseBackend === 'emterpreter_async_callbacks') {
        paused = value;
        if (value) window.Browser.pauseAsyncCallbacks();
        else window.Browser.resumeAsyncCallbacks();
      } else {
        if (value) window.Module.pauseMainLoop();
        else window.Module.resumeMainLoop();
        paused = value;
      }
      lastControlError = null;
    } catch (error) {
      lastControlError = {operation:value ? 'pause' : 'resume',name:String(error?.name || 'Error').slice(0,80),
        message:String(error?.message || error).replace(/[\r\n]/g,' ').slice(0,240)};
      if (pauseBackend === 'emterpreter_async_callbacks') { paused = true; window.Browser.pauseAsyncCallbacks(); }
      throw new Error('Original runtime control failed; inspect inputDiagnostics');
    }
    return api.status();
  }
  function modifiers() {
    return {ctrlKey: heldKeys.has('ControlLeft') || heldKeys.has('ControlRight'),
      shiftKey: heldKeys.has('ShiftLeft') || heldKeys.has('ShiftRight'),
      altKey: heldKeys.has('AltLeft') || heldKeys.has('AltRight'), metaKey: false};
  }
  const namedKeys = {
    Enter:['Enter',13], Escape:['Escape',27], Space:[' ',32], Tab:['Tab',9], Backspace:['Backspace',8],
    Delete:['Delete',46], Insert:['Insert',45], Home:['Home',36], End:['End',35], PageUp:['PageUp',33], PageDown:['PageDown',34],
    ArrowLeft:['ArrowLeft',37], ArrowUp:['ArrowUp',38], ArrowRight:['ArrowRight',39], ArrowDown:['ArrowDown',40],
    ShiftLeft:['Shift',16,1], ShiftRight:['Shift',16,2], ControlLeft:['Control',17,1], ControlRight:['Control',17,2],
    AltLeft:['Alt',18,1], AltRight:['Alt',18,2], CapsLock:['CapsLock',20], NumLock:['NumLock',144],
    Minus:['-',189], Equal:['=',187], Comma:[',',188], Period:['.',190], Slash:['/',191],
    Semicolon:[';',186], Quote:["'",222], BracketLeft:['[',219], BracketRight:[']',221], Backslash:['\\',220],
    NumpadAdd:['+',107,3], NumpadSubtract:['-',109,3], NumpadMultiply:['*',106,3], NumpadDivide:['/',111,3], NumpadDecimal:['.',110,3], NumpadEnter:['Enter',13,3],
  };
  function keyInfo(code) {
    if (typeof code !== 'string') throw new Error('Keyboard code must be a string');
    if (/^Key[A-Z]$/.test(code)) return [modifiers().shiftKey ? code[3] : code[3].toLowerCase(), code.charCodeAt(3), 0];
    if (/^Digit[0-9]$/.test(code)) return [code[5], code.charCodeAt(5), 0];
    if (/^Numpad[0-9]$/.test(code)) return [code[6], 96 + Number(code[6]), 3];
    if (/^F(?:[1-9]|1[0-2])$/.test(code)) return [code, 111 + Number(code.slice(1)), 0];
    if (namedKeys[code]) return namedKeys[code];
    throw new Error('Unsupported physical keyboard code');
  }
  function keyEvent(code, down) {
    requireStarted();
    const [key, keyCode, location = 0] = keyInfo(code);
    const repeat = down && heldKeys.has(code);
    if (down) heldKeys.add(code); else heldKeys.delete(code);
    canvas.focus({preventScroll:true});
    const event = new KeyboardEvent(down ? 'keydown' : 'keyup', {key, code, location,
      keyCode, which:keyCode, charCode:0, repeat, ...modifiers(), bubbles:true, cancelable:true});
    canvas.dispatchEvent(event);
    return receipt('key', {code, down, repeat});
  }
  function saveName(name) {
    if (typeof name !== 'string' || !/^[A-Za-z0-9_-]{1,32}\.sav$/i.test(name)) throw new Error('Use a simple .sav filename');
    return name;
  }
  function resolveSave(name) {
    saveName(name);
    const matches = window.FS.readdir(SAVE_DIR).filter(entry => entry.toLowerCase() === name.toLowerCase());
    if (matches.length !== 1) throw new Error('Save file not found or ambiguous');
    return SAVE_DIR + '/' + matches[0];
  }
  // Preserve only this emulator canvas's WebGL back buffer for exact post-frame PNGs.
  // This changes presentation storage, not guest memory or game rules.
  const originalGetContext = canvas.getContext.bind(canvas);
  canvas.getContext = function(type, attributes) {
    return originalGetContext(type, /^(?:experimental-)?webgl2?$/.test(type)
      ? {...attributes, preserveDrawingBuffer:true} : attributes);
  };
  canvas.addEventListener('contextmenu', event => event.preventDefault());
  const api = {
    async boot({profile = 'default', observer = false} = {}) {
      if (!/^[A-Za-z0-9_-]{1,48}$/.test(profile)) throw new Error('Invalid local runtime profile');
      if (typeof observer !== 'boolean') throw new Error('Observer mode must be boolean');
      if (bootPromise) return bootPromise;
      bootPromise = (async () => {
        if (!window.Emulator || !window.DosBoxLoader) throw new Error('Fetch the runtime assets before booting');
        const response = await fetch(new URL('runtime-manifest.json', base));
        if (!response.ok) throw new Error('Runtime manifest unavailable');
        manifest = await response.json();
        return await new Promise((resolve, reject) => {
          const timeout = setTimeout(() => reject(new Error('Runtime startup timed out')), 120000);
          const loader = new DosBoxLoader(
            DosBoxLoader.emulatorJS(new URL('vendor/dosbox-input.js', base).href),
            DosBoxLoader.locateAdditionalEmulatorJS(filename => new URL('vendor/' +
              (filename === 'dosbox.html.mem' ? 'dosbox-sync.mem' : filename), base).href),
            DosBoxLoader.nativeResolution(640,480),
            DosBoxLoader.fileSystemKey('tsai-civ2-v1-' + profile),
            DosBoxLoader.mountZip('c', DosBoxLoader.fetchFile('Civilization II and Windows 3.1',
              new URL(observer ? 'game/civ2-win31-observer.zip' : 'game/civ2-win31.zip', base).href)),
            // DOSBox otherwise gates mouse motion behind browser pointer lock,
            // which synthetic DOM inputs cannot acquire through user activation.
            // This ordinary host setting enables its existing absolute-input path.
            // The loader already passes -conf /emulator/dosbox.conf. Mount it
            // before startup so GFX initialization reads this setting itself.
            DosBoxLoader.mountFile('/dosbox.conf', DosBoxLoader.fetchFile('Host mouse configuration', new URL('dosbox.conf', base).href)),
            DosBoxLoader.startExe('windows.bat')
          );
          const emulator = new Emulator(canvas, {before_run() {
            started = true; paused = false; installPauseGate(); clearTimeout(timeout); resolve(api.status());
          }}, loader);
          emulator.start({waitAfterDownloading:false});
        });
      })();
      return bootPromise;
    },
    status() {
      return {started, paused, width:canvas.width, height:canvas.height, inputSequence:sequence,
        version:manifest?.game?.version || '1.06 27-Mar-96', runtime:'em-dosbox/Win3.1',
        heldKeys:[...heldKeys], buttons, pauseBackend};
    },
    pause() { return setPaused(true); },
    resume() { return setPaused(false); },
    inputDiagnostics() {
      requireStarted();
      const module = window.Module, heap = module.HEAPU8, ints = module.HEAP32;
      const rect = canvas.getBoundingClientRect();
      const ready = heap instanceof Uint8Array && heap.length > 30064341 && ints;
      let startupConfig = null;
      try {
        const content = window.FS.readFile('/emulator/dosbox.conf');
        if (content.length <= 1024) startupConfig = Array.from(content,byte=>String.fromCharCode(byte)).join('');
      } catch (_) { /* Diagnostic must report missing config without throwing. */ }
      const targetName = target => target === canvas ? 'canvas' : target === document ? 'document' : target === window ? 'window' : 'other';
      return {paused, canvasIsRuntimeCanvas:module.canvas === canvas,
        scheduler:{backend:pauseBackend,mainLoopFunctionPresent:Boolean(window.Browser?.mainLoop?.func),
          asyncState:window.EmterpreterAsync?.state ?? null,
          callbacksAllowed:window.Browser?.allowAsyncCallbacks ?? null,
          queuedCallbacks:window.Browser?.queuedAsyncCallbacks?.length ?? null,lastControlError},
        canvasRect:{left:rect.left,top:rect.top,width:rect.width,height:rect.height},
        pointerLocked:document.pointerLockElement === canvas,
        lastMouse, startupConfig, lastHostError,
        mouseHandlers:(window.JSEvents?.eventHandlers || []).filter(handler =>
          ['mousemove','mousedown','mouseup'].includes(handler.eventTypeString)).slice(0,12).map(handler =>
          ({type:handler.eventTypeString,target:targetName(handler.target),callback:handler.callbackfunc})),
        // Fixed read-only host-runtime symbols recovered from the pinned asm.js:
        // its SDL_MOUSEMOTION case gates on mouse.locked || !mouse.autoenable.
        // No Civ II address or caller-provided memory range is read here.
        dosboxMouse:ready ? {autolock:heap[406184],autoenable:heap[406185],requestlock:heap[406186],
          locked:heap[406187],browserCaptureMode:heap[30064341]} : null,
        sdlMouse:ready ? {x:ints[7175726],y:ints[7175727],buttons:ints[7175732],relativeMode:ints[7175733]} : null};
    },
    keyDown(code) { return keyEvent(code, true); },
    keyUp(code) { return keyEvent(code, false); },
    async key(code, {holdMs = 60} = {}) {
      keyInfo(code);
      if (!isInt(holdMs,1,1000)) throw new Error('Key hold must be 1..1000 milliseconds');
      const inputs = [];
      try { inputs.push(keyEvent(code,true)); await delay(holdMs); }
      finally { inputs.push(keyEvent(code,false)); }
      return inputs;
    },
    async chord(codes, {holdMs = 70} = {}) {
      const modifier = code => /^(Control|Shift|Alt)(Left|Right)$/.test(code);
      if (!Array.isArray(codes) || codes.length < 2 || codes.length > 4 ||
          new Set(codes).size !== codes.length || !codes.slice(0,-1).every(modifier) || modifier(codes.at(-1)))
        throw new Error('Chord requires 1..3 distinct modifiers followed by one physical key');
      codes.forEach(keyInfo);
      if (!isInt(holdMs,1,1000)) throw new Error('Key hold must be 1..1000 milliseconds');
      requireStarted();
      if (codes.some(code => heldKeys.has(code))) throw new Error('Chord keys must not already be held');
      const inputs = [], pressed = [];
      try {
        for (const code of codes.slice(0,-1)) { pressed.push(code); inputs.push(keyEvent(code,true)); }
        inputs.push(...await api.key(codes.at(-1),{holdMs}));
      } finally {
        let cleanupError;
        for (const code of pressed.reverse()) {
          try { inputs.push(keyEvent(code,false)); } catch (error) { cleanupError ||= error; }
        }
        if (cleanupError) throw cleanupError;
      }
      return inputs;
    },
    mouse({type, x, y, button = 0}) {
      requireStarted();
      if (!['mousemove','mousedown','mouseup'].includes(type) || !isInt(x,0,canvas.width-1) || !isInt(y,0,canvas.height-1) || !isInt(button,0,2))
        throw new Error('Invalid canvas mouse event');
      const mask = [1,4,2][button];
      if (type === 'mousedown') buttons |= mask;
      if (type === 'mouseup') buttons &= ~mask;
      const rect = canvas.getBoundingClientRect();
      const clientX = rect.left + x * rect.width / canvas.width;
      const clientY = rect.top + y * rect.height / canvas.height;
      lastMouse = {type,x,y,clientX,clientY,button,buttons};
      canvas.focus({preventScroll:true});
      canvas.dispatchEvent(new MouseEvent(type, {bubbles:true,cancelable:true,
        clientX,clientY,screenX:clientX,screenY:clientY,button,buttons,
        movementX:(x-mouseX)*rect.width/canvas.width,movementY:(y-mouseY)*rect.height/canvas.height,...modifiers()}));
      mouseX=x; mouseY=y;
      return receipt('mouse',{event:type,x,y,button,buttons});
    },
    moveRelative(dx, dy) {
      requireStarted();
      if (!isInt(dx,-32,32) || !isInt(dy,-32,32) || (dx === 0 && dy === 0))
        throw new Error('Relative mouse movement requires nonzero integer deltas within -32..32');
      const moveCursor = window.Module.asm?._tsai_dosbox_mouse_motion;
      if (typeof moveCursor !== 'function')
        throw new Error('The verified DOSBox relative-input runtime is unavailable');
      // Original Mouse_CursorMoved(xrel,yrel,x,y,emulate). DOSBox's unlocked
      // SDL handler forces emulate=false even for SDL relative events, causing
      // host-edge saturation. Use the existing relative host-input mode here;
      // original scaling, PS/2 callback, event queue and IRQ handling remain.
      moveCursor(+dx,+dy,0.0,0.0,1);
      return receipt('relativeMouse',{dx,dy,dispatched:true,emulate:true,via:'DOSBox Mouse_CursorMoved'});
    },
    async click(x,y,{button = 0,holdMs = 60} = {}) {
      if (!isInt(holdMs,1,1000)) throw new Error('Mouse hold must be 1..1000 milliseconds');
      const inputs = [api.mouse({type:'mousemove',x,y,button}),api.mouse({type:'mousedown',x,y,button})];
      try { await delay(holdMs); } finally { inputs.push(api.mouse({type:'mouseup',x,y,button})); }
      return inputs;
    },
    releaseInputs() {
      requireStarted();
      const inputs = [...heldKeys].map(code => keyEvent(code,false));
      for (const button of [0,1,2]) if (buttons & [1,4,2][button]) inputs.push(api.mouse({type:'mouseup',x:mouseX,y:mouseY,button}));
      return inputs;
    },
    capture() { requireStarted(); return canvas.toDataURL('image/png'); },
    listSaves() {
      requireStarted();
      return window.FS.readdir(SAVE_DIR).filter(name => /\.sav$/i.test(name)).map(name => {
        if (typeof name !== 'string' || name.length > 255 || /[\x00-\x1f\\/]/.test(name))
          throw new Error('Save inventory filename is invalid');
        const stat = window.FS.stat(SAVE_DIR + '/' + name);
        if (!Number.isSafeInteger(stat.size) || stat.size < 0) throw new Error('Save inventory size is invalid');
        return {name,size:stat.size,modifiedAt:stat.mtime instanceof Date ? stat.mtime.toISOString() : null};
      }).sort((a,b) => a.name.localeCompare(b.name));
    },
    readSave(name) {
      requireStarted();
      const path = resolveSave(name), stat = window.FS.stat(path);
      if (!isInt(stat.size,1,MAX_SAVE)) throw new Error('Save size outside supported bounds');
      return new Uint8Array(window.FS.readFile(path));
    },
    // Fixed observer mailbox only. Callers cannot select a guest path, address,
    // memory range, or game command. The Win16 helper reads original state.
    observerRequest(nonce) {
      requireStarted();
      if (arguments.length !== 1 || typeof nonce !== 'string' || !/^[a-f0-9]{32}$/.test(nonce))
        throw new Error('Observer requires a fixed hexadecimal nonce');
      const bytes = new Uint8Array(128).fill(32);
      Array.from('C2OBS2 ' + nonce + '\n', ch => ch.charCodeAt(0)).forEach((byte, i) => { bytes[i] = byte; });
      const fs = window.FS, path = '/emulator/c/OBSREQ.TXT';
      const stream = fs.open(path, 'w');
      try {
        if (fs.write(stream, bytes, 0, bytes.length, 0) !== bytes.length)
          throw new Error('Incomplete observer request');
      } finally { fs.close(stream); }
      const actual = fs.readFile(path, {encoding:'binary'});
      if (actual.length !== bytes.length || actual.some((byte, i) => byte !== bytes[i]))
        throw new Error('Observer request readback differs');
      return {nonce, bytes:bytes.length, inputSequence:sequence, gameInput:false};
    },
    readObserver() {
      requireStarted();
      if (arguments.length) throw new Error('Observer reads accept no paths or addresses');
      const fs = window.FS, path = '/emulator/c/OBSRESP.BIN';
      if (fs.stat(path).size !== 524288) throw new Error('Observer envelope has an invalid size');
      const bytes = new Uint8Array(fs.readFile(path, {encoding:'binary'}));
      if (bytes.length !== 524288) throw new Error('Observer envelope is incomplete');
      return bytes;
    },
    async observerProvenance() {
      requireStarted();
      if (arguments.length) throw new Error('Observer provenance accepts no paths');
      const fs = window.FS;
      async function digest(directory, name, maximum) {
        const matches = fs.readdir(directory).filter(entry => entry.toLowerCase() === name.toLowerCase());
        if (matches.length !== 1) throw new Error('Pinned observer executable is missing or ambiguous');
        const path = directory + '/' + matches[0];
        if (!isInt(fs.stat(path).size, 1, maximum)) throw new Error('Observer executable size is invalid');
        const bytes = new Uint8Array(fs.readFile(path, {encoding:'binary'}));
        if (!isInt(bytes.length, 1, maximum)) throw new Error('Observer executable read is invalid');
        const hash = new Uint8Array(await window.crypto.subtle.digest('SHA-256', bytes));
        return Array.from(hash, byte => byte.toString(16).padStart(2, '0')).join('');
      }
      return {
        original_exe_sha256:await digest('/emulator/c/civ2', 'CIV2.EXE', 4 * 1024 * 1024),
        helper_sha256:await digest('/emulator/c', 'CIV2OBS.EXE', 512 * 1024),
      };
    },
    // Explicit setup/recovery only. This imports a whole normal save file; it never
    // changes a running game. The game must load it through its ordinary Load menu.
    importSave(name, bytes) {
      requireStarted(); saveName(name);
      if (!(bytes instanceof Uint8Array) || !isInt(bytes.length,1,MAX_SAVE)) throw new Error('Expected a bounded Uint8Array save');
      let existing = window.FS.readdir(SAVE_DIR).find(entry => entry.toLowerCase() === name.toLowerCase());
      if (existing) throw new Error('Save import will not overwrite an existing file');
      const fs = window.FS, path = SAVE_DIR + '/' + name;
      let created = false;
      try {
        // This pinned FS.writeFile defaults to UTF-8 even for a Uint8Array.
        // Use its binary stream API and close on every path; wx cannot truncate.
        const stream = fs.open(path,'wx');
        created = true;
        try {
          if (fs.write(stream,bytes,0,bytes.length,0) !== bytes.length)
            throw new Error('Incomplete binary save write');
        } finally { fs.close(stream); }
        const saved = fs.readFile(path,{encoding:'binary'});
        if (saved.length !== bytes.length || saved.some((byte,index) => byte !== bytes[index]))
          throw new Error('Binary save readback mismatch');
        lastHostError = null;
        return {name,size:bytes.length,loaded:false,verified:true};
      } catch (error) {
        // Only this call's newly created file may be removed.
        if (created) { try { fs.unlink(path); } catch (_) { /* Report original failure. */ } }
        lastHostError = {operation:'importSave',name:String(error?.name || 'Error').slice(0,80),
          message:String(error?.message || error).replace(/[\r\n]/g,' ').slice(0,240)};
        throw new Error('Binary save import failed; inspect inputDiagnostics');
      }
    },
  };
  window.Civ2Runtime = Object.freeze(api);
})();
