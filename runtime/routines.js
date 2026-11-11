const byId = id => document.getElementById(id);
const base = '/v1/personal/routines';
let routines = {};
async function api(path='', method='GET', body) {
  const res=await fetch(base+path,{method,headers:{'Content-Type':'application/json','X-Jarvis-Routine':'1'},body:body===undefined?undefined:JSON.stringify(body)});
  const data=await res.json();
  if(!res.ok)throw new Error(typeof data.detail==='string'?data.detail:'Check the routine fields and try again.');
  return data;
}
function select(name) {
  byId('saved').value=name;
  byId('phrase').value=name;
  byId('sites').value=(routines[name]?.sites||[]).join('\n');
  byId('reminders').checked=routines[name]?.reminders??true;
  byId('run').disabled=byId('remove').disabled=!name;
}
async function refresh(name='') {
  routines=await api();
  byId('saved').replaceChildren(new Option('New routine',''),...Object.keys(routines).map(n=>new Option(n,n)));
  select(Object.hasOwn(routines,name)?name:'');
}
async function act(fn) {
  if(byId('editor').inert)return;
  byId('editor').inert=true;
  try {await fn();} catch(error){byId('result').textContent=error.message;}
  finally {byId('editor').inert=false;}
}
byId('saved').onchange=()=>select(byId('saved').value);
byId('editor').onsubmit=e=>{e.preventDefault();void act(async()=>{
  const data=await api('','PUT',{phrase:byId('phrase').value,sites:byId('sites').value.split('\n').map(x=>x.trim()).filter(Boolean),reminders:byId('reminders').checked});
  await refresh(data.saved);byId('result').textContent='Saved: '+data.saved;
});};
byId('run').onclick=()=>act(async()=>{
  const name=byId('saved').value;
  byId('result').textContent='Running '+name+'…';
  byId('result').textContent=(await api('/'+encodeURIComponent(name)+'/run','POST')).result;
});
byId('remove').onclick=()=>act(async()=>{
  const name=byId('saved').value;
  if(!confirm('Delete '+name+'?'))return;
  await api('/'+encodeURIComponent(name),'DELETE');await refresh();byId('result').textContent='Deleted: '+name;
});
void act(()=>refresh('start work'));

async function handoffRequest(path='',method='GET',body) {
  const res=await fetch('/v1/personal/handoff'+path,{method,headers:{'Content-Type':'application/json','X-Jarvis-Routine':'1'},body:body===undefined?undefined:JSON.stringify(body)});
  const data=await res.json();
  if(!res.ok)throw new Error(typeof data.detail==='string'?data.detail:'Check the handoff fields and try again.');
  return data;
}
async function handoffAction(fn) {
  if(byId('handoff').inert)return;
  byId('handoff').inert=true;
  try{await fn();}catch(e){byId('work-result').textContent=e.message;}
  finally{byId('handoff').inert=false;}
}
const lines=id=>byId(id).value.split('\n').map(x=>x.trim()).filter(Boolean);
byId('handoff').onsubmit=e=>{e.preventDefault();void handoffAction(async()=>{
  await handoffRequest('','PUT',{sites:lines('work-sites'),files:lines('work-files'),next_step:byId('next-step').value});
  byId('work-result').textContent='Handoff saved.';
});};
byId('restore').onclick=()=>handoffAction(async()=>{
  byId('work-result').textContent='Restoring…';
  byId('work-result').textContent=(await handoffRequest('/restore','POST')).result;
});
void handoffAction(async()=>{
  const data=await handoffRequest();
  byId('work-sites').value=(data.sites||[]).join('\n');
  byId('work-files').value=(data.files||[]).join('\n');
  byId('next-step').value=data.next_step||'';
});

