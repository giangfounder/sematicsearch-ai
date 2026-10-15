import {describe,it,expect,vi,afterEach} from 'vitest';
import {get} from 'svelte/store';
import {createClient,createLoader,createTableCache} from '../lib/api.js';

const defer=()=>{let resolve;const promise=new Promise(r=>resolve=r);return{promise,resolve};};
const response=(body,status=200)=>({ok:status<400,status,text:async()=>JSON.stringify(body)});
const store=()=>{const values=new Map();return{getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,String(v)),removeItem:k=>values.delete(k)};};
function api(fetcher){return createClient({fetcher,local:store(),tab:store()});}
afterEach(()=>vi.useRealTimers());

describe('view lifecycle',()=>{
  it('keeps the newest filter response when responses arrive out of order',async()=>{
    const old=defer(),latest=defer(),loader=createLoader();
    const a=loader.load(()=>old.promise),b=loader.load(()=>latest.promise);
    latest.resolve({query:'new',rows:['new']});await b;old.resolve({query:'old',rows:['old']});
    expect(await a).toBeUndefined();expect(get(loader).data.query).toBe('new');loader.dispose();
  });
  it('cannot publish a response or error after its component is destroyed',async()=>{
    const pending=defer(),loader=createLoader();const values=[];loader.subscribe(x=>values.push(x));
    const task=loader.load(()=>pending.promise);loader.dispose();const count=values.length;pending.resolve(['late']);await task;
    expect(values).toHaveLength(count);expect(get(loader).data).toBeNull();
  });
  it('aborts the previous network signal on a new filter',async()=>{
    const loader=createLoader();let signal;const pending=defer();const first=loader.load(s=>{signal=s;return pending.promise;});
    await loader.load(async()=>['latest']);expect(signal.aborted).toBe(true);pending.resolve(['old']);await first;loader.dispose();
  });
});

describe('session isolation',()=>{
  it('ignores an old 401 after a newer sign-in succeeds',async()=>{
    const old=defer();const client=api(vi.fn(path=>path==='/v1/tables'?old.promise:Promise.resolve(response({token:'new-token',account:{id:2}}))));
    const pending=client.request('/v1/tables').catch(e=>e.name);
    await client.signIn({email:'synthetic@example.test',password:'test',remember:false});old.resolve(response({detail:'expired'},401));
    expect(await pending).toBe('AbortError');expect(get(client.session).status).toBe('ready');expect(get(client.session).account.id).toBe(2);
  });
  it('clears an obsolete session token when switching to remembered login',async()=>{
    const local=store(),tab=store();tab.setItem('ss_token','old');
    const client=createClient({local,tab,fetcher:async()=>response({token:'new',account:{id:1}})});
    await client.signIn({remember:true});expect(tab.getItem('ss_token')).toBeNull();expect(local.getItem('ss_token')).toBe('new');
  });
  it('coalesces email and Google authentication attempts',async()=>{
    const pending=defer(),fetcher=vi.fn(()=>pending.promise),client=api(fetcher);
    const a=client.signIn({remember:false}),b=client.signIn({credential:'synthetic'},true);
    expect(a).toBe(b);expect(fetcher).toHaveBeenCalledTimes(1);pending.resolve(response({token:'synthetic',account:{id:1}}));await a;
  });
  it('clears the visible session immediately even if logout is slow',async()=>{
    const pending=defer(),client=api(path=>path.endsWith('/logout')?pending.promise:Promise.resolve(response({token:'synthetic',account:{id:1}})));
    await client.signIn({remember:false});const out=client.logout();expect(get(client.session).status).toBe('login');pending.resolve(response({ok:true}));await out;
  });
  it('terminates hung reads with an actionable timeout',async()=>{
    vi.useFakeTimers();const client=api((_,{signal})=>new Promise((resolve,reject)=>signal.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')))));
    const pending=client.request('/v1/tables',{timeout:25}).catch(e=>e.message);await vi.advanceTimersByTimeAsync(30);expect(await pending).toContain('quá thời gian');
  });
  it('does not automatically retry writes after a timeout',async()=>{
    vi.useFakeTimers();const fetcher=vi.fn((_,{signal})=>new Promise((resolve,reject)=>signal.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')))));
    const client=api(fetcher),pending=client.request('/v1/tables/test/rows',{method:'PUT',body:{rows:[]},timeout:25}).catch(e=>e.message);
    await vi.advanceTimersByTimeAsync(30);expect(await pending).toContain('kiểm tra kết quả');expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it('prevents duplicate writes for the same operation',async()=>{
    const pending=defer(),client=api(vi.fn()),fn=vi.fn(()=>pending.promise);
    const a=client.mutate('save-row',fn),b=client.mutate('save-row',fn);await Promise.resolve();expect(fn).toHaveBeenCalledTimes(1);pending.resolve('ok');expect(await a).toBe('ok');expect(await b).toBe('ok');
  });
});

describe('table cache',()=>{
  it('preserves the last good catalog on refresh failure and reports the error',async()=>{
    const request=vi.fn().mockResolvedValueOnce([{slug:'existing'}]).mockRejectedValueOnce(Error('offline'));
    const cache=createTableCache({request,onReset:()=>{}});await cache.load();await cache.load(true);
    expect(get(cache).data[0].slug).toBe('existing');expect(get(cache).error).toBe('offline');
  });
  it('shares in-flight loads and reuses a fresh catalog between screens',async()=>{
    const pending=defer(),request=vi.fn(()=>pending.promise),cache=createTableCache({request,onReset:()=>{}});
    const a=cache.load(),b=cache.load();expect(request).toHaveBeenCalledTimes(1);pending.resolve([]);await Promise.all([a,b]);await cache.load();expect(request).toHaveBeenCalledTimes(1);
  });
});
