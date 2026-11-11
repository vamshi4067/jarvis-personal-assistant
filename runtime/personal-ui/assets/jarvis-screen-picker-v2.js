(() => {
 const fetchOriginal=window.fetch.bind(window);
 const command=/^(?:please )?(?:what am i looking at|(?:look at|look on|check|see) (?:my|the|this) (?:screen|window)(?:[ ,]+(?:and |then )?(?:explain|describe|tell me)\b.*)?)$/i;
 function panel(question){
  let dialog=document.getElementById('jarvis-screen-picker');
  if(!dialog){
   dialog=document.createElement('dialog');dialog.id='jarvis-screen-picker';
   dialog.style.cssText='width:min(650px,90vw);padding:20px;border-radius:12px';
   dialog.innerHTML='<h2>Which screen or window should I look at?</h2><p>Choose a window or screen. Jarvis takes one snapshot, stops sharing, and explains it locally.</p><button type="button" data-share>Choose screen or window</button> <button type="button" data-close>Close</button><p><label>Or upload a screenshot <input type="file" accept="image/*"></label></p><pre role="status" style="white-space:pre-wrap"></pre>';
   document.body.append(dialog);
  }
  const status=dialog.querySelector('pre'), share=dialog.querySelector('[data-share]'), file=dialog.querySelector('input');
  if(dialog.open)return;
  const abort=new AbortController();
  let stream;
  const stop=()=>stream?.getTracks().forEach(t=>t.stop());
  dialog.onclose=()=>{abort.abort();stop();};
  dialog.querySelector('[data-close]').onclick=()=>dialog.close();
  async function analyze(blob){
   if(abort.signal.aborted)return;
   status.textContent='Analyzing the snapshot on your Mac…';
   const body=new FormData();body.append('file',blob,blob.name||'screen.jpg');body.append('question','Summarize what is visible in one or two short sentences. Identify the screen or app and its main purpose or most important detail. Do not list every item or quote text unless essential. If unclear, say so briefly.');
   const res=await fetchOriginal('/v1/personal/vision',{method:'POST',headers:{'X-Jarvis-Personal':'1'},body,signal:abort.signal});
   const data=await res.json();
   if(!res.ok)throw Error(typeof data.detail==='string'?data.detail:'Jarvis could not analyze this snapshot.');
   if(!abort.signal.aborted)status.textContent=data.text||'Jarvis returned no explanation.';
  }
  async function attempt(fn){
   share.disabled=file.disabled=true;
   try{await fn();}catch(e){if(!abort.signal.aborted)status.textContent=e.name==='NotAllowedError'?'Nothing was shared. Choose a window again or upload a screenshot.':e.message;}
   finally{if(!abort.signal.aborted){share.disabled=file.disabled=false;}}
  }
  share.onclick=()=>attempt(async()=>{
   let timer;
   const video=document.createElement('video');video.muted=true;video.playsInline=true;
   try{
    stream=await navigator.mediaDevices.getDisplayMedia({video:{displaySurface:'window'},audio:false});
    if(abort.signal.aborted)return;
    video.srcObject=stream;
    await Promise.race([video.play(),new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('The selected window did not provide a frame.')),5000);})]);
    if(abort.signal.aborted)return;
    if(!video.videoWidth||!video.videoHeight)throw Error('No frame was received.');
    const canvas=document.createElement('canvas'),scale=Math.min(1,1536/Math.max(video.videoWidth,video.videoHeight));
    canvas.width=Math.max(1,Math.round(video.videoWidth*scale));canvas.height=Math.max(1,Math.round(video.videoHeight*scale));
    canvas.getContext('2d').drawImage(video,0,0,canvas.width,canvas.height);
    stop();
    const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/jpeg',.92));
    if(!blob)throw Error('Could not create a snapshot.');
    await analyze(blob);
   }finally{clearTimeout(timer);stop();video.srcObject=null;}
  });
  file.onchange=()=>{const blob=file.files[0];file.value='';if(blob)void attempt(()=>analyze(blob));};
  file.value='';file.disabled=false;
  share.disabled=!navigator.mediaDevices?.getDisplayMedia;
  status.textContent=share.disabled?'This app window cannot share a screen. Upload a screenshot here instead.':'';
  dialog.showModal();
 }
 window.fetch=function(input,init){
  try{
   const url=new URL(input instanceof Request?input.url:String(input),location.href);
   if(url.origin===location.origin && url.pathname.replace(/\/$/,'')==='/v1/chat/completions' && typeof init?.body==='string'){
    const data=JSON.parse(init.body),msg=data.messages?.at(-1);
    const phrase=msg?.role==='user'&&typeof msg.content==='string'?msg.content.trim().replace(/^(?:hey[ ,]+)?jarvis\b[ ,:]*/i,'').replace(/[.!?]+$/,''):'';
    if(data.stream&&command.test(phrase)){
     panel(phrase.slice(0,1000));
     const chunk=JSON.stringify({choices:[{delta:{content:'Which screen or window should I look at? Choose it in the panel and I’ll explain what I see.'},finish_reason:'stop'}]});
     return Promise.resolve(new Response('data: '+chunk+'\n\ndata: [DONE]\n\n',{headers:{'Content-Type':'text/event-stream'}}));
    }
   }
  }catch{}
  return fetchOriginal(input,init);
 };
})();
