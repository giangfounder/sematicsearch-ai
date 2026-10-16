import {it,expect,vi} from 'vitest';
import {selectModel,buildMessages,MAX_PROMPT_CHARS,streamReply,puterError} from '../lib/puter.js';

const freeSmall={id:'openrouter:liquid/lfm-2.5-2.6b:free',max_tokens:8192};
const freeNormal={id:'openrouter:google/gemma-4-26b-a4b-it:free',max_tokens:32768};
const freeDeep={id:'openrouter:google/gemma-4-31b-it:free',max_tokens:32768};
const catalog=[freeSmall,freeNormal,freeDeep,{id:'gemini-2.5-flash-lite',costs_currency:'usd-cents',costs:{tokens:1000000,prompt_tokens:10,completion_tokens:40}},
  {id:'gpt-4o-mini',cost:{currency:'usd-cents',tokens:1000000,input:15,output:60}}];
it('uses free small/general/analysis models without an AI router call',()=>{
  expect(selectModel(catalog,{text:'xin chào'}).model).toBe(freeSmall.id);
  expect(selectModel(catalog,{text:'Thông tin tủ lạnh'}).model).toBe(freeNormal.id);
  const plan=selectModel(catalog,{text:'So sánh hai tủ lạnh'});
  expect(plan.model).toBe(freeDeep.id);expect(plan.maxTokens).toBe(768);
});
it('never chooses a paid model if free catalogue entries disappear',()=>{
  expect(()=>selectModel(catalog.filter(m=>!m.id.endsWith(':free')))).toThrow('No eligible model');
});
it('uses current pricing for the explicitly chosen allowance budget',()=>{
  expect(selectModel(catalog,{budget:'economy'}).model).toBe('gemini-2.5-flash-lite');
});
it('bounds full input and keeps complete recent pairs, excluding partial or failed replies',()=>{
  const history=[];
  for(let i=0;i<20;i++)history.push({role:'user',content:`user${i} `+'x'.repeat(1800)},
    {role:'assistant',content:`answer${i} `+'y'.repeat(1800),complete:true});
  history.push({role:'user',content:'failed question'},{role:'assistant',content:'private incomplete text',complete:false,failed:true});
  const messages=buildMessages({text:'q'.repeat(2000),history,context:{rows:[{name:'z'.repeat(4000)}]}});
  expect(JSON.stringify(messages).length).toBeLessThanOrEqual(MAX_PROMPT_CHARS);
  expect(messages.at(-1).content).toContain('q'.repeat(2000));
  expect(JSON.stringify(messages)).not.toContain('incomplete text');
  expect(messages[1].content).not.toContain('user0 ');
  expect(messages.length).toBeLessThanOrEqual(8);
});
it('makes one streamed call with a strict output ceiling and the cancellation signal',async()=>{
  const controller=new AbortController(),onText=vi.fn();
  const chat=vi.fn(async function*(){yield {type:'reasoning',text:'hidden'};yield {type:'text',text:'Hello'};yield {type:'text',text:' world'};});
  const plan=selectModel(catalog,{});
  const result=await streamReply({puter:{ai:{chat}},messages:[],selection:plan,signal:controller.signal,onText});
  expect(result.text).toBe('Hello world');expect(chat).toHaveBeenCalledTimes(1);
  expect(chat.mock.calls[0][1]).toMatchObject({max_tokens:384,signal:controller.signal,stream:true});
});
it('surfaces quota errors and never retries a stream that already emitted output',async()=>{
  const chat=vi.fn(async function*(){yield {type:'text',text:'partial'};yield {type:'error',code:'insufficient_funds'};});
  const task=streamReply({puter:{ai:{chat}},messages:[],selection:selectModel(catalog),signal:new AbortController().signal,onText:vi.fn()});
  await expect(task).rejects.toMatchObject({code:'insufficient_funds'});
  expect(chat).toHaveBeenCalledTimes(1);
  expect(puterError({code:'insufficient_funds'})).toContain('Hạn mức');
  expect(puterError({message:'secret raw response'})).not.toContain('secret');
});
it('cancels without emitting a late stream chunk',async()=>{
  const controller=new AbortController(),onText=vi.fn();
  const chat=vi.fn(async function*(){controller.abort();yield {type:'text',text:'late'};});
  await expect(streamReply({puter:{ai:{chat}},messages:[],selection:selectModel(catalog),signal:controller.signal,onText})).rejects.toMatchObject({name:'AbortError'});
  expect(onText).not.toHaveBeenCalled();
});
