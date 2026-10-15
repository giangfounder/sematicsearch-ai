<script>
  import {onMount,onDestroy} from 'svelte';
  import {client,createLoader,tablePath,demoPath,changed,isAbort,fmt} from '../lib/api.js';
  import {draft,saveDraft} from '../lib/drafts.js';
  import Button from '../components/Button.svelte';import Icon from '../components/Icon.svelte';import Notice from '../components/Notice.svelte';import Confirm from '../components/Confirm.svelte';import Select from '../components/Select.svelte';
  export let table;export let lang='vi';
  const resource=createLoader(),key=`rows:${table.slug}`,saved=draft(key,{query:'',offset:0,editing:null});
  let query=saved.query,offset=saved.offset,editing=saved.editing,expanded={},busy='',error='',success='',confirm=null,fileInput,importMode='upsert',timer,alive=true;
  $: t=(vi,en)=>lang==='en'?en:vi;
  $: data=$resource.data;
  $: columns=table.columns?.length?table.columns:[...new Set((data?.rows||[]).flatMap(x=>Object.keys(x.row)))];
  $: nameCol=table.name_column || (columns.includes('name')?'name':columns[0]);
  $: displayCols=[nameCol,...columns.filter(x=>x!==nameCol)].filter(Boolean);
  function load(){clearTimeout(timer);const q=query,off=offset;return resource.load(async signal=>{
    let result=await client.request(`${tablePath(table.slug)}/rows?offset=${off}&limit=50&q=${encodeURIComponent(q)}`,{signal});
    let actual=off;
    if(off>0&&!result.rows.length&&result.total>0){actual=Math.floor((result.total-1)/50)*50;result=await client.request(`${tablePath(table.slug)}/rows?offset=${actual}&limit=50&q=${encodeURIComponent(q)}`,{signal});}
    return {...result,offset:actual,query:q};
  });}
  function filter(){offset=0;load();}
  function schedule(){clearTimeout(timer);timer=setTimeout(filter,250);}
  function edit(row){editing={key:row?.row_key || null,values:Object.fromEntries(columns.map(c=>[c,row?.row[c] ?? '']))};error='';}
  async function run(action,fn){if(busy)return;busy=action;error='';success='';try{await client.mutate(`${table.slug}:${action}`,fn);}catch(e){if(!isAbort(e)&&alive)error=e.message;}finally{if(alive)busy='';}}
  function value(v){if(typeof v!=='string')return v;const s=v.trim();return s===''?null:/^-?\d+([.,]\d+)?$/.test(s)&&!/^0\d/.test(s)?Number(s.replace(',','.')):s;}
  function save(){const row=Object.fromEntries(Object.entries(editing.values).map(([k,v])=>[k,value(v)]));run('save',async()=>{const result=await client.request(`${tablePath(table.slug)}/rows`,{method:'PUT',body:{rows:[row]}});changed(table.slug,result);if(alive){editing=null;success=t('Đã lưu dòng dữ liệu.','Row saved.');load();}});}
  function remove(row){confirm={title:t('Xoá dòng dữ liệu','Delete row'),message:`${t('Xoá dòng','Delete row')} ${row.row_key}?`,fn:()=>run('delete',async()=>{await client.request(`${tablePath(table.slug)}/rows`,{method:'DELETE',body:{keys:[row.row_key]}});changed(table.slug);if(alive){confirm=null;load();}})};}
  function chooseFile(e){const file=e.currentTarget.files?.[0];if(!file)return;if(file.size>20*1024*1024){error=t('File vượt quá giới hạn 20 MB.','The file exceeds 20 MB.');e.currentTarget.value='';return;}if(importMode==='replace')confirm={title:t('Thay thế dữ liệu','Replace data'),message:t('Dữ liệu trong file sẽ thay thế các dòng hiện có trong bảng.','The file will replace existing rows in this table.'),phrase:table.slug,fn:()=>importFile(file)};else importFile(file);}
  function importFile(file){confirm=null;run('import',async()=>{const form=new FormData();form.append('file',file);form.append('mode',importMode);form.append('dry_run','false');const result=await client.request(`${demoPath(table.slug)}/import`,{method:'POST',body:form});changed(table.slug,result);if(alive){offset=0;success=t(`Đã nhập ${result.products} dòng. Embedding được xử lý ở nền.`,`Imported ${result.products} rows. Embeddings run in the background.`);load();}}).finally(()=>{if(fileInput)fileInput.value='';});}
  onMount(load);onDestroy(()=>{alive=false;resource.dispose();clearTimeout(timer);saveDraft(key,{query,offset:data?.offset??offset,editing});});
