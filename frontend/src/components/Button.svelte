<script>
  export let busy = false;
  export let disabled = false;
  export let variant = 'default';
  export let type = 'button';
  export let title = undefined;
  export let label = undefined;
</script>
<button {type} {title} aria-label={label} class:primary={variant==='primary'} class:danger={variant==='danger'} class:ghost={variant==='ghost'} class="btn" disabled={disabled || busy} aria-busy={busy} on:click>
  {#if busy}<span class="spinner" aria-hidden="true"></span>{/if}<slot/>
</button>
