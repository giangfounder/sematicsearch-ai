<script>
  import {onMount,onDestroy,tick} from 'svelte';
  import {client} from '../lib/api.js';
  import {loadPuter,selectModel,buildMessages,streamReply,puterError} from '../lib/puter.js';
  import Button from '../components/Button.svelte';
  import Icon from '../components/Icon.svelte';
  import Notice from '../components/Notice.svelte';
  import Select from '../components/Select.svelte';
  export let table;export let lang='vi';
  let sdk,models=[],loading=true,connected=false,connecting=false,error='',query='',budget='free',quality='auto',useTable=false,controls;
  let messages=[],busy=false,phase='',controller,alive=true,input,log,frame,pendingText='',nextId=0;
  let requests=0,cacheHits=0,lastPlan=null,sourceCount=0,historyTrimmed=false;
  const cache=new Map();
  $: t=(vi,en)=>lang==='en'?en:vi;
  $: freeCount=models.filter(m=>m.id?.endsWith(':free')).length;
  $: preview=(()=>{try{return selectModel(models,{budget,text:query,quality});}catch{return null;}})();
  async function prepare() {
    loading=true;error='';
    try {
      const loaded=await loadPuter();
      const available=await loaded.ai.listModels();
      if(alive){sdk=loaded;models=available;connected=!!loaded.auth.isSignedIn();}
    } catch(e){if(alive)error=puterError(e,lang);}
    finally {if(alive)loading=false;}
  }
  // SDK is already loaded before this click: preserve the browser's popup gesture.
  async function connect() {
    if(!sdk||connecting)return;
    connecting=true;error='';
    try {
      await sdk.auth.signIn();
      if(alive){connected=true;await tick();input?.focus();}
    } catch(e){if(alive)error=puterError(e,lang);}
    finally {if(alive)connecting=false;}
  }
  function updateReply(id,content,extra={}) {
    if(!alive)return;
    messages=messages.map(m=>m.id===id?{...m,content,...extra}:m);
  }
  function scrollIfNearBottom() {
    if(log&&log.scrollHeight-log.scrollTop-log.clientHeight<200)log.scrollTop=log.scrollHeight;
  }
  function streamText(id,text) {
    pendingText=text;
    if(!frame)frame=requestAnimationFrame(()=>{frame=null;updateReply(id,pendingText);scrollIfNearBottom();});
  }
  function reset() {
    if(busy)return;
    messages=[];cache.clear();error='';requests=0;cacheHits=0;lastPlan=null;sourceCount=0;historyTrimmed=false;query='';input?.focus();
  }
  function changeSource() {if(!busy){messages=[];cache.clear();error='';sourceCount=0;historyTrimmed=false;}}
  async function send() {
    const text=query.trim();
    if(!text||text.length>2000||busy||!connected||!preview)return;
    const history=messages.slice(-38);
    const plan=selectModel(models,{budget,text,quality});lastPlan=plan;
    const replyId=++nextId;
    messages=[...history,{id:++nextId,role:'user',content:text},{id:replyId,role:'assistant',content:'',complete:false,model:plan.label}];
    query='';busy=true;error='';sourceCount=0;phase=useTable?t('Đang tìm dữ liệu…','Finding context…'):t('Đang kết nối model…','Connecting to model…');
    controller=new AbortController();const signal=controller.signal;
    const timer=setTimeout(()=>controller.abort(new DOMException('Deadline','TimeoutError')),45000);
    let answer='';
    try {
      let context=null;
      if(useTable) {
        context=await client.request(`/v1/tables/${encodeURIComponent(table.slug)}/chat-context`,{
          method:'POST',body:{text,top_k:3},signal,timeout:12000});
        if(!alive||signal.aborted)throw signal.reason;
        sourceCount=context.rows.length;
      }
      const prompt=buildMessages({text,history,context,lang});
      historyTrimmed=history.filter(m=>m.role==='user').length>3;
      const key=JSON.stringify([plan.model,prompt,table.data_version,context?.data_version]);
      let result=cache.get(key);
      if(result)cacheHits++;
      else {
        requests++;phase=t('Đang trả lời…','Writing a reply…');
        result=await streamReply({puter:sdk,messages:prompt,selection:plan,signal,onText:text=>{
          answer=text;if(alive&&!signal.aborted)streamText(replyId,text);
        }});
        if(alive&&!signal.aborted&&!result.truncated){
          if(cache.size>=20)cache.delete(cache.keys().next().value);
          cache.set(key,result);
        }
      }
      if(!alive||signal.aborted)throw signal.reason;
      if(frame){cancelAnimationFrame(frame);frame=null;}
      updateReply(replyId,result.text,{complete:!result.truncated,truncated:result.truncated,
        sources:context?.rows||[],cached:!!cache.get(key)&&answer===''});
    } catch(e) {
      if(frame){cancelAnimationFrame(frame);frame=null;}
      if(alive) {
        const stopped=signal.aborted&&signal.reason?.name!=='TimeoutError';
        error=stopped?'':puterError(signal.aborted?signal.reason:e,lang);
        updateReply(replyId,answer,{failed:true,stopped,complete:false});
      }
    } finally {
      clearTimeout(timer);
      if(alive){busy=false;phase='';controller=null;await tick();input?.focus();}
    }
  }
  function keydown(event) {if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();send();}}
  function stop(){controller?.abort();}
  onMount(prepare);
  onDestroy(()=>{alive=false;controller?.abort();if(frame)cancelAnimationFrame(frame);cache.clear();});
