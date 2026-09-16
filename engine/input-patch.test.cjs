const assert = require('node:assert/strict');
const {readFileSync,existsSync} = require('node:fs');
const {createHash} = require('node:crypto');
const test = require('node:test');
const vm = require('node:vm');
const metadata=JSON.parse(readFileSync(__dirname+'/input-patch.json','utf8'));
const present=existsSync(__dirname+'/'+metadata.original)&&existsSync(__dirname+'/'+metadata.derived);
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');

test('derived runtime has only hash-bound host input exports and instantiates them',{skip:!present},()=>{
  const original=readFileSync(__dirname+'/'+metadata.original);
  const derived=readFileSync(__dirname+'/'+metadata.derived);
  assert.equal(sha(original),metadata.original_sha256);assert.equal(sha(derived),metadata.derived_sha256);
  assert.equal(derived.length,metadata.derived_bytes);
  assert.equal(derived.toString(),original.toString().replace(metadata.replace_once,metadata.with));
  const source=derived.toString();
  const start=source.indexOf('var asm=(')+'var asm=('.length;
  const end=source.indexOf('// EMSCRIPTEN_END_ASM');
  const expression=source.slice(start,end).trim().replace(/\)$/,'');
  const realm=vm.createContext({});
  const factory=vm.runInContext('('+expression+')',realm);
  const env={};
  for(const match of expression.matchAll(/env\.([A-Za-z_$][\w$]*)/g))env[match[1]]=()=>0;
  for(const match of expression.matchAll(/env\.([A-Za-z_$][\w$]*)\|0/g))env[match[1]]=0;
  env.STACKTOP=1048576;env.STACK_MAX=2097152;
  const api=factory(vm.runInContext('globalThis',realm),env,vm.runInContext('new ArrayBuffer(128*1024*1024)',realm));
  assert.equal(typeof api._main,'function');
  assert.equal(typeof api._tsai_sdl_send_mouse_motion,'function');
  assert.equal(typeof api._tsai_dosbox_mouse_motion,'function');
});

test('SDL queue alone preserves deltas at host edges, before DOSBox consumes them',{skip:!present},()=>{
  const source=readFileSync(__dirname+'/'+metadata.original,'utf8');
  const functions=['lqa','lt'].map(name=>{
    const start=source.indexOf('function '+name+'(');
    return source.slice(start,source.indexOf('function ',start+1));
  }).join('');
  const buffer=new ArrayBuffer(32*1024*1024),a=new Int8Array(buffer),c=new Int32Array(buffer),events=[];
  c[7175725]=64;c[(64+4)>>2]=1;c[7175730]=639;c[7175731]=479;c[7175726]=639;c[7175727]=479;
  const context={a,c,l:1048576,
    Iaa(window,x,y){c[x>>2]=640;c[y>>2]=480;},TZ(){return 1;},
    iba(p){events.push({type:c[p>>2],x:c[(p+20)>>2],y:c[(p+24)>>2],dx:c[(p+28)>>2],dy:c[(p+32)>>2]});return 1;},
    YG(){throw Error('Absolute focus update is not needed for relative movement');}};
  vm.createContext(context);vm.runInContext(functions,context);
  for(let i=0;i<5;i++)assert.equal(context.lqa(64,0,1,12,8),1);
  assert.equal(c[7175726],639);assert.equal(c[7175727],479);
  assert.equal(events.length,5);assert(events.every(e=>e.type===1024&&e.x===639&&e.y===479&&e.dx===12&&e.dy===8));
});

test('exact compiled SDL-to-DOSBox path saturates unlocked, but original relative handler keeps moving',{skip:!present},()=>{
  const source=readFileSync(__dirname+'/'+metadata.original,'utf8');
  const functions=['lqa','lt','pl','Et'].map(name=>{
    const start=source.indexOf('function '+name+'(');
    assert(start>=0);return source.slice(start,source.indexOf('function ',start+1));
  }).join('');
  const buffer=new ArrayBuffer(32*1024*1024),a=new Int8Array(buffer),b=new Int16Array(buffer),
    c=new Int32Array(buffer),g=new Float32Array(buffer),events=[],dispatches=[],irq=[];
  c[7175725]=64;c[(64+4)>>2]=1;
  c[7175730]=639;c[7175731]=479;c[7175726]=639;c[7175727]=479;
  c[101536]=640;c[101537]=480;c[101547]=100; // Original output clip and sensitivity.
  a[406187]=0;a[406185]=0; // Normal autolock=false startup: unlocked, input enabled.
  a[30095370]=1; // Windows PS/2 callback: original handler doubles Y mickeys.
  b[14346839]=639;b[14346841]=479;
  for(const offset of [7173514,7173515,7173516,7173517,7173520,7173521])g[offset]=1;
  g[7173423]=400;g[7173424]=300;
  const context={a,b,c,g,l:1048576,H:Math.abs,G_:()=>0,
    Iaa(window,x,y){c[x>>2]=640;c[y>>2]=480;},TZ:()=>1,
    iba(p){events.push(new Uint8Array(buffer.slice(p,p+56)));return 1;},
    ofa(p){if(!events.length)return 0;a.set(events.shift(),p);return 1;},
    YG(){throw Error('Unexpected absolute SDL focus operation');},
    UP(...args){irq.push(args);},wS(){},_p(){},
  };
  vm.createContext(context);vm.runInContext(functions,context);
  const moveCursor=context.Et;
  context.Et=(...args)=>{dispatches.push(args);moveCursor(...args);};
  const positions=[];
  for(let i=0;i<3;i++) {
    context.lqa(64,0,1,12,8);context.pl();
    positions.push([g[7173423],g[7173424]]);
  }
  assert.deepEqual(dispatches,[[12,8,1,1,false],[12,8,1,1,false],[12,8,1,1,false]],
    'DOSBox selects emulate=0 from its unlocked state, regardless of SDL relative injection');
  assert.deepEqual(positions,[[639,479],[639,479],[639,479]]);
  assert.equal(g[7173421],36);assert.equal(g[7173422],48,'mickey counters alone do not prove cursor movement');
  g[7173423]=400;g[7173424]=300;
  const relative=[];
  for(let i=0;i<3;i++) {
    moveCursor(12,8,0,0,1);
    relative.push([g[7173423],g[7173424]]);
  }
  assert.deepEqual(relative,[[412,316],[424,332],[436,348]],
    'the unchanged original relative handler accumulates PS/2 mouse movement');
  assert.equal(c[7175726],639);assert.equal(c[7175727],479,'no host SDL bookkeeping rewrite is required');
  assert.ok(a[28693764]>0);assert.equal(irq[0][0],964,'original mouse event/PIC scheduling remains active');
});
