(() => {
  const original = window.fetch.bind(window);
  function show() {
    let dialog=document.getElementById('jarvis-screen-dialog');
    if(!dialog){
      dialog=document.createElement('dialog');dialog.id='jarvis-screen-dialog';
      dialog.style.cssText='width:min(820px,90vw);padding:16px;border-radius:12px';
      const close=document.createElement('button');close.textContent='Close screen sharing';
      close.onclick=()=>dialog.close();dialog.append(close);
      const frame=document.createElement('iframe');
      frame.title='Jarvis screen snapshot';frame.allow='display-capture';
      frame.style.cssText='display:block;width:100%;height:70vh;border:0';
      dialog.append(frame);document.body.append(dialog);
      dialog.addEventListener('close',()=>frame.removeAttribute('src'));
    }
    if(!dialog.open){
      dialog.querySelector('iframe').src='/personal/routines?screen=1';
      dialog.showModal();
    }
  }
  window.fetch=function(input,init){
    try{
      const url=new URL(input instanceof Request?input.url:String(input),location.href);
      if(url.origin===location.origin && url.pathname==='/v1/chat/completions' && typeof init?.body==='string'){
        const data=JSON.parse(init.body), msg=data.messages?.at(-1);
        const command=msg?.role==='user' && typeof msg.content==='string' ? msg.content.trim().toLowerCase().replace(/^hey[, ]+jarvis[, ]+/, '').replace(/[.!?]+$/, ''):'';
        if(data.stream && /^(?:please )?(?:what am i looking at|look at my screen(?: and (?:explain|describe)(?: what (?:it is|you see)| it)?)?)$/.test(command)){
          show();
          const chunk=JSON.stringify({choices:[{delta:{content:'Choose the window to share in the screen panel, then review the snapshot and click Ask Jarvis.'},finish_reason:'stop'}]});
          return Promise.resolve(new Response('data: '+chunk+'\n\ndata: [DONE]\n\n',{headers:{'Content-Type':'text/event-stream'}}));
        }
      }
    }catch{}
    return original(input,init);
  };
})();
