'use strict';

// Apply the saved preference before CSS is painted; storage may be unavailable.
const themeKey='tymetro.theme', systemTheme=matchMedia('(prefers-color-scheme: dark)');
let themePreference=null;
try { const saved=localStorage.getItem(themeKey);if(['light','dark'].includes(saved))themePreference=saved; } catch {}
function applyTheme(theme) {
  document.documentElement.dataset.theme=theme;
  document.querySelector('meta[name="theme-color"]').content=theme==='dark'?'#111923':'#f3f1eb';
  document.querySelectorAll('[data-theme-choice]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.themeChoice===theme)));
}
applyTheme(themePreference||(systemTheme.matches?'dark':'light'));
systemTheme.addEventListener('change',event=>{if(!themePreference)applyTheme(event.matches?'dark':'light');});
window.addEventListener('storage',event=>{
  if(event.key!==themeKey&&event.key!==null)return;
  themePreference=['light','dark'].includes(event.newValue)?event.newValue:null;
  applyTheme(themePreference||(systemTheme.matches?'dark':'light'));
});

document.addEventListener('DOMContentLoaded',()=>{
  applyTheme(document.documentElement.dataset.theme);
  document.querySelectorAll('[data-theme-choice]').forEach(button=>button.addEventListener('click',()=>{
    themePreference=button.dataset.themeChoice;applyTheme(themePreference);
    try {localStorage.setItem(themeKey,themePreference);}catch {}
  }));

const $ = id => document.getElementById(id);
const node = (tag, cls, text) => { const n=document.createElement(tag); if(cls)n.className=cls; if(text!==undefined)n.textContent=text; return n; };
const svgNode = (tag, attrs={}) => { const n=document.createElementNS('http://www.w3.org/2000/svg',tag); for(const [k,v] of Object.entries(attrs))n.setAttribute(k,v); return n; };
function icon(name) { const n=svgNode('svg',{class:'icon','aria-hidden':'true'});n.append(svgNode('use',{href:`#i-${name}`}));return n; }
let meta=null, busy=false, connectionError=false, sessionId=null, conversation=[], latest=null, requestController=null, requestSequence=0, modelPoll=null;
let selection={origin:'A1',destination:'A13'}, editing='origin';
const mobileMap=matchMedia('(max-width:520px)');
const stationData=code=>meta?.stations.find(s=>s.code===code);
const shortName=code=>code==='A1'?'台北車站':(stationData(code)?.zh || code).replace(/^機場(?=第)/,'').replace(/站$/,'');
const stationLabel=code=>`${code} ${stationData(code)?.zh || ''}`.trim();
const trainType=()=>document.querySelector('input[name="train-type"]:checked').value || null;
const selectedAt=()=>`${$('date').value}T${$('time').value}:00+08:00`;
const currentQuery=()=>({...selection,train_type:trainType(),at:selectedAt()});
const ready=()=>Boolean(meta && (meta.engine!=='qwen' || meta.model_status==='ready'));
let spaceClient=null;
async function queryBackend(sent,signal){
  if(meta.transport!=='gradio'){
    const response=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(sent),signal});
    const data=await response.json();
    if(!response.ok)throw new Error(data.message||'查詢未完成，請確認條件後重試。');
    return data;
  }
  if(!spaceClient){
    const {Client}=await import('/gradio-client.js');
    spaceClient=await Client.connect(location.origin);
  }
  signal.throwIfAborted();
  const job=spaceClient.submit('/chat',{payload:sent});
  const cancel=()=>job.cancel();
  signal.addEventListener('abort',cancel,{once:true});
  try{
    for await(const event of job){
      signal.throwIfAborted();
      if(event.type==='data'){
        const data=event.data[0];
        if(data.error)throw new Error(data.message||'雲端查詢未完成，請稍後重試。');
        return data;
      }
      if(event.type==='status'&&event.stage==='error')throw new Error(event.message||'雲端 GPU 暫時無法使用，請稍後重試。');
    }
    signal.throwIfAborted();
    throw new Error('雲端尚未回傳班次，請稍後重試。');
  }finally{signal.removeEventListener('abort',cancel);}
}
function formError(message=''){ $('form-error').textContent=message;$('form-error').hidden=!message; }

function routePath(points, columns) {
  if(!points.length)return '';
  let d=`M ${points[0].x} ${points[0].y}`;
  for(let i=1;i<points.length;i++) {
    const a=points[i-1], b=points[i];
    if(a.row===b.row)d+=` L ${b.x} ${b.y}`;
    else { const edge=a.row%2===0?columns*100-5:5;d+=` L ${edge} ${a.y} L ${edge} ${b.y} L ${b.x} ${b.y}`; }
  }
  return d;
}
function renderMap() {
  if(!meta)return;
  const map=$('station-map'), focused=document.activeElement?.dataset?.station;
  const columns=mobileMap.matches?4:8, rowHeight=mobileMap.matches?72:82, rows=Math.ceil(meta.stations.length/columns);
  const points=meta.stations.map((s,i)=>{const row=Math.floor(i/columns),col=row%2===0?i%columns:columns-1-i%columns;return {x:col*100+50,y:row*rowHeight+14,row,col};});
  const start=meta.stations.findIndex(s=>s.code===selection.origin), end=meta.stations.findIndex(s=>s.code===selection.destination);
  const low=Math.min(start,end),high=Math.max(start,end);
  const svg=svgNode('svg',{class:'map-track',viewBox:`0 0 ${columns*100} ${rows*rowHeight}`,preserveAspectRatio:'none','aria-hidden':'true'});
  svg.append(svgNode('path',{class:'track-base',d:routePath(points,columns)}));
  if(low>=0)svg.append(svgNode('path',{class:'track-selected',d:routePath(points.slice(low,high+1),columns)}));
  map.replaceChildren(svg);
  meta.stations.forEach((s,i)=>{
    const origin=s.code===selection.origin,destination=s.code===selection.destination;
    const b=node('button',`map-station${i>=low&&i<=high?' in-range':''}${origin?' is-origin':''}${destination?' is-destination':''}`);
    b.type='button';b.dataset.station=s.code;b.style.gridColumn=String(points[i].col+1);b.style.gridRow=String(points[i].row+1);
    b.setAttribute('aria-label',`${s.code} ${s.zh}，設為${editing==='origin'?'出發站':'目的站'}`);b.setAttribute('aria-pressed',String(origin||destination));b.title=stationLabel(s.code);b.disabled=busy||!ready();
    b.append(node('span','station-point'),node('span','station-code',s.code),node('span','station-name',shortName(s.code)));
    b.addEventListener('click',()=>{
      selection[editing]=s.code;formError();
      if(editing==='origin')editing='destination';
      renderSelection();renderResult();
      // The map is rebuilt; preserve keyboard focus at the clicked station.
      map.querySelector(`[data-station="${s.code}"]`)?.focus({preventScroll:true});
    });
    map.append(b);
  });
  if(focused)map.querySelector(`[data-station="${focused}"]`)?.focus({preventScroll:true});
}
function renderSelection() {
  $('journey-summary-route').textContent=`${selection.origin} → ${selection.destination}`;
  for(const key of ['origin','destination']) {
    $(`${key}-code`).textContent=selection[key];$(`${key}-name`).textContent=shortName(selection[key]);
    const b=$(`${key}-picker`);
    b.setAttribute('aria-label',`${key==='origin'?'選擇出發站':'選擇目的站'}：${stationLabel(selection[key])}`);
    b.setAttribute('aria-pressed',String(key===editing));
    b.classList.toggle('is-editing',key===editing);
  }
  $('map-instruction').textContent=editing==='origin'?'① 點選車站，設定出發站':'② 點選車站，設定目的站';
  renderMap();
}
function setNow(){const s=new Date(Date.now()+8*3600000).toISOString().slice(0,16);$('date').value=s.slice(0,10);$('time').value=s.slice(11,16);formError();renderResult();}
function emptyResult() {
  const box=node('div','empty-result'),symbol=node('div','empty-symbol');symbol.append(icon('train'));
  box.append(symbol,node('p','','選好旅程查班次，或直接輸入問題。'));return box;
}
function renderResult() {
  $('journey-summary-time').textContent=$('date').value?`${$('date').value.slice(5).replace('-','/')} ${$('time').value} · ${trainType()||'全部車種'}`:'';
  const area=$('result-area');area.replaceChildren();area.setAttribute('aria-busy',String(busy));
  if(busy){const loading=node('div','loading-result');loading.append(node('span','spinner'),node('span','','正在查詢這一程…'),node('small','','核對車種、停靠站與發車時間'));area.append(loading);return;}
  if(!latest){area.append(emptyResult());if(connectionError){area.append(node('p','error-message','無法連線到本機服務。'));const retry=node('button','retry','重新連線');retry.addEventListener('click',connect);area.append(retry);}return;}
  if(latest.error){area.append(node('p','error-message',latest.message));return;}
  const data=latest.data, result=data.result, query=latest.query;
  if(query && JSON.stringify(query)!==JSON.stringify(currentQuery()))area.append(node('p','dirty-note','選項已更改。以下保留上次結果，請重新查詢。'));
  if(result){
    const boundary=result.query_mode==='last'||result.query_mode==='first';
    const boundaryLabel=result.query_mode==='last'?'末班車':'首班車';
    const heading=node('div','result-route');
    for(const [i,code] of [result.origin,result.destination].entries()){if(i)heading.append(icon('arrow'));const label=node('div');label.append(node('strong','',code),node('span','',shortName(code)));heading.append(label);}
    const queryLabel=boundary?`${result.service_date} 營運日 · ${boundaryLabel}`:result.query_time.slice(0,16).replace('T',' ');
    area.append(heading,node('p','result-query',`${queryLabel} · 臺灣時間 · ${result.requested_train_type || '全部車種'}`));
    if(result.status==='ok' && result.next_trains.length){
      for(const train of result.next_trains){
        const row=node('article',`train-row${train.train_type.includes('直達')?' express':''}`);
        const time=node('div','train-time',train.departure.slice(11,16));time.append(node('small','',`${train.departure.slice(5,10).replace('-','/')} ${boundary?boundaryLabel+' · ':''}預定發車`));
        const wait=node('div','train-wait'),seconds=(new Date(train.departure)-new Date(result.query_time))/1000;
        if(boundary&&seconds<0)wait.textContent='預定時間已過';
        else if(boundary&&seconds<=180)wait.textContent='3 分鐘內，請勿趕車';
        else wait.append(node('b','',String(Math.floor(seconds/60))),document.createTextNode('分鐘後'));
        const bottom=node('div','train-row-bottom');bottom.append(node('span','train-type',train.train_type),node('span','train-detail',`終點 ${stationLabel(train.terminal)}`));
        row.append(time,wait,bottom);area.append(row);
      }
      area.append(node('p','alight-note',`可到 ${stationLabel(result.destination)}，不需換車。`));
      if(boundary) {
        if(result.departure_state==='passed')area.append(node('p','result-warning',`${boundaryLabel}預定時間已過。${result.query_mode==='last'?'本營運日沒有更晚的符合條件班次，請洽站務人員。':'可另查後續班次。'}`));
        else if(result.departure_state==='imminent')area.append(node('p','result-warning',`3 分鐘內發車，請勿趕車。${result.query_mode==='last'?'這是末班，沒有更晚的符合條件班次，請洽站務人員。':'可考慮後續班次。'}`));
      } else {
        if(result.imminent_departures?.length)area.append(node('p','result-warning','另有 3 分鐘內發車的班次，建議改搭上述較晚班次，避免趕車奔跑。'));
        if(result.remaining_departures===1)area.append(node('p','result-warning','這是本營運日最後一班符合條件的班次。'));
      }
    } else area.append(node('p','result-answer',data.answer.zh));
  } else area.append(node('p','result-answer',data.answer.zh));
  if(data.raw_output){
    const evidence=node('details','evidence');evidence.append(node('summary','','查詢依據'));
    evidence.append(node('p','',`Qwen3 4B · ${data.elapsed_seconds} 秒。班次顯示依核對後的資料產生；原始模型文字可能有誤。`));
    evidence.append(node('pre','',JSON.stringify({sent_query:latest.sent,confirmed_query:data.confirmed_query,raw_model:data.raw_output},null,2)));area.append(evidence);
  }
}
function renderChat(){
  const log=$('chat-log');log.replaceChildren();
  $('chat-choices').replaceChildren();
  $('conversation-history').hidden=!conversation.length;
  $('history-count').textContent=`· ${conversation.length} 則`;
  for(const item of conversation){
    const message=node('div',`chat-message ${item.role}`);
    message.append(node('strong','chat-author',item.role==='user'?'你':'機捷助手'),node('p','chat-bubble',item.text));
    log.append(message);
  }
  const candidates=latest?.data?.candidates;
  if(candidates?.length){const choices=node('div','candidate-buttons');for(const code of candidates){const b=node('button','',stationLabel(code));b.type='button';b.disabled=busy;b.addEventListener('click',()=>send({message:code}));choices.append(b);}$('chat-choices').append(choices);}
  log.scrollTop=log.scrollHeight;
}
function setBusy(value){
  busy=value;const unavailable=!ready();
  for(const id of ['origin-picker','destination-picker','swap','date','time','now','search','send','reset'])$(id).disabled=value||unavailable;
  document.querySelectorAll('input[name="train-type"]').forEach(input=>input.disabled=value||unavailable||(meta?.engine!=='qwen'&&Boolean(input.value)));
  renderMap();renderResult();renderChat();
}
function sameQuery(a,b){return a&&b&&a.origin===b.origin&&a.destination===b.destination&&a.train_type===b.train_type&&new Date(a.at).getTime()===new Date(b.at).getTime();}
async function send(body){
  if(busy||!ready())return;
  if(!$('journey-form').reportValidity())return;
  if(body.route && body.route.origin===body.route.destination){formError('出發站與目的站相同，請選擇不同車站。');return;}
  formError();const at=selectedAt(), query=currentQuery(), sequence=++requestSequence;
  // Capture exact selections once. Subsequent UI edits cannot mutate the request.
  const sent=JSON.parse(JSON.stringify({...body,at,session_id:sessionId}));
  if(body.message){conversation.push({role:'user',text:body.message});conversation=conversation.slice(-12);$('conversation-history').open=true;}
  setBusy(true);requestController=new AbortController();const controller=requestController;
  const timeout=setTimeout(()=>controller.abort(),meta.transport==='gradio'?300000:meta.engine==='qwen'?180000:20000);
  try {
    const data=await queryBackend(sent,controller.signal);
    if(sequence!==requestSequence)return;
    if(body.route && meta.engine==='qwen' && !sameQuery(query,data.confirmed_query))throw new Error('回傳的查詢條件與選項不一致，已停止顯示班次，請重新查詢。');
    if(data.session_id)sessionId=data.session_id;
    latest={data,query,sent};
    if(body.message){
      conversation.push({role:'assistant',text:data.result?.status==='ok'&&!data.result.query_mode?`已查到 ${stationLabel(data.result.origin)} → ${stationLabel(data.result.destination)} 的班次，請看上方結果。`:data.answer.zh});
      if(data.result && stationData(data.result.origin) && stationData(data.result.destination)){
        selection={origin:data.result.origin,destination:data.result.destination};
        const kind=data.result.requested_train_type||'';document.querySelectorAll('input[name="train-type"]').forEach(input=>input.checked=input.value===kind);
        $('date').value=data.result.query_time.slice(0,10);$('time').value=data.result.query_time.slice(11,16);latest.query=currentQuery();renderSelection();
      }
    }
  } catch(error){if(sequence===requestSequence)latest={error:true,message:error.name==='AbortError'?'等待回覆逾時，模型可能仍在處理，請稍後重試。':error.message};}
  finally {clearTimeout(timeout);if(sequence===requestSequence){requestController=null;setBusy(false);if(matchMedia('(max-width:920px)').matches){$(body.message&&!latest?.error?'chat-section':'results-heading').scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion:reduce)').matches?'instant':'smooth'});}}}
}
function renderStatus(){
  const status=$('model-status');status.className='model-status';
  if(connectionError){status.textContent='連線中斷';status.classList.add('failed');}
  else if(meta?.engine==='qwen'){
    status.textContent=meta.model_status==='ready'?'Qwen 已連線':meta.model_status==='error'?'模型載入失敗':'Qwen 載入中';
    status.classList.toggle('ready',meta.model_status==='ready');status.classList.toggle('failed',meta.model_status==='error');
  }else if(meta){status.textContent='班表展示模式';status.classList.add('ready');}
  $('coverage').textContent=meta?`班表 ${meta.dates[0].slice(5).replace('-','/')} – ${meta.dates.at(-1).slice(5).replace('-','/')}`:'班表資料載入中';
}
async function connect(poll=false){
  clearTimeout(modelPoll);
  try{
    const response=await fetch('/api/bootstrap',{signal:AbortSignal.timeout(10000)});if(!response.ok)throw new Error('bootstrap');
    meta=await response.json();connectionError=false;
    if(meta.deployment==='huggingface-zerogpu')$('about-dialog').querySelector('p').textContent='使用已訓練的第二輪 Qwen3 4B LoRA，由 Hugging Face ZeroGPU 執行中文查詢；可能需要排隊，並受訪客 GPU 額度限制。';
    if(!poll && !$('date').value){$('date').value=meta.now.slice(0,10);$('time').value=meta.now.slice(11,16);}
    // Cache dates are advertised; an unavailable selection is explained locally.
    renderStatus();renderSelection();setBusy(busy);
    if(meta.engine==='qwen'&&['loading','not_started'].includes(meta.model_status))modelPoll=setTimeout(()=>connect(true),2500);
  }catch{connectionError=true;meta=null;renderStatus();setBusy(false);}
}
for(const key of ['origin','destination']) {
  $(`${key}-picker`).addEventListener('click',()=>{editing=key;renderSelection();});
}
$('swap').addEventListener('click',()=>{selection={origin:selection.destination,destination:selection.origin};formError();renderSelection();renderResult();});
document.querySelectorAll('input[name="train-type"]').forEach(input=>input.addEventListener('change',()=>{formError();renderResult();}));
for(const id of ['date','time'])$(id).addEventListener('change',()=>{formError();renderResult();});
$('now').addEventListener('click',setNow);
$('journey-form').addEventListener('submit',event=>{event.preventDefault();send({route:{...selection,train_type:trainType()}});});
$('chat-form').addEventListener('submit',event=>{event.preventDefault();const message=$('message').value.trim();if(!message||busy)return;$('message').value='';send({message});});
$('message').addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();$('chat-form').requestSubmit();}});
$('reset').addEventListener('click',()=>{sessionId=null;conversation=[];latest=null;$('message').value='';renderResult();renderChat();});
$('about-open').addEventListener('click',()=>$('about-dialog').showModal());
document.querySelector('.dialog-close').addEventListener('click',()=>$('about-dialog').close());
mobileMap.addEventListener('change',renderMap);
renderResult();connect();
});
