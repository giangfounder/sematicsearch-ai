<script>
  import {onMount,tick} from 'svelte';
  import Icon from './Icon.svelte';

  export let value = undefined;
  export let options = [];
  export let disabled = false;
  export let placeholder = '';
  export let label = undefined;
  export let size = 'md';
  export let variant = 'default';
  export let icon = undefined;
  export let onchange = undefined;

  const id = 'dd-' + Math.random().toString(36).slice(2, 8);
  const menuId = id + '-menu';

  let open = false, hl = -1, btnEl, menuEl, query = '', queryAt = 0;
  let left = 0, top = 0, width = 0, maxH = 320;

  $: list = (options || []).map(o => o !== null && typeof o === 'object'
    ? { value: o.value, label: o.label ?? String(o.value), disabled: !!o.disabled }
    : { value: o, label: String(o), disabled: false });
  $: selectedIndex = list.findIndex(o => o.value === value);
  $: selected = selectedIndex >= 0 ? list[selectedIndex] : null;
  $: display = selected ? selected.label : placeholder;
  $: rootClass = ['dd', size === 'sm' ? 'sm' : '', variant === 'picker' ? 'picker' : '', variant === 'inline' ? 'inline' : '', open ? 'open' : ''].filter(Boolean).join(' ');
  $: if (open && (disabled || !list.length)) close();
  $: if (open) tick().then(scrollToHighlight);

  function enabledStep(from, dir) {
    for (let i = from; i >= 0 && i < list.length; i += dir) if (!list[i].disabled) return i;
    return -1;
  }

  function toggle() { open ? close() : show(); }

  async function show() {
    if (disabled || !list.length) return;
    if (!open) {
      open = true;
      hl = selectedIndex >= 0 && !list[selectedIndex].disabled ? selectedIndex : enabledStep(0, 1);
      query = ''; queryAt = 0;
    }
    await tick();
    measure();
    btnEl?.focus({ preventScroll: true });
  }

  function close() { open = false; hl = -1; }

  function measure() {
    if (!open || !btnEl || !menuEl) return;
    const r = btnEl.getBoundingClientRect(), vp = window.visualViewport;
    const ox = vp ? vp.offsetLeft : 0, oy = vp ? vp.offsetTop : 0;
    const vw = vp ? vp.width : window.innerWidth, vh = vp ? vp.height : window.innerHeight;
    const gap = 8, below = oy + vh - gap - (r.bottom + 6), above = (r.top - 6) - (oy + gap);
    width = Math.min(Math.max(170, r.width), Math.min(420, vw - gap * 2));
    left = Math.min(Math.max(ox + gap, r.left), ox + vw - gap - width);
    maxH = Math.min(320, Math.max(120, above > below ? above : below));
    tick().then(() => {
      const h = menuEl ? menuEl.offsetHeight : 0;
      const up = h > below && above > below;
      top = up ? Math.max(oy + gap, r.top - 6 - h) : Math.min(oy + vh - gap - h, r.bottom + 6);
    });
  }

  function scrollToHighlight() {
    if (!menuEl || hl < 0) return;
    const el = menuEl.querySelector('.dd-opt.hl');
    if (!el) return;
    if (el.offsetTop < menuEl.scrollTop) menuEl.scrollTop = el.offsetTop;
    else if (el.offsetTop + el.offsetHeight > menuEl.scrollTop + menuEl.clientHeight) menuEl.scrollTop = el.offsetTop + el.offsetHeight - menuEl.clientHeight;
  }

  function choose(i) {
    const opt = list[i];
    if (!opt || opt.disabled) return;
    const changed = opt.value !== value;
    close();
    if (changed) { value = opt.value; onchange?.(opt.value); }
    btnEl?.focus({ preventScroll: true });
  }

  function move(key) {
    if (!list.length) return;
    let i;
    if (key === 'Home') i = enabledStep(0, 1);
    else if (key === 'End') i = enabledStep(list.length - 1, -1);
    else if (key === 'ArrowDown') i = hl < 0 ? enabledStep(0, 1) : enabledStep(hl + 1, 1);
    else i = hl < 0 ? enabledStep(list.length - 1, -1) : enabledStep(hl - 1, -1);
    if (i >= 0) hl = i;
  }

  const normalize = s => s.toLocaleLowerCase().normalize('NFD').replace(/\p{Diacritic}/gu, '').replace(/đ/g, 'd');

  function typeahead(key) {
    const now = performance.now();
    query = now - queryAt > 700 ? key : query + key;
    queryAt = now;
    const chars = [...normalize(query)];
    const q = chars.every(c => c === chars[0]) ? chars[0] : chars.join('');
    if (!q || !list.length) return;
    const start = hl >= 0 ? (q.length === 1 ? hl + 1 : hl) : 0;
    for (let step = 0; step < list.length; step++) {
      const i = (start + step) % list.length;
      if (!list[i].disabled && normalize(list[i].label.trim()).startsWith(q)) { hl = i; return; }
    }
  }

  function onKeydown(e) {
    if (disabled) return;
    if (!open) {
      if (['ArrowDown', 'ArrowUp', 'Home', 'End', 'Enter', ' '].includes(e.key)) {
        e.preventDefault();
        show().then(() => { if (e.key === 'Home' || e.key === 'End') move(e.key); });
      } else if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
        e.preventDefault();
        show().then(() => typeahead(e.key));
      }
      return;
    }
    if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)) { e.preventDefault(); move(e.key); }
    else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); if (hl >= 0) choose(hl); }
    else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); btnEl?.focus({ preventScroll: true }); }
    else if (e.key === 'Tab') close();
    else if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) { e.preventDefault(); typeahead(e.key); }
  }

  const outside = e => { if (open && !e.composedPath().includes(menuEl) && !e.composedPath().includes(btnEl)) close(); };
  const focusOut = e => { if (open && !btnEl?.contains(e.target) && !menuEl?.contains(e.target)) close(); };
  const onScroll = e => { if (open && !(menuEl && menuEl.contains(e.target))) close(); };
  const onResize = () => { if (open) measure(); };

  onMount(() => {
    document.addEventListener('pointerdown', outside);
    document.addEventListener('focusin', focusOut);
    document.addEventListener('scroll', onScroll, true);
    window.addEventListener('resize', onResize);
    window.addEventListener('scroll', onScroll, true);
    window.addEventListener('hashchange', close);
    window.visualViewport?.addEventListener('resize', onResize);
    window.visualViewport?.addEventListener('scroll', onResize);
    return () => {
      document.removeEventListener('pointerdown', outside);
      document.removeEventListener('focusin', focusOut);
      document.removeEventListener('scroll', onScroll, true);
      window.removeEventListener('resize', onResize);
      window.removeEventListener('scroll', onScroll, true);
      window.removeEventListener('hashchange', close);
      window.visualViewport?.removeEventListener('resize', onResize);
      window.visualViewport?.removeEventListener('scroll', onResize);
    };
  });
