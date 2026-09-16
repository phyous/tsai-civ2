const assert = require('node:assert/strict');
const {readFileSync,existsSync} = require('node:fs');
const {createHash} = require('node:crypto');
const test = require('node:test');
const vm = require('node:vm');
const metadata=JSON.parse(readFileSync(__dirname+'/input-patch.json','utf8'));
const present=existsSync(__dirname+'/'+metadata.original)&&existsSync(__dirname+'/'+metadata.derived);
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');

test('derived runtime has only the hash-bound SDL export and instantiates that export',{skip:!present},()=>{
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
});

test('exact original SDL functions preserve relative deltas repeatedly at host edges',{skip:!present},()=>{
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