</script>
<section class="panel">
  <div class="flex flex-wrap items-end gap-3 mb-5">
    <form class="flex flex-1 min-w-52 gap-2 max-w-md" on:submit|preventDefault={filter}><label class="sr-only" for="row-query">{t('Tìm trong dữ liệu','Filter data')}</label><input id="row-query" type="search" placeholder={t('Tìm trong dữ liệu…','Filter data…')} bind:value={query} on:input={schedule}/><Button type="submit" busy={$resource.loading}><Icon name="search" size={17}/>{t('Lọc','Filter')}</Button></form>
    <div class="flex flex-wrap gap-2 sm:ml-auto"><Button on:click={()=>edit(null)} disabled={!!busy}><Icon name="plus" size={17}/>{t('Thêm dòng','Add row')}</Button><label class="btn" class:opacity-50={!!busy}><Icon name="upload" size={17}/>{busy==='import'?t('Đang nhập…','Importing…'):t('Nhập file','Import file')}<input class="sr-only" bind:this={fileInput} type="file" accept=".xlsx,.xls,.csv,.json,.jsonl" disabled={!!busy} on:change={chooseFile}/></label><Select variant="inline" size="sm" bind:value={importMode} disabled={!!busy} label={t('Cách nhập','Import mode')} options={[{value:'upsert',label:t('Thêm / cập nhật','Add / update')},{value:'replace',label:t('Thay thế','Replace')}]}/></div>
  </div>
  <Notice {error} {success} {lang}/><Notice error={$resource.error} retry={load} {lang}/>
  {#if editing}
    <form class="rounded-xl border border-brand/20 bg-canvas p-5 mb-5" on:submit|preventDefault={save}>
      <div class="flex justify-between items-center mb-5"><h2>{editing.key?t('Sửa dòng','Edit row'):t('Thêm dòng','Add row')}{#if editing.key}<span class="text-muted text-sm ml-2">{editing.key}</span>{/if}</h2><Button label={t('Đóng trình sửa','Close editor')} variant="ghost" on:click={()=>editing=null}><Icon name="close"/></Button></div>
      <div class="grid sm:grid-cols-2 xl:grid-cols-3 gap-4">{#each columns as col}<label class="field"><span>{col}</span><input bind:value={editing.values[col]}/></label>{/each}</div>
      <div class="flex gap-3 mt-5"><Button type="submit" variant="primary" busy={busy==='save'}>{t('Lưu dòng','Save row')}</Button><Button disabled={!!busy} on:click={()=>editing=null}>{t('Huỷ','Cancel')}</Button></div>
    </form>
  {/if}
  <div aria-busy={$resource.loading}>
    {#if $resource.loading&&!data}<div class="min-h-72 flex items-center justify-center gap-3 text-muted" role="status"><span class="spinner"></span>{t('Đang tải dữ liệu…','Loading data…')}</div>
    {:else if data?.rows.length}
      <div class="flex justify-between text-xs text-muted mb-3"><span>{fmt(data.total)} {t('dòng','rows')} · {data.offset+1}–{data.offset+data.rows.length}</span>{#if $resource.loading}<span role="status">{t('Đang cập nhật…','Updating…')}</span>{:else}<span>{t('Bấm vào ô để xem đầy đủ','Click a cell to expand')}</span>{/if}</div>
      <div class="table-scroll" class:opacity-50={$resource.loading} inert={$resource.loading}><table class="data-table"><thead><tr><th>{t('Mã dòng','Row key')}</th>{#each displayCols as col}<th>{col}</th>{/each}<th>{t('Thao tác','Actions')}</th></tr></thead><tbody>{#each data.rows as row (row.id)}<tr><td class="font-semibold whitespace-nowrap">{row.row_key}</td>{#each displayCols as col}<td><button class="cell-value" class:expanded={expanded[`${row.id}:${col}`]} title={String(row.row[col]??'')} on:click={()=>expanded={...expanded,[`${row.id}:${col}`]:!expanded[`${row.id}:${col}`]}}>{row.row[col]===null||row.row[col]===undefined||row.row[col]===''?'—':String(row.row[col])}</button></td>{/each}<td class="whitespace-nowrap"><div class="flex gap-1"><Button variant="ghost" label={`${t('Sửa dòng','Edit row')} ${row.row_key}`} disabled={!!busy} on:click={()=>edit(row)}><Icon name="edit" size={16}/></Button><Button variant="ghost" label={`${t('Xoá dòng','Delete row')} ${row.row_key}`} disabled={!!busy} on:click={()=>remove(row)}><Icon name="trash" size={16}/></Button></div></td></tr>{/each}</tbody></table></div>
      <div class="flex justify-between items-center mt-4"><span class="text-xs text-muted">{t('Trang','Page')} {Math.floor(data.offset/50)+1}</span><div class="flex gap-2"><Button disabled={$resource.loading||data.offset===0} on:click={()=>{offset=Math.max(0,data.offset-50);load();}}>{t('Trang trước','Previous')}</Button><Button disabled={$resource.loading||data.offset+data.rows.length>=data.total} on:click={()=>{offset=data.offset+50;load();}}>{t('Trang sau','Next')}</Button></div></div>
    {:else if !$resource.error}<div class="empty"><Icon name="table" size={28}/><h2 class="mt-4">{t('Chưa có dòng phù hợp','No matching rows')}</h2><p>{query?t('Thử từ khoá khác.','Try another keyword.'):t('Thêm dòng hoặc nhập file để bắt đầu.','Add a row or import a file to get started.')}</p></div>{/if}
  </div>
</section>
{#if confirm}<Confirm {...confirm} {lang} busy={!!busy} onconfirm={confirm.fn} oncancel={()=>{confirm=null;if(fileInput)fileInput.value='';}}/>{/if}
