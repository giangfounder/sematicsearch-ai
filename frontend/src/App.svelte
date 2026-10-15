<script>
  import {onMount,tick} from 'svelte';
  import {client,tables,fmt} from './lib/api.js';
  import {parseRoute,tabs,href} from './lib/router.js';
  import Login from './views/Login.svelte';
  import Search from './views/Search.svelte';
  import Rows from './views/Rows.svelte';
  import Api from './views/Api.svelte';
  import Keys from './views/Keys.svelte';
  import Evaluation from './views/Evaluation.svelte';
  import Enrichment from './views/Enrichment.svelte';
  import Logs from './views/Logs.svelte';
  import Settings from './views/Settings.svelte';
  import NewTable from './views/NewTable.svelte';
  import Accounts from './views/Accounts.svelte';
  import Icon from './components/Icon.svelte';
  import Button from './components/Button.svelte';
  import Notice from './components/Notice.svelte';
  import Secret from './components/Secret.svelte';
  import JobBanner from './components/JobBanner.svelte';
  const session=client.session;
  let route=parseRoute(location.hash),lang='vi',main,accountMenu,connectionMenu,apiKey='',adminKey='',connectionError='',statusText='';
  try {lang=localStorage.getItem('ss_lang')==='en'?'en':'vi';}catch{}
  $: t=(vi,en)=>lang==='en'?en:vi;
  $: selected=$tables.data?.find(x=>x.slug===route.slug);
  $: title=route.type==='new'?t('Tạo bảng mới','Create table'):route.type==='accounts'?t('Quản lý tài khoản','Accounts'):tabs.find(x=>x[0]===route.tab)?.[lang==='vi'?1:2] || t('Không gian làm việc','Workspace');
  $: if($session.status==='ready') tables.load();
  $: if($session.status==='ready') focusMain();
  $: if($session.status==='ready' && route.type==='home' && $tables.data!==null && !$tables.error) {
    location.replace($tables.data.length?href($tables.data[0].slug):'#/new');
  }
  $: document.documentElement.lang=lang;
  function toggleLang(){lang=lang==='vi'?'en':'vi';try{localStorage.setItem('ss_lang',lang);}catch{}}
  async function focusMain(){await tick();main?.focus({preventScroll:true});statusText=title;const active=document.querySelector('.sidebar nav a[aria-current="page"]');if(active&&window.innerWidth<=760)active.scrollIntoView({block:'nearest',inline:'center'});}
  function navigate(){route=parseRoute(location.hash);if(accountMenu)accountMenu.open=false;if(connectionMenu)connectionMenu.open=false;focusMain();window.scrollTo({top:0,behavior:'instant'});}
  async function connect(){connectionError='';client.connection.set({apiKey,adminKey});if(connectionMenu)connectionMenu.open=false;await client.boot();}
  onMount(()=>{
    const unsub=client.connection.subscribe(v=>{apiKey=v.apiKey;adminKey=v.adminKey;});
    window.addEventListener('hashchange',navigate);window.addEventListener('storage',client.storageChanged);
    const hide=()=>{if(document.hidden){if(accountMenu)accountMenu.open=false;if(connectionMenu)connectionMenu.open=false;}};
    document.addEventListener('visibilitychange',hide);client.boot();
    return()=>{unsub();window.removeEventListener('hashchange',navigate);window.removeEventListener('storage',client.storageChanged);document.removeEventListener('visibilitychange',hide);};
  });
