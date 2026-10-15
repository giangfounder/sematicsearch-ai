<script>
  export let name = 'search';
  export let size = 20;
  const paths = {
    search:'M21 21l-5-5M17 10a7 7 0 1 1-14 0 7 7 0 0 1 14 0',
    table:'M4 4h16v16H4zM4 10h16M10 4v16M4 15h16',
    code:'m8 6-6 6 6 6m8-12 6 6-6 6m-3-15-2 18',
    key:'M15 8a5 5 0 1 1-3-4M12 8l8-6m-3 3 3 3m-6 0 3 3',
    chart:'M4 20V10m8 10V4m8 16v-7M2 20h20',
    spark:'m12 3 2.4 6.6L21 12l-6.6 2.4L12 21l-2.4-6.6L3 12l6.6-2.4Z',
    clock:'M12 7v5l3 2M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
    settings:'M4 7h16M4 17h16M12 7a3 3 0 1 1-6 0 3 3 0 0 1 6 0M18 17a3 3 0 1 1-6 0 3 3 0 0 1 6 0',
    plus:'M12 5v14M5 12h14',arrow:'M5 12h14m-5-5 5 5-5 5',chevron:'m8 10 4 4 4-4',
    upload:'M12 16V3m-5 5 5-5 5 5M4 16v5h16v-5',refresh:'M20 7v5h-5M4 17v-5h5M6 6a8 8 0 0 1 14 6M4 12a8 8 0 0 0 14 6',
    eye:'M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0',
    close:'m6 6 12 12M6 18 18 6',check:'m5 12 4 4L19 6',logout:'M9 4H4v16h5M9 12h12m-4-4 4 4-4 4',
    user:'M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0M4 21v-3a8 8 0 0 1 16 0v3',copy:'M9 9h12v12H9zM15 9V3H3v12h6',
    trash:'M3 6h18M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7m4-7v7',edit:'m15 4 5 5M4 20l5-1L21 7l-5-5L4 14Z',
    menu:'M4 6h16M4 12h16M4 18h16',info:'M12 11v6m0-10v1M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
  };
</script>
<svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d={paths[name] || paths.search}/></svg>
