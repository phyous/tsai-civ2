const assert=require('node:assert/strict');
const {readFileSync,existsSync}=require('node:fs');
const test=require('node:test');
const vm=require('node:vm');
const filename=__dirname+'/vendor/dosbox-sync.js';
const present=existsSync(filename);
function member(source,name,next) {
  const start=source.indexOf(name+':(function(');
  assert(start>=0);
  return source.slice(start+name.length+1,source.indexOf(','+next+':',start));
}
test('pinned main-loop resume fails on the empty main loop used by synchronous DOSBox',{skip:!present},()=>{
  const source=readFileSync(filename,'utf8');
  const start=source.indexOf('function _emscripten_set_main_loop(');
  const loop=source.slice(start,source.indexOf('var Browser={',start));
  const timingStart=source.indexOf('function _emscripten_set_main_loop_timing(');
  const timing=source.slice(timingStart,source.indexOf('function _emscripten_get_now(',timingStart));
  const context={Module:{},Browser:{mainLoop:{func:null,arg:0,timingMode:0,timingValue:0,scheduler:null,currentlyRunningMainloop:0}},assert:assert.ok};
  vm.createContext(context);vm.runInContext(timing+loop+';Browser.mainLoop.resume='+member(source,'resume','updateStatus'),context);
  assert.throws(()=>context.Browser.mainLoop.resume(),/scheduler/);
});
test('pinned async callback queue parks and resumes a yielded interpreter callback',{skip:!present},()=>{
  const source=readFileSync(filename,'utf8'),timers=[];
  const context={Module:{},ABORT:false,setTimeout(fn){timers.push(fn);},Browser:{allowAsyncCallbacks:true,queuedAsyncCallbacks:[]}};
  vm.createContext(context);
  for(const [name,next] of [['pauseAsyncCallbacks','resumeAsyncCallbacks'],['resumeAsyncCallbacks','safeRequestAnimationFrame'],['safeSetTimeout','safeSetInterval']])
    vm.runInContext('Browser.'+name+'='+member(source,name,next),context);
  let calls=0;
  context.Browser.safeSetTimeout(()=>calls++,0);
  context.Browser.pauseAsyncCallbacks();timers.shift()();
  assert.equal(calls,0);assert.equal(context.Browser.queuedAsyncCallbacks.length,1);
  context.Browser.resumeAsyncCallbacks();assert.equal(calls,1);
  context.Browser.resumeAsyncCallbacks();assert.equal(calls,1);
});
