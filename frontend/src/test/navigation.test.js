import {it,expect,vi,beforeEach} from 'vitest';
import {render,fireEvent,screen,waitFor} from '@testing-library/svelte';
import {client,tables} from '../lib/api.js';
import App from '../App.svelte';
const table={slug:'demo',name:'Synthetic table',rows:1,vectors:2,data_version:1,columns:['name'],name_column:'name'};
const response=data=>({ok:true,status:200,text:async()=>JSON.stringify(data)});
beforeEach(()=>{client.expire();localStorage.clear();location.hash='#/t/demo/try';});
it('changes screen immediately without waiting for the catalog API, and restores keyboard focus',async()=>{
  let tableRequests=0;
  vi.stubGlobal('fetch',vi.fn(async path=>{
    if(path==='/v1/auth/me')return response({account:{id:1,is_admin:true,name:'Test'}});
    if(path==='/v1/tables'){tableRequests++;return response([table]);}
    if(path.includes('/jobs?'))return response([]);
    if(path.endsWith('/logs?limit=100&wrong_only=false'))return new Promise(()=>{});
    throw Error('Unexpected request '+path);
  }));
  render(App);await screen.findByRole('button',{name:'Tìm kiếm'});
  await fireEvent.click(screen.getByRole('link',{name:'Nhật ký'}));window.dispatchEvent(new HashChangeEvent('hashchange'));
  await screen.findByText('Đang tải nhật ký…');
  await fireEvent.click(screen.getByRole('link',{name:'Cài đặt'}));window.dispatchEvent(new HashChangeEvent('hashchange'));
  await screen.findByRole('heading',{name:'Thông tin bảng'});
  expect(tableRequests).toBe(1);await waitFor(()=>expect(document.activeElement.id).toBe('content'));
});
it('does not turn a catalog network failure into a new-table screen',async()=>{
  vi.stubGlobal('fetch',vi.fn(async path=>{
    if(path==='/v1/auth/me')return response({account:{id:1,is_admin:true}});
    if(path==='/v1/tables')throw new TypeError('offline');
    throw Error('unexpected');
  }));
  location.hash='#/';render(App);await screen.findByRole('alert');expect(location.hash).toBe('#/');expect(screen.queryByRole('button',{name:'Tạo bảng và embedding'})).toBeNull();
});
