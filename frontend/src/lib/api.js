import { writable, get } from 'svelte/store';

const abortError = () => new DOMException('Request superseded', 'AbortError');
export const isAbort = (error) => error?.name === 'AbortError';

export function createClient({ fetcher = (...args) => fetch(...args), local = globalThis.localStorage, tab = globalThis.sessionStorage } = {}) {
  const read = (storage, key) => { try { return storage?.getItem(key) || ''; } catch { return ''; } };
  let token = read(local, 'ss_token') || read(tab, 'ss_token');
  let epoch = 0, authTask = null;
  const controllers = new Set(), actions = new Map(), resets = new Set();
  const session = writable({ status: 'loading', account: null, error: '' });
  const connection = writable({ apiKey: read(local, 'apikey'), adminKey: read(local, 'adminkey') });
  function cancelAll() { for (const controller of controllers) controller.abort(); controllers.clear(); epoch++; resets.forEach(fn => fn()); }
  function clearStorage() { try { local?.removeItem('ss_token'); tab?.removeItem('ss_token'); } catch { /* private browsing */ } }
  function accept(result, remember) {
    if (!result?.token || !result.account) throw new Error('Phản hồi đăng nhập không hợp lệ.');
    cancelAll(); clearStorage(); token = result.token;
    try { (remember ? local : tab)?.setItem('ss_token',token); local?.setItem('ss_remember',remember ? '1' : '0'); } catch { /* in-memory session remains usable */ }
    session.set({status:'ready',account:result.account,error:''});
  }
  function expire(message = '') { cancelAll(); clearStorage(); token = ''; session.set({status:'login',account:null,error:message}); }
  async function request(path, { method = 'GET', body, signal, timeout = body instanceof FormData ? 120000 : 15000, auth = true, headers = {} } = {}) {
    const version = epoch, sentToken = token, controller = new AbortController();
    let timedOut = false;
    const abort = () => controller.abort();
    if (signal?.aborted) abort(); else signal?.addEventListener('abort',abort,{once:true});
    const timer = setTimeout(() => { timedOut = true; controller.abort(); },timeout);
    controllers.add(controller);
    const keys = get(connection);
    const h = { ...(!(body instanceof FormData) ? {'Content-Type':'application/json'} : {}),
      ...(auth && sentToken ? {Authorization:`Bearer ${sentToken}`} : {}),
      ...(auth && keys.apiKey ? {'X-API-Key':keys.apiKey} : {}), ...(auth && keys.adminKey ? {'X-Admin-Key':keys.adminKey} : {}), ...headers };
    try {
      const response = await fetcher(path,{method,headers:h,body:body instanceof FormData ? body : body === undefined ? undefined : JSON.stringify(body),signal:controller.signal});
      if (version !== epoch || signal?.aborted) throw abortError();
      const text = await response.text(); let data; try { data = JSON.parse(text); } catch { data = null; }
      if (version !== epoch || signal?.aborted) throw abortError();
      if (!response.ok) {
        if (response.status === 401 && auth && !path.startsWith('/v1/auth/') && sentToken === token) expire('Phiên đã hết hạn. Vui lòng đăng nhập lại.');
        const detail = data?.detail;
        const message = response.status === 401 && path === '/v1/auth/login' ? 'Email hoặc mật khẩu không đúng.' :
          typeof detail === 'string' ? detail : detail?.message ? [detail.message,...(detail.warnings || [])].join(' · ') :
          Array.isArray(detail) ? detail.map(x=>`${x.loc?.at(-1) || ''}: ${x.msg}`).join('; ') : `Máy chủ trả lỗi ${response.status}. Vui lòng thử lại.`;
        const error = new Error(message); error.status = response.status; throw error;
      }
      if (data === null) throw new Error('Máy chủ trả về dữ liệu không hợp lệ. Vui lòng thử lại.');
      return data;
    } catch (error) {
      if (version !== epoch || signal?.aborted) throw abortError();
      if (timedOut) throw new Error(method === 'GET' || path.startsWith('/v1/auth/') ? 'Kết nối quá thời gian chờ. Vui lòng thử lại.' : 'Kết nối quá thời gian chờ. Hãy kiểm tra kết quả trước khi thực hiện lại thao tác lưu/nhập.');
      if (error instanceof TypeError) throw new Error('Không kết nối được máy chủ. Kiểm tra mạng rồi thử lại.');
      throw error;
    } finally { clearTimeout(timer); controllers.delete(controller); signal?.removeEventListener('abort',abort); }
  }
  async function boot() {
    const version = epoch; session.update(s=>({...s,status:'loading',error:''}));
    try { const result = await request('/v1/auth/me',{timeout:12000}); if (version === epoch) session.set({status:'ready',account:result.account,error:''}); }
    catch (error) { if (isAbort(error)) return; if (error.status === 401) expire(); else if (version === epoch) session.set({status:'login',account:null,error:error.message}); }
  }
  function signIn(body, google = false) {
    if (authTask) return authTask;
    authTask = request(google ? '/v1/auth/google' : '/v1/auth/login',{method:'POST',body,auth:false,timeout:20000})
      .then(result=>accept(result,!!body.remember)).finally(()=>{authTask=null;});
    return authTask;
  }
  async function logout() {
    // Clear the visible session immediately; revoke its captured token independently.
    const oldToken = token, keys = get(connection); expire();
    try { local?.setItem('ss_logout',String(Date.now())); } catch { /* storage unavailable */ }
    try { await request('/v1/auth/logout',{method:'POST',auth:false,timeout:5000,headers:{...(oldToken ? {Authorization:`Bearer ${oldToken}`} : {}),...(keys.adminKey ? {'X-Admin-Key':keys.adminKey} : {})}}); } catch { /* local session is already gone */ }
  }
  function mutate(key, fn) {
    const id = `${epoch}:${key}`; if (actions.has(id)) return actions.get(id);
    const task = Promise.resolve().then(fn).finally(()=>{actions.delete(id);}); actions.set(id,task); return task;
  }
  function storageChanged(event) {
    if (event.key === 'ss_logout' || event.key === 'ss_token' && event.newValue !== token && read(local,'ss_remember') === '1') {
      cancelAll(); token = read(local,'ss_token') || read(tab,'ss_token'); session.set({status:'loading',account:null,error:''}); boot();
    }
  }
  return {request,session,connection,boot,signIn,logout,mutate,expire,storageChanged,onReset(fn){resets.add(fn);return()=>resets.delete(fn);},remember:()=>read(local,'ss_remember') !== '0'};
}

