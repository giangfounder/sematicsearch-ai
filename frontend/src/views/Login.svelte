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
<div class="login-page grid min-h-dvh place-items-center px-5 py-10">
  <main class="login-card w-full max-w-[380px]">
    <div class="flex items-center justify-center gap-3 text-xl"><img src="/logo.png" alt="" width="48" height="48"/><span class="wordmark text-3xl">semsearch</span></div>
    <h1 class="mt-9">{t('Đăng nhập','Sign in')}</h1>
    <form on:submit|preventDefault={()=>login()} aria-busy={busy} class="space-y-5 mt-7">
      <label class="field"><span>Email</span><input bind:this={emailInput} bind:value={email} type="email" name="email" autocomplete="username" required placeholder="you@company.com" aria-invalid={invalid || undefined} aria-describedby={error?'login-error':undefined} on:input={()=>{error='';initialError='';invalid=false;}}/></label>
      <Secret bind:value={password} bind:inputElement={passwordInput} {lang} label={t('Mật khẩu','Password')} required {invalid} describedby={error?'login-error':undefined} on:input={()=>{error='';initialError='';invalid=false;}}/>
      <label class="flex items-center gap-2.5 text-sm text-muted min-h-11"><input type="checkbox" bind:checked={remember}/>{t('Duy trì đăng nhập trong 30 ngày','Stay signed in for 30 days')}</label>
      <div id="login-error"><Notice error={error || initialError} {lang}/></div>
      <div class="grid"><Button type="submit" variant="primary" {busy}>{busy?t('Đang đăng nhập…','Signing in…'):t('Đăng nhập','Sign in')}<Icon name="arrow" size={18}/></Button></div>
    </form>
    <div class:hidden={!googleLoading && !googleEnabled && !googleError} class="mt-6">
      <div class="flex items-center gap-4 text-xs text-muted mb-5"><span class="h-px flex-1 bg-line"></span>{t('hoặc','or')}<span class="h-px flex-1 bg-line"></span></div>
      <div class="relative flex min-h-11 items-center justify-center">
        <div class="w-full flex justify-center" inert={busy} class:opacity-50={busy} bind:this={googleBox}></div>
        {#if googleLoading}<span class="spinner text-brand absolute"></span>{/if}
      </div>
      <Notice error={googleError} retry={initGoogle} {lang}/>
    </div>
    <div class="mt-9 pt-5 border-t border-line flex justify-between items-center text-xs text-muted"><span>Semsearch Console</span><button class="min-h-11 px-2 underline underline-offset-4" on:click={toggleLang}>{lang==='vi'?'English':'Tiếng Việt'}</button></div>
  </main>
</div>
<style>
  .login-page{background:#eef4f0;background-image:radial-gradient(ellipse at 50% -5%,#d7eae0 0,transparent 60%)}
  .login-card{background:#fff;border:1px solid var(--color-line);border-radius:18px;padding:38px 32px 28px;box-shadow:0 20px 55px #162b2312}
  .login-card h1{font-size:24px;letter-spacing:-.6px}
</style>
