const assert=require('node:assert/strict');
const {readFileSync,existsSync}=require('node:fs');
const {createHash}=require('node:crypto');
const test=require('node:test');
const vm=require('node:vm');
const path=require('node:path');
const runtimePath=__dirname+'/vendor/dosbox-sync.js';
const browserPath=__dirname+'/vendor/browserfs.min.js';
const present=existsSync(runtimePath)&&existsSync(browserPath);

function pinnedFilesystem() {
  const source=readFileSync(runtimePath,'utf8');
  assert.equal(createHash('sha256').update(source).digest('hex'),
    'e73cd0b0130b2428863f000f3c9a77daf554b8dbed7d4fac02b1ec092871812a');
  const BrowserFS=require(browserPath);
  BrowserFS.initialize(new BrowserFS.FileSystem.InMemory());
  const nodefs=BrowserFS.BFSRequire('fs');nodefs.mkdirSync('/saves');
  const streams=new Set();
  const FS={isFile:()=>true,ErrnoError:Error};
  const adapter=new BrowserFS.EmscriptenFS(FS,path.posix,{},nodefs);
  adapter.realPath=node=>node.path;
  const flags={r:0,w:577,wx:705};
  Object.assign(FS,{
    open(filename,mode){
      const stream={node:{path:filename,mode:0},flags:flags[mode]};
      adapter.stream_ops.open(stream);streams.add(stream);return stream;
    },
    write:(...args)=>adapter.stream_ops.write(...args),
    read:(...args)=>adapter.stream_ops.read(...args),
    close(stream){adapter.stream_ops.close(stream);streams.delete(stream);},
    stat:filename=>nodefs.statSync(filename),
  });
  const context={FS,Uint8Array,Module:{}};vm.createContext(context);
  for(const name of ['lengthBytesUTF8','stringToUTF8Array']) {
    const begin=source.indexOf('function '+name+'(');
    const end=source.indexOf('Module["'+name+'"]',begin);
    assert(begin>=0&&end>begin);vm.runInContext(source.slice(begin,end),context);
  }
  for(const [name,next] of [['writeFile','cwd'],['readFile','writeFile']]) {
    const begin=source.indexOf(name+':(function(');
    const end=source.indexOf(','+next+':',begin);
    assert(begin>=0&&end>begin);
    vm.runInContext('FS.'+name+'='+source.slice(begin+name.length+1,end),context);
  }
  return {FS,streams};
}

test('actual pinned default writeFile truncates then rejects Uint8Array as UTF-8',{skip:!present},()=>{
  const {FS,streams}=pinnedFilesystem();
  assert.throws(()=>FS.writeFile('/saves/broken.sav',new Uint8Array([0,128,255])),/charCodeAt/);
  assert.equal(FS.stat('/saves/broken.sav').size,0);
  assert.equal(streams.size,1,'old writeFile has no finally to close after conversion failure');
  for(const stream of streams)FS.close(stream);
});

test('pinned binary API and BrowserFS stream adapter preserve a 70 KiB native byte array',{skip:!present},()=>{
  const {FS,streams}=pinnedFilesystem();
  const bytes=Uint8Array.from({length:70*1024},(_,index)=>(index*127)&255);
  FS.writeFile('/saves/binary.sav',bytes,{encoding:'binary',flags:'wx'});
  assert.deepEqual(FS.readFile('/saves/binary.sav',{encoding:'binary'}),bytes);
  const stream=FS.open('/saves/restore.sav','wx');
  try {assert.equal(FS.write(stream,bytes,0,bytes.length,0),bytes.length);}
  finally {FS.close(stream);}
  assert.deepEqual(FS.readFile('/saves/restore.sav',{encoding:'binary'}),bytes);
  assert.equal(streams.size,0);
  assert.throws(()=>FS.open('/saves/restore.sav','wx'));
  assert.deepEqual(FS.readFile('/saves/restore.sav'),bytes,'exclusive open cannot truncate an existing save');
});