export const client = createClient();

// Each view owns this loader: abort superseded reads and ignore late responses even
// when a transport fails to honour AbortSignal. No request can write into another view.
export function createLoader(initial = null) {
  const state = writable({data:initial,loading:false,error:''});
  let generation = 0, controller, disposed = false;
  async function load(fn) {
    if (disposed) return;
    controller?.abort(); controller = new AbortController(); const id = ++generation;
    state.update(s=>({...s,loading:true,error:''}));
    try { const data = await fn(controller.signal); if (!disposed && id === generation) {state.set({data,loading:false,error:''});return data;} }
    catch (error) { if (!disposed && id === generation && !isAbort(error)) state.update(s=>({...s,loading:false,error:error.message})); }
    finally { if (!disposed && id === generation) state.update(s=>({...s,loading:false})); }
  }
  return {subscribe:state.subscribe,load,dispose(){disposed=true;generation++;controller?.abort();},clear(){state.set({data:initial,loading:false,error:''});}};
}

export function createTableCache(api = client) {
  const state = writable({data:null,loading:false,error:''});
  let loadedAt = 0, pending = null, generation = 0;
  api.onReset(()=>{generation++;pending=null;loadedAt=0;state.set({data:null,loading:false,error:''});});
  async function load(force = false) {
    if (!force && get(state).data !== null && Date.now() - loadedAt < 30000) return get(state).data;
    if (pending) return pending;
    const id = generation;
    state.update(s=>({...s,loading:true,error:''}));
    const task = api.request('/v1/tables').then(data=>{if (id === generation) {loadedAt=Date.now();state.set({data,loading:false,error:''});} return data;})
      .catch(error=>{if (id === generation && !isAbort(error)) state.update(s=>({...s,loading:false,error:error.message})); return null;})
      .finally(()=>{if (pending === task) pending=null;});
    pending=task; return task;
  }
  return {subscribe:state.subscribe,load,invalidate(){loadedAt=0;}};
}
export const tables = createTableCache();
export const jobs = writable({});
client.onReset(()=>jobs.set({}));
export function trackJob(slug, id) { if (id) jobs.update(all=>({...all,[slug]:{id,status:'queued',progress:0}})); }
export async function changed(slug, result) { tables.invalidate(); tables.load(true); trackJob(slug,result?.embed_job); }
export const fmt = value => new Intl.NumberFormat('vi-VN').format(value ?? 0);
export const date = value => value ? new Date(value).toLocaleString('vi-VN') : '—';
export const tablePath = slug => `/v1/tables/${encodeURIComponent(slug)}`;
export const demoPath = slug => `/v1/admin/demos/${encodeURIComponent(slug)}`;