</script>
<svelte:head><title>{title} · Semsearch</title></svelte:head>
{#if $session.status==='loading'}
  <div class="min-h-dvh flex flex-col gap-5 items-center justify-center" role="status"><img src="/logo.png" alt="" width="48" height="48"/><strong class="text-xl">semsearch</strong><span class="spinner text-brand"></span><p class="text-muted">{t('Đang mở không gian làm việc…','Opening your workspace…')}</p></div>
{:else if $session.status!=='ready'}
  <Login {lang} {toggleLang} initialError={$session.error}/>
{:else}
  <a href="#content" class="skip-link" on:click|preventDefault={focusMain}>{t('Đến nội dung','Skip to content')}</a>
  <div class="app-shell">
    <aside class="sidebar">
      <a href="#/" class="brand"><img src="/logo.png" alt="" width="34" height="34"/><span>semsearch</span></a>
      <p class="workspace-label">{t('Không gian làm việc','Workspace')}</p>
      <nav aria-label={t('Chức năng','Navigation')}>
        {#each tabs as [key,vi,en,icon]}
          <a href={route.slug?href(route.slug,key):'#/'} class:active={route.type==='table'&&route.tab===key} aria-current={route.type==='table'&&route.tab===key?'page':undefined} class:nav-disabled={!route.slug}><Icon name={icon}/><span>{lang==='vi'?vi:en}</span></a>
        {/each}
      </nav>
      <div class="sidebar-bottom"><a href="#/new" class="btn w-full" class:primary={route.type==='new'}><Icon name="plus" size={18}/>{t('Tạo bảng mới','Create table')}</a><p class="text-xs text-muted mt-5 px-1">Semsearch Console</p></div>
    </aside>
    <div class="app-body">
      <header class="app-header">
        <div class="min-w-0 flex-1 max-w-sm">
          <label class="sr-only" for="table-picker">{t('Chuyển bảng dữ liệu','Switch table')}</label>
          <div class="relative"><span class="picker-icon"><Icon name="table" size={17}/></span><select id="table-picker" class="table-picker" value={route.slug} on:change={e=>{location.hash=href(e.currentTarget.value,route.tab==='new'||route.tab==='accounts'?'try':route.tab);}} disabled={!$tables.data?.length}>
            {#if !route.slug}<option value="">{t('Chọn bảng dữ liệu','Select table')}</option>{/if}
            {#each $tables.data || [] as table}<option value={table.slug}>{table.name}</option>{/each}
          </select></div>
        </div>
        <div class="header-actions">
          <details bind:this={connectionMenu} class="relative"><summary class="icon-button" aria-label={t('Kết nối API','API connection')} title={t('Kết nối API','API connection')}><Icon name="key" size={19}/></summary><div class="header-menu w-80"><h2>{t('Khoá kết nối','Connection keys')}</h2><p class="text-muted text-xs my-3">{t('Dùng khi kết nối bằng khoá thay cho tài khoản.','Use keys to connect without an account.')}</p><div class="space-y-3"><Secret bind:value={apiKey} label="API key" autocomplete="off" {lang}/><Secret bind:value={adminKey} label="Admin key" autocomplete="off" {lang}/><Button on:click={connect}>{t('Kết nối','Connect')}</Button></div><Notice error={connectionError}/></div></details>
          <button class="icon-button text-xs font-semibold" on:click={toggleLang} title={t('Đổi ngôn ngữ','Change language')}>{lang==='vi'?'VI':'EN'}</button>
          <details bind:this={accountMenu} class="relative"><summary class="avatar" aria-label={t('Tài khoản','Account')}>{($session.account?.name || $session.account?.email || 'A')[0].toUpperCase()}</summary><div class="header-menu w-72"><b class="block truncate">{$session.account?.name || t('Quản trị hệ thống','System admin')}</b><p class="text-muted text-xs break-all mb-4">{$session.account?.email || ''}</p>{#if $session.account?.is_admin}<a href="#/accounts" class="menu-item"><Icon name="user" size={18}/>{t('Quản lý tài khoản','Manage accounts')}</a>{/if}<a href="#/new" class="menu-item"><Icon name="plus" size={18}/>{t('Tạo bảng mới','Create table')}</a><button class="menu-item w-full" on:click={()=>client.logout()}><Icon name="logout" size={18}/>{t('Đăng xuất','Sign out')}</button></div></details>
        </div>
      </header>
      <main id="content" bind:this={main} tabindex="-1" class="content" aria-label={title}>
        <div class="page-heading"><div><p class="text-muted text-xs mb-2">{selected?.name || t('Không gian làm việc','Workspace')}{#if selected}<span class="ml-2 text-[#8b9d91]">/ {selected.slug}</span>{/if}</p><h1>{title}</h1></div>
          {#if selected}<div class="flex gap-5 sm:gap-6"><div class="metric"><b>{fmt(selected.rows)}</b><span>{t('Dòng dữ liệu','Rows')}</span></div><div class="metric"><b>{fmt(selected.vectors)}</b><span>Vector</span></div><div class="metric"><b>v{selected.data_version}</b><span>{t('Phiên bản','Version')}</span></div></div>{/if}
        </div>
        <Notice error={$tables.error} retry={()=>tables.load(true)} {lang}/>
        {#if route.type==='invalid'}<div class="empty"><h2>{t('Không tìm thấy màn hình','Page not found')}</h2><a class="text-action" href="#/">{t('Về không gian làm việc','Go to workspace')}</a></div>
        {:else if route.type==='new'}<NewTable {lang}/>
        {:else if route.type==='accounts'}{#if $session.account?.is_admin}<Accounts {lang}/>{:else}<Notice error={t('Tài khoản chưa có quyền quản trị.','Administrator access is required.')}/>{/if}
        {:else if $tables.data===null}<div class="panel min-h-64" aria-busy={$tables.loading} role="status">{#if $tables.loading}<div class="flex gap-3 text-muted items-center"><span class="spinner"></span>{t('Đang tải danh sách bảng…','Loading tables…')}</div>{/if}</div>
        {:else if route.type==='table' && !selected}<div class="empty"><h2>{t('Không tìm thấy bảng','Table not found')}</h2><p>{t('Thử tải lại danh sách hoặc chọn bảng khác.','Refresh the list or select another table.')}</p><Button on:click={()=>tables.load(true)}>{t('Tải lại','Reload')}</Button></div>
        {:else if selected}
          {#key route.key}
            <JobBanner slug={selected.slug} {lang}/>
            {#if route.tab==='try'}<Search table={selected} {lang}/>
            {:else if route.tab==='rows'}<Rows table={selected} {lang}/>
            {:else if route.tab==='api'}<Api table={selected} {lang}/>
            {:else if route.tab==='keys'}<Keys table={selected} {lang}/>
            {:else if route.tab==='eval'}<Evaluation table={selected} {lang}/>
            {:else if route.tab==='enrich'}<Enrichment table={selected} {lang}/>
            {:else if route.tab==='logs'}<Logs table={selected} {lang}/>
            {:else if route.tab==='settings'}<Settings table={selected} {lang}/>{/if}
          {/key}
        {/if}
      </main>
    </div>
  </div>
  <div class="sr-only" role="status" aria-live="polite">{statusText}</div>
{/if}
<style>
  .app-shell{min-height:100dvh}.sidebar{position:fixed;inset:0 auto 0 0;width:228px;padding:28px 16px 22px;background:#edf3ef;border-right:1px solid #dfe8e3;display:flex;flex-direction:column;z-index:30}.brand{display:flex;align-items:center;gap:10px;font-size:21px;letter-spacing:-.8px;font-weight:700;padding:0 10px 34px}.workspace-label{font-size:11px;color:#718477;padding:0 12px 14px}nav{display:flex;flex-direction:column;gap:5px}nav a{display:flex;align-items:center;gap:12px;min-height:46px;padding:10px 12px;border-radius:9px;color:#597062;font-size:13px;font-weight:600;transition:background .12s}nav a:hover{background:#e2ece5}nav a.active{background:white;color:#176552;box-shadow:0 1px 3px #142b1510}.nav-disabled{opacity:.45}.sidebar-bottom{margin-top:auto;padding-top:30px}.app-body{margin-left:228px}.app-header{height:78px;padding:0 36px;display:flex;align-items:center;justify-content:space-between;gap:24px;border-bottom:1px solid #dfe8e3;background:white;position:sticky;top:0;z-index:25}.table-picker{padding-left:40px;max-width:340px;font-size:13px;font-weight:600;background:#f8faf8}.picker-icon{position:absolute;left:13px;top:14px;color:#176552;pointer-events:none}.header-actions{display:flex;gap:10px;align-items:center}.icon-button{display:flex;align-items:center;justify-content:center;width:44px;height:44px;border-radius:9px;color:#597062;border:1px solid #e1e9e3;list-style:none;background:white;cursor:pointer}.icon-button::-webkit-details-marker,summary.avatar::-webkit-details-marker{display:none}.avatar{width:36px;height:36px;display:grid;place-items:center;border-radius:50%;background:#dcece2;color:#176552;font-size:13px;font-weight:700;cursor:pointer;list-style:none}.header-menu{position:absolute;right:0;top:calc(100% + 12px);background:white;border:1px solid #dfe8e3;border-radius:12px;padding:18px;box-shadow:0 12px 40px #17392518;max-width:calc(100vw - 32px);max-height:75vh;overflow:auto}.menu-item{display:flex;align-items:center;gap:10px;padding:10px 8px;min-height:44px;border-radius:7px;text-align:left;font-size:13px}.menu-item:hover{background:#f0f5f1}.content{padding:34px 36px 64px;max-width:1600px;margin:auto;outline:none}.page-heading{display:flex;align-items:center;justify-content:space-between;gap:28px;margin-bottom:30px}.skip-link{position:fixed;top:-100px;left:12px;background:white;padding:12px;z-index:100}.skip-link:focus{top:12px}
  @media(max-width:1050px){.sidebar{width:200px;padding-inline:12px}.app-body{margin-left:200px}.app-header{padding-inline:24px}.content{padding:28px 24px}.page-heading{flex-wrap:wrap}}
  @media(max-width:760px){.sidebar{position:static;width:auto;padding:16px 16px 0;border-right:0;border-bottom:1px solid #dfe8e3}.brand{font-size:20px;padding:0 0 14px}.brand img{width:30px;height:30px}.workspace-label,.sidebar-bottom{display:none}nav{flex-direction:row;overflow:auto;padding-bottom:10px;scrollbar-width:thin}nav a{flex:none;font-size:12px;gap:7px;padding:8px 12px;min-height:44px}nav a :global(svg){width:16px}.app-body{margin:0}.app-header{height:68px;padding:10px 16px;gap:12px}.header-actions{gap:7px}.header-actions .icon-button{width:38px}.table-picker{font-size:12px;padding-left:33px;padding-right:6px}.picker-icon{left:10px}.content{padding:26px 16px 48px}.page-heading{gap:22px;margin-bottom:24px}.page-heading>div:last-child{max-width:100%}}
</style>
