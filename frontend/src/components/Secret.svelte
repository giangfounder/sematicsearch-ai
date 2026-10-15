<script>
  import {onMount} from 'svelte';
  import Icon from './Icon.svelte';
  export let value = '';
  export let label = 'Mật khẩu';
  export let autocomplete = 'current-password';
  export let readonly = false;
  export let required = false;
  export let minlength = undefined;
  export let invalid = false;
  export let describedby = undefined;
  export let lang = 'vi';
  export let inputElement = undefined;
  const inputId = 'secret-'+Math.random().toString(36).slice(2);
  let shown = false;
  onMount(()=>{ const hide=()=>shown=false; document.addEventListener('visibilitychange',hide);window.addEventListener('pagehide',hide);return()=>{document.removeEventListener('visibilitychange',hide);window.removeEventListener('pagehide',hide);}; });
</script>
<div class="field"><label class="text-xs font-semibold" for={inputId}>{label}</label><span class="secret-input">
  <input id={inputId} bind:this={inputElement} type={shown?'text':'password'} bind:value {autocomplete} {readonly} {required} {minlength} aria-invalid={invalid || undefined} aria-describedby={describedby} on:input/>
  <button type="button" class="secret-toggle" aria-label={`${shown?(lang==='en'?'Hide':'Ẩn'):(lang==='en'?'Show':'Hiện')} ${label.toLowerCase()}`} aria-pressed={shown} on:click={()=>shown=!shown}><Icon name="eye" size={19}/></button>
</span></div>
