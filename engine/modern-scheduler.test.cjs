const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm');
const {readFileSync,existsSync}=require('node:fs'),{createHash}=require('node:crypto');
const patch=JSON.parse(readFileSync(__dirname+'/modern-scheduler-patch.json','utf8'));
const path=__dirname+'/vendor/modern/wdosbox.js';
function checked(text,record){assert.equal(Buffer.byteLength(text),record.bytes);assert.equal(createHash('sha256').update(text).digest('hex'),record.sha256);}
function source(){const derived=readFileSync(path,'utf8');checked(derived,patch.derived);assert.equal(derived.split(patch.replace).length,2);const original=derived.replace(patch.replace,patch.search);checked(original,patch.source);return {derived,original};}
function scheduler(script){
  const begin=script.indexOf('function initMessageSyncSleep(worker)'),end=script.indexOf('function destroyAsyncify()',begin);
  assert.ok(begin>=0&&end>begin);let now=1000,next=0;const intervals=new Map(),messages=[];
  const context={Module:{sessionId:'calibration'},Date:{now:()=>now},postMessage:m=>messages.push(m),
    setInterval:fn=>{const id=++next;intervals.set(id,fn);return id;},clearInterval:id=>intervals.delete(id),
    self:{addEventListener(){},removeEventListener(){}}};
  vm.createContext(context);vm.runInContext(script.slice(begin,end)+';initMessageSyncSleep(true);',context);
  return {module:context.Module,intervals,messages,tick(ms=0){now+=ms;for(const fn of [...intervals.values()])fn();},
    reply(){context.Module.receive({data:{name:'wc-sync-sleep',props:{sessionId:'calibration'}}});}};
}
test('exact original pinned worker can wake a queued callback while paused',{skip:!existsSync(path)},()=>{
  const s=scheduler(source().original);let wakes=0;s.module.sync_sleep(()=>wakes++);s.module.paused=true;s.reply();assert.equal(wakes,1);
});
test('derived host scheduler retains original callback through pause and future wake deadline',{skip:!existsSync(path)},()=>{
  const s=scheduler(source().derived);let wakes=0;s.module.sync_sleep(()=>wakes++);s.module.wakeUpAt=1200;s.module.paused=true;
  s.reply();s.reply();assert.equal(s.intervals.size,1);assert.equal(wakes,0);assert.equal(s.messages.length,1);
  s.tick(300);assert.equal(wakes,0,'deadline cannot resume a paused guest');assert.equal(s.messages.length,1);
  s.module.paused=false;s.tick();assert.equal(wakes,1);assert.equal(s.intervals.size,0);assert.equal(s.module.sync_wakeUp,undefined);
});
test('paused scheduler releases its bounded host timer if worker exits',{skip:!existsSync(path)},()=>{
  const s=scheduler(source().derived);let wakes=0;s.module.sync_sleep(()=>wakes++);s.module.paused=true;s.reply();
  s.module.alive=false;s.tick();assert.equal(wakes,0);assert.equal(s.intervals.size,0);
});
