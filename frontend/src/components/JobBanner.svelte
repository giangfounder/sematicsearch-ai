<script>
  import {onMount,onDestroy} from 'svelte';import {get} from 'svelte/store';
  import {client,jobs,trackJob,tables,isAbort} from '../lib/api.js';import Button from './Button.svelte';import Notice from './Notice.svelte';
  export let slug;export let lang='vi';
  let activeId='',timer,controller,alive=true,mounted=false,sequence=0,error='',busy=false;
  $: t=(vi,en)=>lang==='en'?en:vi;
  $: job=$jobs[slug];
  $: names={embed:t('Embedding dữ liệu','Embedding data'),evaluate:t('Đánh giá','Evaluation'),enrich:t('Bổ sung dữ liệu','Enrichment'),calibrate:t('Hiệu chỉnh','Calibration')};
  $: if(mounted && job?.id && job.id!==activeId && job.status!=='done') start(job.id);
  function start(id){clearTimeout(timer);controller?.abort();controller=new AbortController();activeId=id;const seq=++sequence;error='';poll(id,seq,controller.signal);}
  async function poll(id,seq,signal){
    try {const value=await client.request(`/v1/admin/jobs/${encodeURIComponent(id)}`,{signal});if(!alive||seq!==sequence)return;
      jobs.update(all=>({...all,[slug]:value}));
      if(['queued','running'].includes(value.status))timer=setTimeout(()=>poll(id,seq,signal),2500);
      else {tables.invalidate();tables.load(true);}
    }catch(e){if(alive&&seq===sequence&&!isAbort(e))error=e.message;}
  }
  async function discover(){controller?.abort();controller=new AbortController();error='';try{const all=await client.request(`/v1/admin/jobs?demo=${encodeURIComponent(slug)}`,{signal:controller.signal});if(!alive)return;
    const existing=get(jobs)[slug];if(existing?.id){start(existing.id);return;}
    const latest=all.find(x=>['queued','running'].includes(x.status))||all.find(x=>x.kind==='embed'&&['error','cancelled'].includes(x.status));jobs.update(state=>({...state,[slug]:latest||{status:'idle',checkedAt:Date.now()}}));
  }catch(e){if(alive&&!isAbort(e))error=e.message;}}
  async function retry(){if(busy)return;busy=true;error='';try{const result=await client.mutate(`retry:${job.id}`,()=>client.request(`/v1/admin/jobs/${job.id}/retry`,{method:'POST'}));if(alive)trackJob(slug,result.job_id);}catch(e){if(alive&&!isAbort(e))error=e.message;}finally{if(alive)busy=false;}}
  onMount(()=>{const value=get(jobs)[slug];if(value?.id){activeId=value.id;if(value.status!=='done')start(value.id);}else if(!value?.checkedAt || Date.now()-value.checkedAt>30000)discover();mounted=true;});
  onDestroy(()=>{alive=false;sequence++;clearTimeout(timer);controller?.abort();});
</script>
{#if job?.id && job.status!=='done'}
  <section class="job-banner mb-5" class:failed={['error','cancelled'].includes(job.status)} aria-live="polite">
    <div class="flex gap-3 items-center"><span class:spinner={['queued','running'].includes(job.status)}></span><strong>{names[job.kind] || t('Đang xử lý','Processing')}</strong><span class="ml-auto text-xs">{job.status==='queued'?t('Đang chờ','Queued'):`${Math.round(job.progress||0)}%`}</span></div>
    {#if ['queued','running'].includes(job.status)}<progress class="w-full h-1 mt-3" max="100" value={job.progress||0} aria-label={t('Tiến độ xử lý','Job progress')}></progress>{#if job.result?.total_vectors}<p class="text-xs mt-2">{job.result.completed_vectors}/{job.result.total_vectors} vector</p>{/if}
    {:else}<p class="text-xs mt-2 whitespace-pre-wrap break-words">{job.error || job.status}</p>{#if job.kind==='embed'}<div class="mt-3"><Button {busy} on:click={retry}>{t('Tiếp tục vector còn thiếu','Continue remaining vectors')}</Button></div>{/if}{/if}
  </section>
{/if}
<Notice {error} retry={()=>activeId?start(activeId):discover()} {lang}/>
<style>.job-banner{background:#eaf3ed;border:1px solid #d5e5da;padding:16px 20px;border-radius:10px;font-size:13px;color:#2b6548}.job-banner.failed{background:#fff4e4;border-color:#efdcba;color:#80551f}progress{accent-color:#176552}</style>
