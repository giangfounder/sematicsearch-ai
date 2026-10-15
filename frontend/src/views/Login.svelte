<script>
  import {onMount,tick} from 'svelte';
  import {client,isAbort} from '../lib/api.js';
  import Button from '../components/Button.svelte';
  import Secret from '../components/Secret.svelte';
  import Icon from '../components/Icon.svelte';
  import Notice from '../components/Notice.svelte';
  export let lang='vi'; export let toggleLang; export let initialError='';
  let email='',password='',remember=client.remember(),busy=false,error='',invalid=false,emailInput,googleBox,googleError='',googleEnabled=false,googleLoading=true,alive=true;
  let googleScript,passwordInput;
  $: t=(vi,en)=>lang==='en'?en:vi;
  async function login(credential=null) {
    if(busy)return; busy=true;error='';initialError='';invalid=false;
    try { await client.signIn(credential ? {credential,remember} : {email:email.trim(),password,remember},!!credential);password=''; }
    catch(e){if(!isAbort(e)&&alive){error=e.message;invalid=!credential && e.status===401;if(!credential){await tick();passwordInput?.focus();passwordInput?.select();}}}
    finally {if(alive)busy=false;}
  }
  async function initGoogle() {
    googleLoading=true;googleError='';
    try {
      const cfg=await client.request('/v1/auth/config',{auth:false,timeout:8000});
      if(!alive)return;googleEnabled=cfg.google_enabled;
      if(!cfg.google_enabled)return;
      if(!window.google?.accounts?.id) await new Promise((resolve,reject)=>{
        const script=document.createElement('script'); googleScript=script;
        script.src='https://accounts.google.com/gsi/client';script.async=true;
        const timer=setTimeout(()=>{script.remove();reject(new Error(t('Chưa tải được đăng nhập Google. Bạn có thể dùng email hoặc thử lại.','Google sign-in could not load. Use email or retry.')));},10000);
        script.onload=()=>{clearTimeout(timer);resolve();};script.onerror=()=>{clearTimeout(timer);script.remove();reject(new Error(t('Không kết nối được Google.','Cannot connect to Google.')));};document.head.append(script);
      });
      if(!alive)return;
      window.google.accounts.id.initialize({client_id:cfg.google_client_id,callback:resp=>{if(alive)login(resp.credential);},auto_select:false});
      googleBox.replaceChildren();window.google.accounts.id.renderButton(googleBox,{theme:'outline',size:'large',width:Math.min(360,googleBox.clientWidth || 320),text:'continue_with',locale:lang==='en'?'en':'vi'});
    }catch(e){if(alive&&!isAbort(e))googleError=e.message;}finally{if(alive)googleLoading=false;}
  }
  onMount(()=>{emailInput.focus();initGoogle();return()=>{alive=false;password='';googleScript?.remove();};});
</script>
<div class="login-page grid min-h-dvh lg:grid-cols-2">
  <aside class="login-story hidden lg:flex flex-col justify-between p-12 xl:p-16">
    <a class="flex items-center gap-3 font-bold text-xl" href="#/"><img src="/logo.png" alt="" width="40" height="40" class="rounded-xl bg-white"/>semsearch</a>
    <div class="max-w-lg py-16">
      <div class="inline-flex items-center gap-2 rounded-full border border-white/20 px-3 py-1.5 text-xs text-white/75 mb-7"><span class="h-1.5 w-1.5 rounded-full bg-emerald-300"></span>{t('Không gian dữ liệu của bạn','Your data workspace')}</div>
      <h1 class="text-[clamp(36px,4vw,54px)] leading-[1.2] tracking-[-2px] text-white">{t('Tìm đúng dữ liệu.','Find the right data.')}<br/><span class="text-[#a8d8bf]">{t('Trong một câu hỏi.','With one question.')}</span></h1>
      <p class="mt-6 text-white/65 max-w-sm leading-7">{t('Từ bảng Excel đến câu trả lời rõ ràng. Quản lý, tìm kiếm và kết nối dữ liệu trong cùng một nơi.','From spreadsheets to clear answers. Manage, search and connect your data in one place.')}</p>
      <div class="mt-12 border-l-2 border-[#88bfa2] pl-5"><p class="text-sm text-white/55 mb-3">{t('Ví dụ tìm kiếm','Try a question')}</p><p class="text-white/95 text-lg">“{t('Tủ lạnh tiết kiệm điện dưới 10 triệu','Energy-efficient refrigerator under 10 million')}”</p><div class="mt-5 flex items-center gap-3 text-[#a8d8bf] text-sm"><Icon name="search" size={17}/>{t('Hiểu ý bạn. Tìm trong dữ liệu của bạn.','Understand your intent. Search your own data.')}</div></div>
    </div>
    <p class="text-xs text-white/40">Semsearch Console</p>
  </aside>
  <main class="flex flex-col min-h-dvh items-center justify-center px-6 py-10 sm:px-12 bg-white">
    <div class="w-full max-w-[360px]">
      <div class="lg:hidden flex items-center gap-3 mb-10 text-xl font-bold"><img src="/logo.png" alt="" width="40" height="40"/>semsearch</div>
      <h1>{t('Đăng nhập','Sign in')}</h1><p class="text-muted mt-3 mb-8">{t('Tiếp tục với không gian làm việc của bạn.','Continue to your workspace.')}</p>
      <form on:submit|preventDefault={()=>login()} aria-busy={busy} class="space-y-5">
        <label class="field"><span>Email</span><input bind:this={emailInput} bind:value={email} type="email" name="email" autocomplete="username" required placeholder="you@company.com" aria-invalid={invalid || undefined} aria-describedby={error?'login-error':undefined} on:input={()=>{error='';initialError='';invalid=false;}}/></label>
        <Secret bind:value={password} bind:inputElement={passwordInput} {lang} label={t('Mật khẩu','Password')} required {invalid} describedby={error?'login-error':undefined} on:input={()=>{error='';initialError='';invalid=false;}}/>
        <label class="flex items-center gap-2.5 text-sm text-muted min-h-11"><input type="checkbox" bind:checked={remember}/>{t('Duy trì đăng nhập trong 30 ngày','Stay signed in for 30 days')}</label>
        <div id="login-error"><Notice error={error || initialError} {lang}/></div>
        <div class="grid"><Button type="submit" variant="primary" {busy}>{busy?t('Đang đăng nhập…','Signing in…'):t('Đăng nhập','Sign in')}<Icon name="arrow" size={18}/></Button></div>
      </form>
      <div class:hidden={!googleLoading && !googleEnabled && !googleError} class="mt-7">
        <div class="flex items-center gap-4 text-xs text-muted mb-6"><span class="h-px flex-1 bg-line"></span>{t('hoặc','or')}<span class="h-px flex-1 bg-line"></span></div>
        <div class="min-h-11 flex justify-center" inert={busy} class:opacity-50={busy} bind:this={googleBox}></div>
        {#if googleLoading}<p class="text-xs text-muted text-center">{t('Đang kết nối Google…','Connecting to Google…')}</p>{/if}
        <Notice error={googleError} retry={initGoogle} {lang}/>
      </div>
      <div class="mt-10 flex justify-between items-center text-xs text-muted"><span>Semsearch Console</span><button class="min-h-11 px-2 underline underline-offset-4" on:click={toggleLang}>{lang==='vi'?'English':'Tiếng Việt'}</button></div>
    </div>
  </main>
</div>
<style>.login-story{color:white;background:#153f33;background-image:radial-gradient(ellipse at 15% 80%,#2b5a46 0,transparent 65%)}.login-story h1{font-weight:600}</style>
