<script>
  import {onMount} from 'svelte';
  import Button from './Button.svelte';
  export let title;
  export let message;
  export let phrase = '';
  export let busy = false;
  export let onconfirm;
  export let oncancel;
  export let lang = 'vi';
  let dialog, typed = '';
  onMount(()=>{dialog.showModal();return()=>dialog.close();});
</script>
<dialog bind:this={dialog} class="confirm-dialog" on:cancel|preventDefault={oncancel} aria-labelledby="confirm-title">
  <h2 id="confirm-title">{title}</h2><p class="text-muted my-4">{message}</p>
  {#if phrase}<label class="field"><span>{lang==='en'?'Type to confirm':'Nhập để xác nhận'}: <strong>{phrase}</strong></span><input bind:value={typed} autocomplete="off"/></label>{/if}
  <div class="flex gap-3 justify-end mt-6"><Button disabled={busy} on:click={oncancel}>{lang==='en'?'Cancel':'Huỷ'}</Button><Button variant="danger" {busy} disabled={phrase && typed!==phrase} on:click={onconfirm}>{lang==='en'?'Confirm':'Xác nhận'}</Button></div>
</dialog>
