import {it,expect,vi,beforeEach} from 'vitest';
import {render,fireEvent,screen,waitFor} from '@testing-library/svelte';
import {loadPuter} from '../lib/puter.js';
import {client} from '../lib/api.js';
import Chat from '../views/Chat.svelte';
vi.mock('../lib/puter.js',async importOriginal=>({...await importOriginal(),loadPuter:vi.fn()}));
const table={slug:'synthetic',name:'Test catalog',data_version:1};
let sdk;
beforeEach(()=>{
  sdk={auth:{isSignedIn:()=>true,signIn:vi.fn(async()=>({}))},ai:{listModels:vi.fn(async()=>[
    {id:'openrouter:google/gemma-4-26b-a4b-it:free',name:'Gemma Free'}]),
    chat:vi.fn(async function*(){yield {type:'text',text:'Synthetic reply'};})}};
  loadPuter.mockResolvedValue(sdk);
});
it('sends one chat request, keeps table sharing off, and renders text safely',async()=>{
  sdk.ai.chat=vi.fn(async function*(){yield {type:'text',text:'<script>unsafe</script>'};});
  const request=vi.spyOn(client,'request');
  render(Chat,{table});await screen.findByText('Gemma Free');
  await fireEvent.input(screen.getByRole('textbox',{name:'Tin nhắn'}),{target:{value:'Hỏi về một ý tưởng'}});
  await fireEvent.click(screen.getByRole('button',{name:'Gửi'}));
  await screen.findByText('<script>unsafe</script>');
  expect(document.querySelector('.conversation script')).toBeNull();
  expect(sdk.ai.chat).toHaveBeenCalledTimes(1);expect(request).not.toHaveBeenCalled();
  expect(screen.getByRole('checkbox',{name:/Dùng dữ liệu bảng/}).checked).toBe(false);
});
it('cancels a running request when leaving the view',async()=>{
  let signal,release;
  sdk.ai.chat=vi.fn(async function*(_messages,options){signal=options.signal;await new Promise(r=>release=r);yield {type:'text',text:'late'};});
  const view=render(Chat,{table});await screen.findByText('Gemma Free');
  await fireEvent.input(screen.getByRole('textbox'),{target:{value:'Question'}});
  await fireEvent.click(screen.getByRole('button',{name:'Gửi'}));
  await waitFor(()=>expect(signal).toBeDefined());view.unmount();
  expect(signal.aborted).toBe(true);release();
});
it('loads bounded table excerpts only after the user enables them',async()=>{
  const request=vi.spyOn(client,'request').mockResolvedValue({rows:[{product_id:1,name:'Synthetic product'}],data_version:1});
  render(Chat,{table});await screen.findByText('Gemma Free');
  await fireEvent.click(screen.getByRole('checkbox',{name:/Dùng dữ liệu bảng/}));
  await fireEvent.input(screen.getByRole('textbox'),{target:{value:'Synthetic product'}});
  await fireEvent.click(screen.getByRole('button',{name:'Gửi'}));await screen.findByText('Synthetic reply');
  expect(request).toHaveBeenCalledTimes(1);expect(request.mock.calls[0][0]).toContain('/chat-context');
  expect(JSON.stringify(sdk.ai.chat.mock.calls[0][0])).toContain('Synthetic product');
});