</script>

<div class={rootClass}>
  <button type="button" class="dd-btn" bind:this={btnEl} {disabled}
    role="combobox" aria-haspopup="listbox" aria-expanded={open} aria-controls={menuId} aria-label={label}
    aria-activedescendant={open && hl >= 0 ? `${id}-option-${hl}` : undefined}
    on:click={toggle} on:keydown={onKeydown}>
    {#if icon}<span class="dd-ico"><Icon name={icon} size={17}/></span>{/if}
    <span class="dd-val" class:dd-placeholder={!selected}>{display}</span>
    <span class="caret"><Icon name="chevron" size={16}/></span>
  </button>
  {#if open}
    <div class="dd-menu" id={menuId} bind:this={menuEl} role="listbox" aria-label={label} style="left:{left}px;top:{top}px;width:{width}px;max-height:{maxH}px">
      {#each list as opt, i (i)}
        <button type="button" class="dd-opt" class:hl={hl === i} id={`${id}-option-${i}`} role="option"
          aria-selected={opt.value === value} disabled={opt.disabled}
          on:click={() => choose(i)} on:mouseenter={() => { if (!opt.disabled) hl = i; }}>
          <span>{opt.label}</span>
          <span class="ck" aria-hidden="true"><Icon name="check" size={16}/></span>
        </button>
      {/each}
    </div>
  {/if}
</div>
