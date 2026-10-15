import {client} from './api.js';
// Keep non-secret drafts in memory only. Never cache account passwords or API keys.
const drafts = new Map();
export function draft(key, initial) { return drafts.has(key) ? structuredClone(drafts.get(key)) : initial; }
export function saveDraft(key, value) { drafts.delete(key);drafts.set(key,structuredClone(value));while(drafts.size>24)drafts.delete(drafts.keys().next().value); }
export function clearDraft(key) { drafts.delete(key); }
client.onReset(()=>drafts.clear());
