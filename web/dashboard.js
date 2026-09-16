/* One fixed-size Canvas2D composition powers both the live HUD and PNG export.
 * The game itself stays in its original same-origin iframe. No credentials,
 * arbitrary RPCs, remote image URLs, or synthetic game data enter this view. */
(function () {
  'use strict';
  const W = 1920, H = 1080;
  const GAME = Object.freeze({x: 32, y: 190, w: 1120, h: 840});
  const C = Object.freeze({bg: '#102735', deep: '#0a1923', ink: '#17323c', gold: '#e0bb72', mutedGold: '#bca16e', ivory: '#f4eedf', parchment: '#f4efe3', muted: '#b4c5c8', faint: '#748f99', line: '#3e5b63', paperLine: '#dcd3bf', teal: '#196b64', red: '#bd7053', white: '#fffbf2'});
  const STATUSES = new Set(['setup', 'starting', 'running', 'paused', 'victory', 'defeat', 'error']);
  const ACTIONS = new Set(['start', 'pause', 'resume']);
  const LENSES = ['Cities', 'Science', 'Diplomacy', 'War', 'Explore', 'Economy'];
  const secretPattern = /(?:Bearer\s+[^\s]+|apikey_[A-Za-z0-9_-]{16,}|sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})/gi;
  const obj = value => value !== null && typeof value === 'object' && !Array.isArray(value);
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const nonnegative = value => finite(value) && value >= 0;
  function text(value, limit = 160) {
    if (typeof value !== 'string' && !finite(value)) return '';
    return String(value).replace(secretPattern, '[redacted]').replace(/[\u0000-\u001f\u007f]/g, ' ').replace(/\s+/g, ' ').trim().slice(0, limit);
  }
  const number = value => finite(value) ? value : null;
  function probabilityTotalValid(values) {
    if (!values.length || values.some(p => !finite(p) || p < 0 || p > 1)) return false;
    const total = values.reduce((a,b) => a+b, 0);
    return Math.abs(total-1) <= 1e-6 ||
      ((Math.abs(total-.99) <= 1e-8 || Math.abs(total-1.01) <= 1e-8) && values.every(p => Math.abs(p*100-Math.round(p*100)) <= 1e-8));
  }
  function choiceGroup(name, answer, labels) {
    if (!obj(answer) || answer.type !== 'choice' || !obj(answer.probabilities)) return null;
    const entries = Object.entries(answer.probabilities);
    if (entries.length < 2 || entries.length > 255 || entries.some(([key]) => !key) || !probabilityTotalValid(entries.map(([,p])=>p))) return null;
    if (!Object.prototype.hasOwnProperty.call(answer.probabilities, answer.choice) || Math.abs(answer.probabilities[answer.choice]-Math.max(...entries.map(([,p])=>p))) > 1e-9) return null;
    if (answer.confidence !== undefined && (!finite(answer.confidence) || answer.confidence < 0 || answer.confidence > 1)) return null;
    return {name: text(name, 100), choice: answer.choice, confidence: number(answer.confidence), total: entries.reduce((sum,[,p])=>sum+p,0), options: entries.map(([id,p])=>({id, label: text(obj(labels) ? labels[id] : '', 160) || text(id, 160), p})).sort((a,b)=>b.p-a.p || Number(b.id===answer.choice)-Number(a.id===answer.choice) || a.id.localeCompare(b.id))};
  }
  function normalize(snapshot) {
    if (!obj(snapshot)) throw new TypeError('Dashboard snapshot must be an object.');
    const d = obj(snapshot.decision) ? snapshot.decision : {};
    const e = obj(snapshot.empire) ? snapshot.empire : {};
    const metadata = obj(d.metadata) ? d.metadata : {};
    const graph = obj(metadata.decision_graph) ? metadata.decision_graph : {};
    const labels = obj(d.labels) ? d.labels : {};
    const raw = obj(d.answers) ? d.answers : {};
    const entries = Object.entries(raw);
    const groups = entries.map(([name,answer])=>choiceGroup(name,answer,labels[name])).filter(Boolean);
    const invalid = entries.some(([name,answer])=>answer?.type === 'choice' && !choiceGroup(name,answer,labels[name]));
    const groupNames = new Set(groups.map(g=>g.name));
    const rootName = text(d.selected_question || graph.intent_question, 100);
    const childName = text(d.selected_action_question || graph.selected_action_question, 100);
    const pathInvalid = Boolean(rootName && !groupNames.has(rootName)) || Boolean(childName && !groupNames.has(childName)) || (groups.length>1 && !rootName && !childName);
    const selectedIntent = text(d.selected_intent || graph.selected_intent, 80);
    const root = groups.find(g=>g.name===rootName);
    const disagreement = Boolean(root && selectedIntent && root.choice!==selectedIntent);
    const rawReceipt = d.receipt;
    const receipt = ['pending','accepted','refused'].includes(rawReceipt) ? rawReceipt : null;
    return {
      status: STATUSES.has(snapshot.status) ? snapshot.status : 'setup', mode: snapshot.mode === 'replay' ? 'replay' : 'live',
      civilization: text(snapshot.civilization,50), turn: number(snapshot.turn), year: text(snapshot.year,30), message: text(snapshot.message,190),
      settings: Array.isArray(snapshot.settings) ? snapshot.settings.filter(obj).slice(0,6).map(s=>({label:text(s.label,30),value:text(s.value,60)})).filter(s=>s.label&&s.value) : [],
      empire: {cities:number(e.cities),population:number(e.population),treasury:number(e.treasury),net_income:number(e.net_income),science:number(e.science),research:text(e.research,70),research_turns:number(e.research_turns)},
      decision: {id:text(d.id,30),model:/^jev[a-zA-Z0-9._-]*$/.test(d.model) ? d.model : '',latency_ms:nonnegative(d.latency_ms ?? metadata.latency_ms) ? (d.latency_ms ?? metadata.latency_ms) : null,observed_turn:number(d.observed_turn),observed_revision:text(d.observed_revision,40),
        groups: invalid || pathInvalid || disagreement ? [] : groups,invalid:invalid||pathInvalid||disagreement,rootName,childName,selectedIntent,action_label:text(d.action_label,220),receipt,
        input_tokens:nonnegative(d.input_tokens ?? metadata.input_tokens_total) ? (d.input_tokens ?? metadata.input_tokens_total) : null},
      chronicle: Array.isArray(snapshot.chronicle) ? snapshot.chronicle.filter(obj).slice(-30).map((event,i)=>({id:text(event.id,40)||String(i),turn:number(event.turn),year:text(event.year,30),label:text(event.label,180),kind:text(event.kind,40)})).filter(event=>event.label) : [],
      playback_speed: finite(snapshot.playback_speed) && snapshot.playback_speed>0 ? snapshot.playback_speed : null,
      runtime_ready: snapshot.runtime_ready === true,
    };
  }
  function fitRect(width,height,bounds=GAME) {
    if (!finite(width)||!finite(height)||width<=0||height<=0) throw new TypeError('Invalid game image dimensions.');
    const ratio=Math.min(bounds.w/width,bounds.h/height), w=width*ratio,h=height*ratio;
    return {x:bounds.x+(bounds.w-w)/2,y:bounds.y+(bounds.h-h)/2,w,h};
  }
  function vectorLayout(decision) {
    const groups=decision.groups;
    if(!groups.length)return {panels:[],additional:[]};
    const primary=groups.find(g=>g.name===decision.childName)||groups.find(g=>g.name===decision.rootName)||groups[0];
    const root=groups.find(g=>g.name===decision.rootName);
    const ordered=[primary,...(root&&root!==primary?[root]:[]),...groups.filter(g=>g!==primary&&g!==root)];
    const shown=ordered.slice(0,3),count=shown.length;
    const plans=shown.map((g,i)=>{
      const limit=i===0?16:count===3?8:12,visible=Math.min(g.options.length,limit);
      const columns=i===0?(count===1?1:visible>(count===3?8:12)?2:1):(visible>4?2:1);
      return {group:g,role:i===0?'COMMAND CHOICE':g===root?'ROUTING CHOICE':'COMPANION · NOT DISPATCHED',visible,columns,rows:Math.ceil(visible/columns)};
    });
    const rowHeight=Math.min(43,Math.max(24,Math.floor((556-40*count-10*(count-1))/plans.reduce((n,p)=>n+p.rows,0))));
    let y=286;
    for(const plan of plans){plan.y=y;plan.rowHeight=rowHeight;plan.height=40+plan.rows*rowHeight;y+=plan.height+10;}
    return {panels:plans,additional:ordered.slice(3)};
  }
  function font(size=20,kind='sans',weight='normal') {
    return `${weight} ${size}px ${kind==='serif'?'Georgia, "Times New Roman", serif':kind==='mono'?'"Courier New", monospace':'Arial, Helvetica, sans-serif'}`;
  }
  function write(ctx,value,x,y,size=20,color=C.ivory,kind='sans',weight='normal',align='left') {
    ctx.font=font(size,kind,weight);ctx.fillStyle=color;ctx.textAlign=align;ctx.textBaseline='top';ctx.fillText(text(value,300),x,y);
  }
  function clipped(ctx,value,width,size=20,kind='sans',weight='normal') {
    ctx.font=font(size,kind,weight);let s=text(value,300);if(ctx.measureText(s).width<=width)return s;
    while(s.length && ctx.measureText(s+'…').width>width)s=s.slice(0,-1);return s+'…';
  }
  function wrapped(ctx,value,width,maxLines=2,size=20,kind='sans') {
    ctx.font=font(size,kind);const words=text(value,400).split(' '),lines=[];let line='';
    for(let i=0;i<words.length;i++) {
      const candidate=line?line+' '+words[i]:words[i];
      if(ctx.measureText(candidate).width<=width){line=candidate;continue;}
      if(lines.length===maxLines-1){line=clipped(ctx,[line,...words.slice(i)].join(' '),width,size,kind);break;}
      if(line)lines.push(line);line=clipped(ctx,words[i],width,size,kind);
    }
    if(line && lines.length<maxLines)lines.push(line);return lines;
  }
  function rect(ctx,x,y,w,h,fill,stroke,r=0) {
    ctx.beginPath();if(r)ctx.roundRect(x,y,w,h,r);else ctx.rect(x,y,w,h);if(fill){ctx.fillStyle=fill;ctx.fill();}if(stroke){ctx.strokeStyle=stroke;ctx.lineWidth=1;ctx.stroke();}
  }
  function rule(ctx,x,y,w,color=C.line){ctx.strokeStyle=color;ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(x,y+.5);ctx.lineTo(x+w,y+.5);ctx.stroke();}
  function diamond(ctx,x,y,size,color){ctx.fillStyle=color;ctx.beginPath();ctx.moveTo(x,y-size);ctx.lineTo(x+size,y);ctx.lineTo(x,y+size);ctx.lineTo(x-size,y);ctx.closePath();ctx.fill();}
  function laurels(ctx) {
    ctx.save();ctx.strokeStyle=C.gold;ctx.lineWidth=1.5;
    for(const sign of [-1,1])for(let i=0;i<6;i++) {
      const angle=(i/5)*1.1+.15,x=64+sign*Math.cos(angle)*23,y=41+Math.sin(angle)*22;
      ctx.beginPath();ctx.ellipse(x,y,5,2.1,sign*(angle+.5),0,Math.PI*2);ctx.stroke();
    }
    write(ctx,'II',64,24,31,C.gold,'serif','normal','center');ctx.restore();
  }
  const shown = value => value === null ? '—' : new Intl.NumberFormat('en-US',{maximumFractionDigits:1}).format(value);
  function probabilityText(p){return p>0&&p<.001?'<0.1%':(p*100).toFixed(Math.abs(p*100-Math.round(p*100))<1e-8?0:1)+'%';}
  function vectorName(name){return ({unit_action:'Unit orders',dialog_action:'Dialog choices',empire_strategy:'Empire strategy',intent:'Strategic direction'})[name]||name.replace(/^action_/, '').replace(/_/g,' ').replace(/^./,c=>c.toUpperCase());}
  function paintVector(ctx,plan){
    const {group,role,y,columns,visible,rows,rowHeight}=plan;
    const primary=role==='COMMAND CHOICE',color=primary?C.teal:'#8c6939';
    write(ctx,clipped(ctx,vectorName(group.name),325,17,'serif'),1208,y,17,C.ink,'serif');
    write(ctx,role,1864,y+3,10,primary?C.teal:'#927952','mono','normal','right');
    const columnWidth=columns===1?656:319,gap=18;
    group.options.slice(0,visible).forEach((option,index)=>{
      const col=columns===1?0:Math.floor(index/rows),row=columns===1?index:index%rows;
      const x=1208+col*(columnWidth+gap),top=y+27+row*rowHeight,selected=option.id===group.choice;
      const size=columns===1?18:16;
      if(selected)rect(ctx,x-7,top-3,columnWidth+14,rowHeight-3,primary?'#e0ece5':'#ede3ce',null,2);
      if(selected)diamond(ctx,x+2,top+8,3,color);
      const labelX=selected?x+13:x,labelWidth=columnWidth-(selected?66:53);
      write(ctx,clipped(ctx,option.label,labelWidth,size,'sans',selected?'bold':'normal'),labelX,top,size,C.ink,'sans',selected?'bold':'normal');
      write(ctx,probabilityText(option.p),x+columnWidth,top,size,C.ink,'mono',selected?'bold':'normal','right');
      const barY=top+Math.min(25,rowHeight-10),barWidth=columnWidth-2;
      rect(ctx,x,barY,barWidth,3,'#e0daca',null,1.5);
      if(option.p>0)rect(ctx,x,barY,Math.max(1,barWidth*option.p),3,selected?color:'#b9a477',null,1.5);
    });
    const notes=[];
    if(group.options.length>visible)notes.push(`+${group.options.length-visible} more options in trace`);
    if(Math.abs(group.total-1)>1e-6)notes.push(`API total ${(group.total*100).toFixed(0)}% · unchanged`);
    if(group.confidence!==null)notes.push(`confidence ${group.confidence.toFixed(2)}`);
    if(notes.length)write(ctx,notes.join('   ·   '),1208,y+27+rows*rowHeight,10,'#8a806b','mono');
  }
  function paint(ctx,s,view={},gameImage=null) {
    ctx.clearRect(0,0,W,H);ctx.fillStyle=C.bg;ctx.fillRect(0,0,W,H);
    const wash=ctx.createLinearGradient(0,0,W,H);wash.addColorStop(0,'#0c2230');wash.addColorStop(1,'#183d43');ctx.fillStyle=wash;ctx.fillRect(0,0,W,H);
    // Fixed, subtle geometry, never synthetic game information.
    ctx.save();ctx.globalAlpha=.10;for(let x=-500;x<W;x+=190){ctx.strokeStyle=C.gold;ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x+900,H);ctx.stroke();}ctx.restore();
    rect(ctx,0,0,W,4,C.gold);laurels(ctx);
    write(ctx,'JEV / CIVILIZATION II',113,23,34,C.ivory,'serif');
    write(ctx,'AN EMPIRE, ONE DECISION AT A TIME',115,62,11,C.mutedGold,'mono');
    const statusLabels={setup:'AWAITING GAME',starting:'STARTING EMULATOR',running:'GAME RUNNING',paused:'GAME PAUSED',victory:'VICTORY RECORDED',defeat:'DEFEAT RECORDED',error:'ATTENTION REQUIRED'};
    const statusColor=s.status==='error'||s.status==='defeat'?C.red:s.status==='victory'?C.gold:C.muted;
    diamond(ctx,1176,43,4,statusColor);write(ctx,statusLabels[s.status],1194,34,15,statusColor,'mono');
    write(ctx,s.mode==='replay'?'RECORDED REPLAY':'LIVE SESSION',1445,36,12,C.mutedGold,'mono');
    rule(ctx,32,88,1856);
    const stats=[['CIVILIZATION',s.civilization||'—',s.year||(s.turn!==null?'Turn '+shown(s.turn):'Year not observed')],['CITIES',shown(s.empire.cities),s.empire.population!==null?shown(s.empire.population)+' population':'Population not observed'],['TREASURY',s.empire.treasury!==null?shown(s.empire.treasury)+' gold':'—',s.empire.net_income!==null?(s.empire.net_income>0?'+':'')+shown(s.empire.net_income)+' / turn':'Income not observed'],['RESEARCH',s.empire.research||'—',s.empire.research_turns!==null?shown(s.empire.research_turns)+' turns remaining':s.empire.science!==null?shown(s.empire.science)+' science / turn':'Research not observed'],['JEV MODEL',s.decision.model||'—',s.decision.latency_ms!==null?shown(s.decision.latency_ms)+' ms latest response':'No model response yet']];
    const cols=[32,368,644,950,1420],widths=[306,246,276,440,466];
    stats.forEach(([label,value,note],i)=>{write(ctx,label,cols[i],106,12,C.mutedGold,'mono');write(ctx,clipped(ctx,value,widths[i],27,'serif'),cols[i],126,27,C.ivory,'serif');write(ctx,clipped(ctx,note,widths[i],13),cols[i],159,13,C.muted);if(i) {ctx.fillStyle=C.line;ctx.fillRect(cols[i]-20,110,1,57);}});
    rect(ctx,GAME.x-1,GAME.y-1,GAME.w+2,GAME.h+2,C.deep,C.mutedGold);
    if(gameImage){const fit=fitRect(gameImage.width,gameImage.height);ctx.imageSmoothingEnabled=false;ctx.drawImage(gameImage,fit.x,fit.y,fit.w,fit.h);}
    else {
      // The live iframe covers this placeholder as soon as the runtime is ready.
      ctx.save();ctx.strokeStyle='#2e4549';ctx.lineWidth=1;
      for(let i=0;i<5;i++){ctx.beginPath();ctx.arc(592,531,80+i*30,0,Math.PI*2);ctx.stroke();}
      for(let i=0;i<8;i++){const a=i*Math.PI/4;ctx.beginPath();ctx.moveTo(592+60*Math.cos(a),531+60*Math.sin(a));ctx.lineTo(592+210*Math.cos(a),531+210*Math.sin(a));ctx.stroke();}
      write(ctx,'CIVILIZATION II',592,503,40,C.gold,'serif','normal','center');
      write(ctx,s.status==='starting'?'Opening the original game…':'The world awaits',592,562,22,C.muted,'serif','normal','center');
      write(ctx,'Original game pixels appear here when the emulator is ready.',592,801,17,C.muted,'sans','normal','center');ctx.restore();
    }
    // Dense, distinct vectors fill the council. Only returned answers make bars.
    rect(ctx,1184,190,704,688,C.parchment,C.mutedGold,3);
    rect(ctx,1185,191,702,5,C.gold,null);
    write(ctx,'THE COUNCIL',1208,209,10,'#927952','mono');
    write(ctx,'The action space',1208,229,28,C.ink,'serif');
    write(ctx,'JEV PROBABILITIES',1864,238,10,'#927952','mono','normal','right');
    const layout=vectorLayout(s.decision);
    const observed=s.decision.observed_turn!==null?'Evaluated turn '+shown(s.decision.observed_turn):s.decision.observed_revision?'Evaluated revision '+s.decision.observed_revision:'No evaluated turn reported';
    write(ctx,layout.panels.length?clipped(ctx,observed+(s.decision.id?'  /  decision '+s.decision.id:''),646,11):'Waiting for the first decision',1208,263,11,'#857a65','mono');
    if(layout.panels.length) {
      layout.panels.forEach((panel,i)=>{if(i)rule(ctx,1208,panel.y-7,656,C.paperLine);paintVector(ctx,panel);});
      if(layout.additional.length)write(ctx,clipped(ctx,'Other returned vectors: '+layout.additional.map(g=>vectorName(g.name)).join(', '),656,11),1208,855,11,'#857a65');
    } else {
      if(s.decision.invalid)write(ctx,'Probability data unavailable',1208,304,19,C.red);
      else write(ctx,s.status==='setup'?'Connect the game to begin.':'The next observed position will appear here.',1208,304,18,'#887b62');
      LENSES.forEach((lens,i)=>{const x=1208+(i%2)*337,y=355+Math.floor(i/2)*79;rule(ctx,x,y,319,C.paperLine);write(ctx,lens,x,y+17,21,C.ink,'serif');write(ctx,'Not evaluated',x+319,y+23,11,'#9e927b','mono','normal','right');});
      if(s.settings.length){write(ctx,'THIS GAME',1208,663,10,'#927952','mono');s.settings.slice(0,4).forEach((setting,i)=>{write(ctx,clipped(ctx,setting.label,180,14),1208,690+i*30,14,'#8a7e68');write(ctx,clipped(ctx,setting.value,440,15),1864,688+i*30,15,C.ink,'sans','normal','right');});}
    }
    rect(ctx,1184,890,704,75,'#12363e',C.line,3);
    const receiptText={pending:'AWAITING GAME RECEIPT',accepted:'ORDER ACCEPTED',refused:'ORDER NOT ACCEPTED'};
    const receiptColor=s.decision.receipt==='refused'?C.red:C.gold;
    write(ctx,receiptText[s.decision.receipt]||'LATEST MODEL ORDER',1206,901,10,receiptColor,'mono');
    wrapped(ctx,s.decision.action_label||'Waiting for an order',651,2,17).forEach((line,i)=>write(ctx,line,1206,921+i*21,17,C.ivory));
    rect(ctx,1184,977,704,53,'#102a34',C.line,3);
    write(ctx,'CHRONICLE',1206,985,9,C.mutedGold,'mono');
    const events=s.chronicle.slice(-1);
    if(!events.length)write(ctx,'No events yet',1206,1003,14,C.faint);
    events.forEach((event,i)=>{const y=1003;diamond(ctx,1210,y+7,2.5,C.gold);const when=event.year||(event.turn!==null?'T'+shown(event.turn):'');write(ctx,clipped(ctx,when,94,12,'mono'),1224,y,12,C.mutedGold,'mono');write(ctx,clipped(ctx,event.label,when?520:628,14),when?1329:1224,y,14,C.muted);});
    rule(ctx,32,1047,1856);
    let settings=s.settings.map(item=>item.label+': '+item.value).join('   ·   ');
    if(!settings)settings='Scenario settings have not been reported';
    write(ctx,clipped(ctx,settings,1130,12),32,1061,12,C.muted,'mono');
    const connection=view.connection==='offline'?'TELEMETRY DISCONNECTED':s.mode==='replay'?'REPLAY'+(s.playback_speed!==null?'  '+s.playback_speed+'×':''):view.connection==='connecting'?'CONNECTING':'TELEMETRY CONNECTED';
    write(ctx,connection,1888,1061,11,view.connection==='offline'?C.red:C.mutedGold,'mono','normal','right');
    if(view.controlError||s.status==='error') {
      const message=text(view.controlError||s.message||'The controller needs attention.',180);
      rect(ctx,300,94,1320,72,'#3b2927',C.red,4);write(ctx,'ATTENTION',324,105,11,C.red,'mono');write(ctx,clipped(ctx,message,1260,19),324,128,19,C.ivory);
    }
  }
  const exported={normalize,choiceGroup,probabilityTotalValid,fitRect,vectorLayout,text,paint,W,H,GAME};
  if(typeof module!=='undefined'&&module.exports)module.exports=exported;
  if(typeof window==='undefined'||typeof document==='undefined')return;
  const canvas=document.getElementById('dashboard'),ctx=canvas.getContext('2d');
  const stage=document.getElementById('stage'),iframe=document.getElementById('game'),gameWindow=document.getElementById('game-window');
  const description=document.getElementById('screen-reader-state');
  let state=normalize({}),connection='connecting',controlError='',inFlight=false,polling=true,pollTimer=null,activeRequest=null,capturePending=null,seenSnapshot=false;
  function redraw(){paint(ctx,state,{connection,controlError});}
  function syncControls(){
    const blocked=inFlight||state.mode==='replay';
    const start=document.getElementById('start'),pause=document.getElementById('pause'),resume=document.getElementById('resume');
    start.hidden=!['setup','starting','error'].includes(state.status);pause.hidden=state.status!=='running';resume.hidden=state.status!=='paused';
    start.disabled=blocked||state.status==='starting';pause.disabled=blocked;resume.disabled=blocked;
  }
  function render(snapshot){
    state=normalize(snapshot);seenSnapshot=true;connection='connected';
    if(state.mode==='replay')setPolling(false);
    gameWindow.dataset.hidden=String(!(state.runtime_ready||['running','paused','victory','defeat'].includes(state.status)));
    description.textContent=[state.mode,state.status,state.civilization,state.year,state.turn!==null?'Turn '+state.turn:'',state.decision.action_label,state.decision.invalid?'Invalid model probabilities':''].filter(Boolean).join('. ');
    syncControls();redraw();return state;
  }
  function resize(){const scale=Math.min(window.innerWidth/W,window.innerHeight/H);stage.style.transform=`scale(${scale})`;}
  window.addEventListener('resize',resize);resize();gameWindow.dataset.hidden='true';syncControls();redraw();
  async function poll(){
    if(!polling)return;
    activeRequest=new AbortController();const timer=setTimeout(()=>activeRequest?.abort(),4000);
    try {
      const response=await fetch('/api/state',{cache:'no-store',signal:activeRequest.signal,credentials:'same-origin'});
      if(!response.ok)throw new Error('Telemetry unavailable');
      const data=await response.json();render(data);
    } catch(error){if(polling){connection='offline';redraw();}}
    finally{clearTimeout(timer);activeRequest=null;if(polling)pollTimer=setTimeout(poll,500);}
  }
  function setPolling(enabled){polling=enabled===true;clearTimeout(pollTimer);if(!polling){activeRequest?.abort();return;}if(!activeRequest)pollTimer=setTimeout(poll,0);}
  async function control(action){
    if(!ACTIONS.has(action)||inFlight||state.mode==='replay')return false;
    inFlight=true;controlError='';syncControls();redraw();
    const abort=new AbortController(),timeout=setTimeout(()=>abort.abort(),action==='start'?95000:45000);
    try {
      const response=await fetch('/api/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action}),credentials:'same-origin',signal:abort.signal});
      if(!response.ok)throw new Error('Control request was not accepted.');
      // State comes from /api/state. A successful HTTP request alone does not
      // establish that the emulator is running, paused, or that Jev is active.
      return true;
    } catch(error){controlError='The game control request was not completed. Check the local controller and try again.';document.getElementById('control-error').textContent=controlError;return false;}
    finally{clearTimeout(timeout);inFlight=false;syncControls();redraw();}
  }
  document.querySelectorAll('[data-action]').forEach(button=>button.addEventListener('click',()=>control(button.dataset.action)));
  async function captureGame(){
    let runtime;try{runtime=iframe.contentWindow.Civ2Runtime;}catch(error){throw new Error('Original game capture is unavailable.');}
    if(!runtime||typeof runtime.capture!=='function')throw new Error('Original game capture is unavailable.');
    let timer,png;
    try {png=await Promise.race([Promise.resolve().then(()=>runtime.capture()),new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('Original game capture timed out.')),10000);})]);}
    finally {clearTimeout(timer);}
    if(typeof png!=='string'||!png.startsWith('data:image/png;base64,')||png.length>32*1024*1024)throw new Error('Original game capture was not a bounded PNG image.');
    return png;
  }
  async function imageFromPNG(png){
    const image=new Image();image.src=png;
    let timer;try{await Promise.race([image.decode(),new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('Game capture decode timed out.')),5000);})]);}finally{clearTimeout(timer);}
    if(!image.naturalWidth||!image.naturalHeight||image.naturalWidth>4096||image.naturalHeight>4096)throw new Error('Game capture dimensions are invalid.');
    return image;
  }
  function capture(){
    if(capturePending)return capturePending;
    capturePending=(async()=>{
      if(!seenSnapshot)throw new Error('No dashboard observation has been received.');
      const snapshot=state,view={connection,controlError};
      const image=await imageFromPNG(await captureGame());
      const output=document.createElement('canvas');output.width=W;output.height=H;
      paint(output.getContext('2d'),snapshot,view,image);
      return output.toDataURL('image/png');
    })().finally(()=>{capturePending=null;});
    return capturePending;
  }
  window.Civ2Dashboard=Object.freeze({render,capture,captureGame,setPolling,setReplay(enabled){if(enabled){state={...state,mode:'replay'};setPolling(false);}else{state={...state,mode:'live'};setPolling(true);}syncControls();redraw();},version:1});
  if(window.location.protocol==='http:'||window.location.protocol==='https:')poll();
})();
