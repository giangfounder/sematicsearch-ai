<script>
  export let error = '';
  export let success = '';
  export let retry = null;
  export let lang = 'vi';
</script>
{#if error}<div class="notice error" role="alert"><span>{error}</span>{#if retry}<button class="text-action" on:click={retry}>{lang==='en'?'Retry':'Thử lại'}</button>{/if}</div>{/if}
{#if success}<div class="notice success" role="status">{success}</div>{/if}
