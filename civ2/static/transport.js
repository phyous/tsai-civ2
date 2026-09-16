/* Local-only, fixed-command transport. Model credentials never enter the page. */
(() => {
  'use strict';
  const allowed = new Set(['boot','status','pause','resume','key','chord','keyDown','keyUp','mouse','click','releaseInputs','capture','captureDashboard','listSaves','readSave','inputDiagnostics','moveRelative','importSave']);
  function encode(value) {
    if (value instanceof Uint8Array) {
      let text = '';
      for (let i = 0; i < value.length; i += 8192) text += String.fromCharCode(...value.subarray(i, i + 8192));
      return {encoding:'base64', data:btoa(text), length:value.length};
    }
    return value === undefined ? null : value;
  }
  function connect() {
    const socket = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/api/runtime`);
    socket.onmessage = async event => {
      let id;
      try {
        const request = JSON.parse(event.data); id = request.id;
        if (!Number.isInteger(id) || !allowed.has(request.command) || !Array.isArray(request.args)) throw Error('Invalid command');
        let value;
        if (request.command === 'captureDashboard') value = await parent.Civ2Dashboard.capture();
        else {
          const runtime = window.Civ2Runtime;
          if (!runtime || typeof runtime[request.command] !== 'function') throw Error('Runtime unavailable');
          if (request.command === 'importSave') {
            const [name, payload] = request.args;
            if (request.args.length !== 2 || payload?.encoding !== 'base64' || typeof payload.data !== 'string' ||
                payload.data.length > 6000000 || !Number.isInteger(payload.length) || payload.length < 1 || payload.length > 4000000)
              throw Error('Invalid original save import');
            const raw = atob(payload.data);
            if (raw.length !== payload.length) throw Error('Truncated original save');
            value = await runtime.importSave(name, Uint8Array.from(raw, character => character.charCodeAt(0)));
          } else value = await runtime[request.command](...request.args);
        }
        socket.send(JSON.stringify({id, ok:true, result:encode(value)}));
      } catch (_) {
        if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({id, ok:false, error:'Runtime command failed'}));
      }
    };
    socket.onclose = () => setTimeout(connect, 1500);
  }
  connect();
})();
