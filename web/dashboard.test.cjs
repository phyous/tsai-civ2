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

const {historyLayout}=require('./dashboard.js');
function recorded(id, options={exit:.8,buy:.2},stage='command') {
  return {id,observed_turn:3,stage,executes_input:stage!=='planning',selected_question:'city_action',
    answers:{city_action:answer(options),empire_strategy:answer({Cities:.6,Economy:.4})},
    labels:{city_action:{exit:'Exit city',buy:'Open quote'}}};
}
test('recent panels use only actual earlier primary vectors and drop malformed duplicate future records',()=>{
  const invalid=recorded(3,{a:.8,b:.3});
  const s=normalize({decision:recorded(6),recent_decisions:[recorded(1),recorded(2),invalid,recorded(4),recorded(4),recorded(6),recorded(8)]});
  assert.deepEqual(s.recent_decisions.map(d=>d.id),['4','2','1']);
  assert.ok(s.recent_decisions.every(d=>d.groups.length===1&&d.groups[0].name==='city_action'));
  assert.equal(s.recent_decisions[0].groups[0].options[0].p,.8);
  assert.deepEqual(normalize({recent_decisions:[recorded(1)]}).recent_decisions,[]);
});
test('spare council space shows three clearly separate historical cards without changing current vectors',()=>{
  const current=recorded(4);
  current.answers.empire_strategy=answer({Cities:.5,Economy:.1,Science:.1,Diplomacy:.1,War:.1,Explore:.1});
  const s=normalize({decision:current,recent_decisions:[recorded(1),recorded(2),recorded(3)]});
  const layout=vectorLayout(s.decision),before=JSON.stringify(layout),history=historyLayout(layout,s.recent_decisions);
  assert.equal(history.cards.length,3);assert.equal(JSON.stringify(layout),before);
  assert.ok(history.y>Math.max(...layout.panels.map(p=>p.y+p.height)));
  assert.ok(history.cards.every(card=>card.y+card.height<=864));
});
test('sixteen current options retain their full original space and displace history',()=>{
  const options=Object.fromEntries(Array.from({length:16},(_,i)=>['action'+i,1/16]));
  const current=recorded(4,options);
  current.answers.empire_strategy=answer({Cities:.5,Economy:.1,Science:.1,Diplomacy:.1,War:.1,Explore:.1});
  const s=normalize({decision:current,recent_decisions:[recorded(1),recorded(2),recorded(3)]});
  const layout=vectorLayout(s.decision);assert.equal(layout.panels[0].visible,16);
  assert.equal(historyLayout(layout,s.recent_decisions).cards.length,0);
});
test('historical objectives stay distinct from command decisions and remain immutable sanitized data',()=>{
  const prior=recorded(1,{survey:.6,hold:.39},'planning');
  prior.labels.city_action={survey:'Bearer synthetic-not-real',hold:'Hold'};
  const s=normalize({decision:recorded(2),recent_decisions:[prior]});
  prior.answers.city_action.probabilities.survey=0;
  assert.equal(s.recent_decisions[0].stage,'planning');assert.equal(s.recent_decisions[0].receipt,null);
  assert.equal(s.recent_decisions[0].groups[0].options[0].p,.6);
  assert.equal(s.recent_decisions[0].groups[0].total,.99);
  assert.equal(s.recent_decisions[0].groups[0].options[0].label,'[redacted]');
});

 test('category planning retains its real vector and never claims dispatch',()=>{
  const s=normalize({decision:{stage:'planning_category',executes_input:false,receipt:'accepted',selected_question:'task_category',answers:{task_category:answer({settle:.8,hold:.2})}}});
  assert.equal(s.decision.stage,'planning_category');assert.equal(s.decision.receipt,null);
  assert.equal(vectorLayout(s.decision).panels[0].role,'OBJECTIVE CATEGORY');
  assert.deepEqual(s.decision.groups[0].options.map(x=>x.p),[.8,.2]);
  const unsafe=normalize({decision:{stage:'planning_category',executes_input:true}});
  assert.equal(unsafe.decision.stage,'command');
});

test('compatible live category envelope preserves distinct category display',()=>{
 const s=normalize({decision:{stage:'planning',planning_phase:'category',executes_input:false,selected_question:'task_category',answers:{task_category:answer({settle:.7,hold:.3})}}});
 assert.equal(s.decision.stage,'planning_category');assert.equal(s.decision.receipt,null);
 assert.equal(vectorLayout(s.decision).panels[0].role,'OBJECTIVE CATEGORY');
});
