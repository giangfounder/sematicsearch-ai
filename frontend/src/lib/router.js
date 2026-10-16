export const tabs = [
  ['try','Tìm kiếm','Search','search'],['chat','Trò chuyện AI','AI chat','chat'],['rows','Dữ liệu','Data','table'],['api','Tích hợp API','API integration','code'],
  ['keys','Khoá API','API keys','key'],['eval','Đánh giá','Evaluation','chart'],['enrich','Bổ sung dữ liệu','Enrichment','spark'],
  ['logs','Nhật ký','Logs','clock'],['settings','Cài đặt','Settings','settings'],
];
export function parseRoute(hash) {
  try {
    const [type,slug,tab] = hash.replace(/^#\/?/,'').split('/').map(decodeURIComponent);
    if (type === 'new' || type === 'accounts') return {type,slug:'',tab:type,key:type};
    if (type === 't' && slug) { const screen = tabs.some(x=>x[0]===tab) ? tab : 'try'; return {type:'table',slug,tab:screen,key:`${slug}/${screen}`}; }
    if (type) return {type:'invalid',slug:'',tab:'',key:'invalid'};
    return {type:'home',slug:'',tab:'',key:'home'};
  } catch { return {type:'invalid',slug:'',tab:'',key:'invalid'}; }
}
export const href = (slug,tab='try') => `#/t/${encodeURIComponent(slug)}/${tab}`;
