<script>
  import {onDestroy} from 'svelte';import {client,demoPath,changed,trackJob,isAbort,tables} from '../lib/api.js';import {draft,saveDraft,clearDraft} from '../lib/drafts.js';import Button from '../components/Button.svelte';import Notice from '../components/Notice.svelte';import Confirm from '../components/Confirm.svelte';
  export let table;export let lang='vi';const key=`settings:${table.slug}`;let name=draft(key,table.name),error='',success='',busy='',confirm=null,alive=true;
  $: t=(vi,en)=>lang==='en'?en:vi;
  async function run(action,fn){if(busy)return;busy=action;error='';success='';try{await client.mutate(`${table.slug}:${action}`,fn);}catch(e){if(alive&&!isAbort(e))error=e.message;}finally{if(alive)busy='';}}
  function rename(){if(!name.trim())return;run('rename',async()=>{await client.request(demoPath(table.slug),{method:'PATCH',body:{name:name.trim()}});changed(table.slug);if(alive){success=t('Đã đổi tên bảng.','Table renamed.');clearDraft(key);}});}
  function embed(){run('embed',async()=>{const result=await client.request(`${demoPath(table.slug)}/embed`,{method:'POST'});trackJob(table.slug,result.job_id);if(alive)success=t('Đã đưa yêu cầu embedding vào hàng đợi.','Embedding queued.');});}
  function drop(){run('drop',async()=>{await client.request(demoPath(table.slug),{method:'DELETE'});await tables.load(true);if(alive)location.hash='#/';});}
  onDestroy(()=>{alive=false;saveDraft(key,name);});
</script>
<Notice {error} {success} {lang}/>
<div class="space-y-5">
  <section class="panel"><h2>{t('Thông tin bảng','Table details')}</h2><form on:submit|preventDefault={rename} class="flex flex-wrap items-end gap-3 mt-5"><label class="field flex-1 max-w-md"><span>{t('Tên bảng','Table name')}</span><input bind:value={name} required maxlength="200"/></label><Button type="submit" variant="primary" busy={busy==='rename'} disabled={!!busy}>{t('Lưu thay đổi','Save changes')}</Button></form><p class="text-xs text-muted mt-4">Slug: <code>{table.slug}</code> · {t('Không thay đổi sau khi tạo bảng.','Cannot be changed after creation.')}</p></section>
  <section class="panel"><h2>{t('Embedding dữ liệu','Data embedding')}</h2><p class="text-muted text-sm my-3">{t('Tạo vector cho dữ liệu mới hoặc tiếp tục phần còn thiếu. Các vector phù hợp đã lưu được tái sử dụng.','Generate vectors for new data or continue missing vectors. Valid checkpoints are reused.')}</p><Button busy={busy==='embed'} disabled={!!busy} on:click={embed}>{t('Tạo / cập nhật embedding','Create / update embeddings')}</Button></section>
  <section class="panel"><h2>{t('Cấu trúc dữ liệu','Data structure')}</h2><p class="text-xs text-muted my-4">{t('Cột tên','Name column')}: <b>{table.name_column || '—'}</b></p><div class="flex flex-wrap gap-2">{#each table.columns as col}<span class="badge">{col}</span>{/each}</div></section>
  <section class="panel border-red-200"><h2 class="text-red-800">{t('Xoá bảng','Delete table')}</h2><p class="text-muted text-sm my-3">{t('Xoá toàn bộ dữ liệu và cấu hình của bảng. Thao tác không thể hoàn tác.','Delete all data and configuration for this table. This cannot be undone.')}</p><Button variant="danger" disabled={!!busy} on:click={()=>confirm=true}>{t('Xoá bảng này','Delete this table')}</Button></section>
</div>
{#if confirm}<Confirm title={t('Xoá bảng','Delete table')} message={`${t('Xoá toàn bộ dữ liệu của','Delete all data for')} ${table.name}?`} phrase={table.slug} busy={busy==='drop'} {lang} onconfirm={drop} oncancel={()=>confirm=null}/>{/if}
