const {test}=require('node:test');
const assert=require('node:assert/strict');
const {normalize,choiceGroup,probabilityTotalValid,fitRect,vectorLayout,text,GAME}=require('./dashboard.js');
const answer=(p,choice=Object.keys(p)[0])=>({type:'choice',choice,probabilities:p,confidence:.4});

test('empty snapshot does not manufacture game progress or decisions',()=>{
  const s=normalize({});assert.equal(s.status,'setup');assert.equal(s.turn,null);
  assert.equal(s.empire.cities,null);assert.equal(s.empire.treasury,null);
  assert.deepEqual(s.decision.groups,[]);assert.deepEqual(s.settings,[]);
});
test('actual probabilities and valid tied maximum stay unchanged',()=>{
  const g=choiceGroup('action',answer({a:.5,b:.5},'b'),{a:'Build a city',b:'Explore'});
  assert.equal(g.options[0].id,'b');assert.equal(g.options[0].p,.5);assert.equal(g.options[0].label,'Explore');
});
test('observed rounding compatibility does not renormalize',()=>{
  const g=choiceGroup('action',answer({a:.66,b:.33}),{});
  assert.equal(g.total,.99);assert.equal(g.options[0].p,.66);
  assert.equal(probabilityTotalValid([.331,.659]),false);
  assert.equal(probabilityTotalValid([.50,.48]),false);
});
test('untrusted malformed probabilities fail closed without erasing actual resources',()=>{
  for(const probabilities of [{a:NaN,b:.2},{a:-.1,b:1.1},{a:.6,b:.2},{a:true,b:0},{a:1}]) {
    const s=normalize({empire:{treasury:42},decision:{answers:{action:answer(probabilities)}}});
    assert.equal(s.decision.invalid,true);assert.deepEqual(s.decision.groups,[]);assert.equal(s.empire.treasury,42);
  }
  assert.equal(choiceGroup('a',answer({a:.9,b:.1},'b'),{}),null);
});
test('graph path cannot name a missing question or contradict the root answer',()=>{
  const common={answers:{intent:answer({Science:.8,War:.2})},selected_question:'intent'};
  assert.equal(normalize({decision:{...common,selected_action_question:'not_returned'}}).decision.invalid,true);
  assert.equal(normalize({decision:{...common,selected_intent:'War'}}).decision.invalid,true);
  assert.equal(normalize({decision:{...common,selected_intent:'Science'}}).decision.invalid,false);
  assert.equal(normalize({decision:{answers:{intent:answer({Science:.8,War:.2}),companion:answer({a:.5,b:.5})}}}).decision.invalid,true);
});
test('existing graph metadata is compatible',()=>{
  const s=normalize({decision:{answers:{intent:answer({Science:.8,War:.2}),action_science:answer({bronze:.7,pottery:.3})},metadata:{decision_graph:{intent_question:'intent',selected_intent:'Science',selected_action_question:'action_science'}}}});
  assert.equal(s.decision.groups.length,2);assert.equal(s.decision.childName,'action_science');
});
test('sensitive-looking text and control characters cannot enter output labels',()=>{
  const fake='apikey_'+'x'.repeat(30);
  assert.equal(text('Bearer not-a-real-token'), '[redacted]');
  assert.equal(text(fake),'[redacted]');assert.equal(text('Rome\n\u0000I'),'Rome I');
  assert.equal(text({secret:fake}), '');assert.equal(text('x'.repeat(1000),40).length,40);
});
test('unknown unsafe fields are dropped and mutable input cannot replace stored statistics',()=>{
  const raw={api_key:'synthetic',empire:{treasury:17},settings:[{label:'Map',value:'Observed map'}]};
  const s=normalize(raw);raw.empire.treasury=1000;raw.settings[0].value='changed';
  assert.equal(s.empire.treasury,17);assert.equal(s.settings[0].value,'Observed map');assert.equal('api_key' in s,false);
});
test('game fitting preserves aspect and includes all original pixels',()=>{
  assert.deepEqual(fitRect(640,480),GAME);
  const wide=fitRect(1600,900);assert.equal(wide.w,GAME.w);assert.ok(wide.h<GAME.h);
  assert.equal(wide.x,GAME.x);assert.ok(wide.y>GAME.y);
  const tall=fitRect(600,800);assert.equal(tall.h,GAME.h);assert.ok(tall.w<GAME.w);
  assert.throws(()=>fitRect(0,480));assert.throws(()=>fitRect(Infinity,480));
});
test('telemetry bounds labels and history without creating events',()=>{
  const s=normalize({chronicle:Array.from({length:50},(_,i)=>({id:String(i),label:'Event '+i})),settings:Array.from({length:10},()=>({label:'Map',value:'Actual'}))});
  assert.equal(s.chronicle.length,30);assert.equal(s.chronicle[0].id,'20');assert.equal(s.settings.length,6);
});

test('dense action space retains16 real options with a distinct advisory vector',()=>{
  const p=Object.fromEntries(Array.from({length:16},(_,i)=>['order_'+i,1/16]));
  const s=normalize({decision:{selected_question:'unit_action',answers:{unit_action:answer(p),empire_strategy:answer({Cities:.5,Economy:.1,Science:.1,Diplomacy:.1,War:.1,Explore:.1})}}});
  const layout=vectorLayout(s.decision);
  assert.equal(layout.panels.length,2);assert.equal(layout.panels[0].visible,16);assert.equal(layout.panels[0].columns,2);
  assert.equal(layout.panels[1].role,'COMPANION · NOT DISPATCHED');assert.equal(layout.panels[1].visible,6);
  for(const panel of layout.panels)assert.ok(panel.y+panel.height<=878);
});

test('routing and companion vectors stay separate and in the panel bounds',()=>{
  const many=Object.fromEntries(Array.from({length:24},(_,i)=>['choice_'+i,1/24]));
  const s=normalize({decision:{selected_question:'intent',selected_action_question:'action_war',selected_intent:'War',answers:{intent:answer({War:.8,Cities:.2}),action_war:answer(many),empire_strategy:answer({War:.7,Cities:.3})}}});
  const layout=vectorLayout(s.decision);
  assert.equal(layout.panels[0].visible,16);assert.equal(layout.panels[1].role,'ROUTING CHOICE');assert.equal(layout.panels[2].role,'COMPANION · NOT DISPATCHED');
  for(const panel of layout.panels)assert.ok(panel.y+panel.height<=878);
  assert.deepEqual(vectorLayout(normalize({}).decision),{panels:[],additional:[]});
});

test('planning probabilities choose an objective without claiming a game command',()=>{
  const s=normalize({decision:{stage:'planning',executes_input:false,receipt:'accepted',selected_question:'task_choice',answers:{task_choice:answer({survey:.8,hold:.2})}}});
  assert.equal(s.decision.stage,'planning');assert.equal(s.decision.receipt,null);
  assert.equal(vectorLayout(s.decision).panels[0].role,'OBJECTIVE CHOICE');
  const command=normalize({decision:{stage:'planning',executes_input:true}});
  assert.equal(command.decision.stage,'command');
  const dispatched=normalize({decision:{stage:'command',receipt:'dispatched'}});
  assert.equal(dispatched.decision.receipt,'dispatched');
  assert.notEqual(dispatched.decision.receipt,'accepted');
});
