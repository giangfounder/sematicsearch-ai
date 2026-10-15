import {afterEach,vi} from 'vitest';
import {cleanup} from '@testing-library/svelte';
afterEach(()=>cleanup());
window.scrollTo=vi.fn();
Element.prototype.scrollIntoView=vi.fn();
if(!HTMLDialogElement.prototype.showModal)HTMLDialogElement.prototype.showModal=function(){this.open=true;};
if(!HTMLDialogElement.prototype.close)HTMLDialogElement.prototype.close=function(){this.open=false;};