</script>

<section class="chat-workspace">
  <aside class="chat-controls panel" bind:this={controls}>
    <div class="flex gap-3 items-center"><span class="chat-mark"><Icon name="chat" size={21}/></span><div><h2>{t('Trợ lý của bạn','Your assistant')}</h2><p class="text-xs text-muted mt-1">Puter AI</p></div></div>
    <p class="text-sm text-muted leading-relaxed mt-5">{t('Hỏi ngắn, nhận câu trả lời rõ ràng. Chọn thêm dữ liệu bảng khi cần thông tin sản phẩm.','Ask a question and get a clear reply. Add table context when you need product information.')}</p>
    <div class="my-5 border-t border-line"></div>
    <div class="space-y-5">
      <label class="field"><span>{t('Ngân sách','Budget')}</span><Select bind:value={budget} disabled={busy} label={t('Ngân sách AI','AI budget')} options={[{value:'free',label:t('Chỉ model miễn phí','Free models only')},{value:'economy',label:t('Dùng hạn mức · model tiết kiệm','Use allowance · economy models')}]}/></label>
      <label class="field"><span>{t('Cách trả lời','Response style')}</span><Select bind:value={quality} disabled={busy} label={t('Cách trả lời','Response style')} options={[{value:'auto',label:t('Tự động theo câu hỏi','Match the question')},{value:'deep',label:t('So sánh / phân tích kỹ','Compare / detailed analysis')}]}/></label>
      <label class="context-choice"><input type="checkbox" bind:checked={useTable} disabled={busy} on:change={changeSource}/><span><b>{t('Dùng dữ liệu bảng','Use table context')}</b><small>{table.name}</small></span></label>
      {#if useTable}<p class="text-xs text-muted leading-relaxed">{t('Câu hỏi và tối đa 3 trích đoạn sẽ được gửi tới Puter và nhà cung cấp model. Chuyển chế độ sẽ bắt đầu hội thoại mới.','Your question and up to 3 excerpts will be sent to Puter and the model provider. Switching this setting starts a new conversation.')}</p>{/if}
    </div>
    <div class="model-note mt-6"><span class="text-xs text-muted">{t('Model dự kiến','Selected model')}</span><p class="text-xs font-semibold break-words mt-2">{preview?.label||t('Đang kiểm tra danh mục…','Checking availability…')}</p>{#if preview}<p class="text-xs text-muted mt-2">{t('Tối đa','Up to')} {preview.maxTokens} token {t('đầu ra','output')}</p>{/if}</div>
    <p class="text-xs text-muted leading-relaxed mt-5">{t('Puter có hạn mức miễn phí theo tài khoản. Model :free có thể bị giới hạn lượt hoặc thay đổi. Chế độ dùng hạn mức có thể phát sinh chi phí trên tài khoản Puter.','Puter has a free account allowance. :free models have limits and may change. Allowance mode may charge your Puter account.')}</p>
    <a class="text-action text-xs inline-block mt-3" href="https://puter.com/dashboard" target="_blank" rel="noopener noreferrer">{t('Xem hạn mức Puter','View Puter usage')}</a>
    <p class="text-xs text-muted mt-4">{freeCount} {t('model :free trong danh mục','models with :free variants')}</p>
    <div class="mt-5"><Button on:click={prepare} busy={loading} disabled={busy||connecting}>{t('Tải lại model','Refresh models')}</Button></div>
  </aside>
  <div class="chat-main panel">
    <div class="chat-top"><div><strong>{t('Cuộc trò chuyện','Conversation')}</strong><p class="text-xs text-muted mt-1">{t('Ngữ cảnh tối đa 3 lượt gần nhất','Context: up to 3 recent turns')}</p><p class="text-xs text-muted">{t('Hội thoại chỉ giữ khi màn hình này đang mở.','Conversation stays only while this view is open.')}</p></div><div class="flex gap-2"><div class="mobile-options"><Button on:click={()=>controls?.scrollIntoView({block:'start'})}>{t('Tuỳ chọn','Options')}</Button></div><Button on:click={reset} disabled={busy||!messages.length} title={t('Bắt đầu cuộc trò chuyện mới','Start a new conversation')}><Icon name="plus" size={16}/>{t('Mới','New')}</Button></div></div>
    {#if !connected}<div class="connect-note"><div><b>{t('Kết nối tài khoản Puter','Connect your Puter account')}</b><p class="text-xs text-muted mt-2">{t('Đăng nhập riêng với Puter để dùng AI. Khoá API của server không được gửi đi.','Sign in with Puter to use AI. Server API keys stay on the backend.')}</p></div><Button variant="primary" on:click={connect} busy={connecting||loading} disabled={!sdk||!!error}>{t('Kết nối Puter','Connect Puter')}</Button></div>{/if}
    <Notice {error} {lang}/>
    <div class="conversation" bind:this={log} role="log" aria-label={t('Nội dung trò chuyện','Chat messages')} aria-live="polite" aria-relevant="additions" aria-busy={busy}>
      {#if !messages.length}<div class="chat-empty"><Icon name="chat" size={34}/><h2>{t('Bắt đầu từ một câu hỏi','Start with a question')}</h2><p>{t('Tìm ý tưởng, giải thích một khái niệm hoặc bật dữ liệu bảng để hỏi về sản phẩm.','Explore an idea, explain a concept, or enable table context to ask about products.')}</p><div class="chat-samples">{#each [t('Giải thích tìm kiếm ngữ nghĩa thật ngắn gọn','Explain semantic search briefly'),t('So sánh các lựa chọn phù hợp nhu cầu của tôi','Compare the options that fit my needs')] as sample}<button on:click={()=>{query=sample;input?.focus();}} disabled={busy}>{sample}<Icon name="arrow" size={16}/></button>{/each}</div></div>{/if}
      {#each messages as message (message.id)}
        <article class="chat-message" class:from-user={message.role==='user'}>
          <div class="message-label">{message.role==='user'?t('Bạn','You'):'Semsearch'}{#if message.cached}<span>Cache</span>{/if}</div>
          <div class="message-text">{message.content|| (busy?t('Đang chuẩn bị câu trả lời…','Preparing a reply…'):t('Chưa có nội dung trả lời.','No reply was received.'))}</div>
          {#if message.model}<p class="message-model">{message.model}</p>{/if}
          {#if message.stopped}<p class="message-model">{t('Đã dừng. Phần trả lời này không được dùng làm ngữ cảnh tiếp theo.','Stopped. This partial reply is excluded from future context.')}</p>
          {:else if message.truncated}<p class="message-model">{t('Đã đạt giới hạn đầu ra. Hãy hỏi tiếp một phần cụ thể.','Output limit reached. Ask about a specific part to continue.')}</p>
          {:else if message.failed}<p class="message-model">{t('Yêu cầu chưa hoàn tất.','Request incomplete.')}</p>{/if}
          {#if message.sources?.length}<details class="mt-3 text-xs"><summary>{t('Trích đoạn đã gửi','Excerpts sent')} ({message.sources.length})</summary>{#each message.sources as source}<p class="text-muted mt-2">[{source.product_id}] {source.name}</p>{/each}</details>{/if}
        </article>
      {/each}
    </div>
    <form class="chat-composer" on:submit|preventDefault={send}>
      <label class="sr-only" for="chat-question">{t('Tin nhắn','Message')}</label><textarea id="chat-question" bind:this={input} bind:value={query} maxlength="2000" rows="3" on:keydown={keydown} disabled={busy} placeholder={t('Nhập câu hỏi… Enter để gửi, Shift + Enter xuống dòng','Ask a question… Enter to send, Shift + Enter for a new line')}></textarea>
      <div class="composer-actions"><span class="text-xs text-muted">{busy?phase:`${query.length}/2000`}</span>{#if busy}<Button on:click={stop}><Icon name="close" size={16}/>{t('Dừng','Stop')}</Button>{:else}<Button type="submit" variant="primary" disabled={!connected||!preview||!query.trim()||loading}><Icon name="arrow" size={17}/>{t('Gửi','Send')}</Button>{/if}</div>
    </form>
    <footer class="chat-footer"><span>{requests} {t('lượt AI','AI requests')} · {cacheHits} cache{#if lastPlan} · {lastPlan.maxTokens} {t('token đầu ra tối đa','max output tokens')}{/if}{#if sourceCount} · {sourceCount} {t('trích đoạn','excerpts')}{/if}</span><a href="https://developer.puter.com" target="_blank" rel="noopener noreferrer">Powered by Puter</a></footer>
    {#if historyTrimmed}<p class="text-xs text-muted mt-2">{t('Các lượt cũ đã được bỏ khỏi ngữ cảnh để tiết kiệm token.','Older turns were omitted from context to save tokens.')}</p>{/if}
  </div>
</section>
<style>
  .chat-workspace{display:grid;grid-template-columns:280px minmax(0,1fr);gap:24px;align-items:start}.chat-controls{padding:22px}.chat-mark{display:grid;place-items:center;width:40px;height:40px;border-radius:12px;color:#176552;background:#e9f3ed}.context-choice{display:flex;gap:10px;align-items:flex-start;font-size:12px;cursor:pointer;min-height:44px}.context-choice input{margin-top:4px}.context-choice b{display:block;font-weight:600}.context-choice small{display:block;color:#597062;overflow-wrap:anywhere;margin-top:5px}.model-note{border-left:2px solid #88b69c;padding-left:12px}.chat-main{min-width:0;padding:22px;display:flex;flex-direction:column;min-height:640px}.chat-top{display:flex;justify-content:space-between;align-items:center;gap:12px;border-bottom:1px solid #dfe8e3;padding-bottom:18px}.connect-note{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:18px;background:#f1f7f3;border-radius:10px;margin-top:18px;font-size:13px}.conversation{height:min(52vh,600px);min-height:320px;overflow:auto;overscroll-behavior:contain;padding:22px 4px}.chat-empty{display:flex;min-height:300px;flex-direction:column;align-items:flex-start;justify-content:center;max-width:520px;margin:auto;color:#597062}.chat-empty h2{font-size:22px;margin:18px 0 10px;color:#203d2e}.chat-empty>p{font-size:13px;line-height:1.8;max-width:52ch}.chat-samples{display:grid;gap:10px;margin-top:22px;width:100%}.chat-samples button{display:flex;justify-content:space-between;align-items:center;gap:14px;text-align:left;min-height:48px;border:1px solid #dfe8e3;border-radius:9px;padding:12px;font-size:12px}.chat-samples button:hover{background:#f1f7f3}.chat-message{margin-bottom:24px;padding:0 12px 0 0;max-width:75ch;overflow-wrap:anywhere}.from-user{margin-left:auto;background:#eef5f0;padding:14px 18px;border-radius:12px;max-width:85%}.message-label{font-size:11px;font-weight:600;color:#597062;margin-bottom:8px}.message-label span{margin-left:10px}.message-text{font-size:14px;line-height:1.85;white-space:pre-wrap}.message-model{font-size:10px;line-height:1.5;color:#597062;margin-top:10px}.chat-composer{border:1px solid #c7dcd0;border-radius:12px;padding:12px;background:#fbfdfb}.chat-composer textarea{border:0;background:transparent;box-shadow:none;padding:4px;resize:vertical;min-height:80px;width:100%;font-size:16px}.composer-actions{display:flex;justify-content:space-between;gap:10px;align-items:center;margin-top:8px}.chat-footer{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;font-size:10px;color:#597062;margin-top:14px}.chat-footer a{text-decoration:underline;text-underline-offset:3px;min-height:24px}.chat-samples :global(svg){flex:none}
  .mobile-options{display:none}.chat-controls{scroll-margin-top:90px}
  @media(max-width:1150px){.chat-workspace{grid-template-columns:1fr}.mobile-options{display:block}.chat-controls{display:block}.chat-controls .space-y-5{display:grid;grid-template-columns:1fr 1fr;gap:16px}.chat-controls .space-y-5>*{margin:0}.chat-main{min-height:600px;order:-1}.model-note{margin-top:20px}}
  @media(max-width:560px){.chat-main,.chat-controls{padding:16px}.connect-note{align-items:flex-start;flex-direction:column;gap:12px}.chat-controls .space-y-5{grid-template-columns:1fr}.chat-top{align-items:flex-start}.chat-empty h2{font-size:20px}.from-user{max-width:94%}.conversation{height:48vh;min-height:300px}.chat-footer{font-size:11px}}
</style>
