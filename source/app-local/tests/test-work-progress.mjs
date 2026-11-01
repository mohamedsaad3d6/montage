import test from 'node:test';import assert from 'node:assert/strict';import {transcriptionProgress as progress}from '../web/control/work-progress.mjs';
const p={jobs:[{id:'j',options:'{"input_version":2}'}],assets:[{id:'v',duration:600},{id:'a',duration:400}]};const intake={version:2,selection:{voice_mode:'external_cut',video:'v',voice:'a'}};const wf={input_preparation:{job:'j',chunks:[{source:'camera',completed_seconds:600},{source:'master',completed_seconds:100}]}};
test('fraction uses completed media seconds of both actual files, not episode or job completion',()=>{assert.equal(progress(p,wf,intake).percent,70);assert.equal(progress(p,wf,intake).scope,'transcription_only')});
test('changed selection cannot provide a false denominator',()=>assert.equal(progress(p,wf,{...intake,version:3}),null));
test('unmeasured transcription does not fabricate progress',()=>assert.equal(progress(p,{input_preparation:{job:'j',chunks:[]}},intake).percent,0));