let snapshot, snapshotURL, lookRequest, captureVersion=0;
function previewSnapshot(blob) {
  lookRequest?.abort();
  if(snapshotURL)URL.revokeObjectURL(snapshotURL);
  snapshot=blob;
  const image=byId('look-preview');
  if(blob){snapshotURL=URL.createObjectURL(blob);image.src=snapshotURL;}
  else{snapshotURL=null;image.removeAttribute('src');}
  image.hidden=!blob;
  byId('look-ask').disabled=!blob;
  byId('look-result').textContent='';
}
byId('look-clear').onclick=()=>{captureVersion++;byId('look-file').value='';previewSnapshot(null);};
byId('look-file').onchange=e=>{captureVersion++;previewSnapshot(e.target.files[0]);};
byId('look-capture').onclick=async()=>{
  const version=++captureVersion;
  let stream, timer;
  const video=document.createElement('video');
  byId('look-capture').disabled=true;
  previewSnapshot(null);
  try{
    if(!navigator.mediaDevices?.getDisplayMedia)throw Error('Window capture is unavailable here. Use Chrome or choose a screenshot.');
    stream=await navigator.mediaDevices.getDisplayMedia({video:{displaySurface:'window'},audio:false});
    if(version!==captureVersion)return;
    video.muted=true;video.srcObject=stream;
    await Promise.race([video.play(),new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('The selected window did not provide a frame.')),5000);})]);
    if(!video.videoWidth)throw Error('No frame received.');
    const canvas=document.createElement('canvas');
    const scale=Math.min(1,1536/Math.max(video.videoWidth,video.videoHeight));
    canvas.width=Math.max(1,Math.round(video.videoWidth*scale));canvas.height=Math.max(1,Math.round(video.videoHeight*scale));
    canvas.getContext('2d').drawImage(video,0,0,canvas.width,canvas.height);
    stream.getTracks().forEach(track=>track.stop());
    const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/jpeg',0.92));
    if(!blob)throw Error('Could not create the snapshot.');
    if(version===captureVersion)previewSnapshot(blob);
  }catch(e){if(version===captureVersion)byId('look-result').textContent=e.message;}
  finally{clearTimeout(timer);stream?.getTracks().forEach(track=>track.stop());video.srcObject=null;byId('look-capture').disabled=false;}
};
byId('look-form').onsubmit=async e=>{
  e.preventDefault();
  if(!snapshot)return;
  lookRequest?.abort();
  const request=new AbortController();lookRequest=request;
  const body=new FormData();body.append('file',snapshot,snapshot.name||'snapshot.jpg');body.append('question',byId('look-question').value);
  byId('look-result').textContent='Looking at the snapshot locally…';byId('look-ask').disabled=true;
  try{
    const res=await fetch('/v1/personal/vision',{method:'POST',headers:{'X-Jarvis-Personal':'1'},body,signal:request.signal});
    const data=await res.json();
    if(!res.ok)throw Error(typeof data.detail==='string'?data.detail:'Could not analyze this image.');
    if(lookRequest===request&&!request.signal.aborted)byId('look-result').textContent=data.text||'The local model returned no answer.';
  }catch(e){if(!request.signal.aborted)byId('look-result').textContent=e.message;}
  finally{if(lookRequest===request){lookRequest=null;byId('look-ask').disabled=!snapshot;}}
};

if(new URLSearchParams(location.search).get('screen')==='1') for(const el of document.querySelectorAll('main > :not(#screen-snapshot)')) el.hidden=true;

let teachTimer, teachingBusy=false;
async function teach(action){
 if(teachingBusy)return;
 teachingBusy=true;
 const output=byId('teach-status');
 try{
  const res=await fetch('/v1/personal/teach/'+action,{method:'POST',headers:{'X-Jarvis-Routine':'1'}});
  const data=await res.json();
  if(!res.ok)throw Error(data.detail||'Recorder unavailable.');
  clearTimeout(teachTimer);
  byId('teach-start').disabled=data.active;
  byId('teach-stop').disabled=byId('teach-cancel').disabled=!data.active;
  if(data.active){
   output.textContent='● Recording navigation in Jarvis’s browser: '+data.sites.length+' of 8 pages.';
   teachTimer=setTimeout(()=>void teach('status'),1500);
  }else if(action==='cancel'){output.textContent='Recording discarded.';}
  else if(data.sites.length){
   select('');
   byId('sites').value=data.sites.join('\n');
   byId('reminders').checked=false;
   output.textContent='Review the addresses below. Remove or reorder lines, name the shortcut, then click Save.';
   byId('phrase').focus();
  }else output.textContent='No pages recorded. Start teaching and navigate in Jarvis’s browser.';
 }catch(e){output.textContent=e.message;}
 finally{teachingBusy=false;}
}
byId('teach-start').onclick=()=>void teach('start');
byId('teach-stop').onclick=()=>void teach('stop');
byId('teach-cancel').onclick=()=>void teach('cancel');
