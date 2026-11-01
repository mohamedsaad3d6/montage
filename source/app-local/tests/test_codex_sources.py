import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_lifecycle as fixture
from core import Invalid, dump
from codex_sources import options_for, context
from codex_agent import start, state, tick


class CodexSources(unittest.TestCase):
    def setUp(self):
        self.f = fixture.Lifecycle(); self.f.setUp()
        self.s, self.p = self.f.s, self.f.p

    def tearDown(self):
        self.f.tearDown()

    def finish_job(self, job, result, status='completed'):
        with self.s.connect() as c:
            c.execute('UPDATE jobs SET status=?,result=? WHERE id=?', (status, dump(result), job))

    def test_unknown_billable_sources_and_bad_generation_options_rejected(self):
        for value in ({'query':'Saudi','sources':['magnific']}, {'query':'Saudi','url':'https://example.com'}):
            with self.assertRaises(Invalid): options_for('archive_search', dump(value), self.p)
        for value in ({'seconds':601}, {'seconds':True}, {'seconds':6,'seed':1.5}):
            with self.assertRaises(Invalid): options_for('generate_music', dump(value), self.p)

    def test_collection_requires_saved_result_on_same_project_and_revision(self):
        job = self.s.enqueue(self.f.other['id'], 'archive_search')
        self.finish_job(job, {'results':[{'source':'commons','id':'1'}]})
        options = {'search_job':job,'source':'commons','item_id':'1'}
        with self.assertRaises(Invalid): options_for('archive_collect', dump(options), self.s.project(self.p['id']))
        job = self.s.enqueue(self.p['id'], 'archive_search')
        self.finish_job(job, {'results':[{'source':'commons','id':'1'}]})
        options['search_job'] = job
        self.assertEqual(options_for('archive_collect', dump(options), self.s.project(self.p['id'])), options)
        options['item_id'] = 'not-in-result'
        with self.assertRaises(Invalid): options_for('archive_collect', dump(options), self.s.project(self.p['id']))

    def test_duplicate_failed_source_is_not_retried(self):
        options = {'query':'Saudi','sources':['commons'],'media_type':'visual'}
        job = self.s.enqueue(self.p['id'], 'archive_search', options)
        self.finish_job(job, {}, 'failed')
        with self.assertRaises(Invalid): options_for('archive_search', dump(options), self.s.project(self.p['id']))
        options['sources'] = ['internet_archive']
        self.assertEqual(options_for('archive_search', dump(options), self.s.project(self.p['id'])), options)

    def test_director_requests_source_through_queue_without_changing_timeline(self):
        job = start(self.s, self.p['id'], 'اختبار موسيقى فقط')['new_job']
        decision = {'action':'generate_music','reason':'اختبار أداة الموسيقى','evidence':[], 'next_steps':[], 'ready_for_release':False, 'tool_options_json':dump({'seconds':6,'seed':38})}
        self.finish_job(job, {'decision':decision})
        calls = []; tick(self.s, calls.append)
        self.assertEqual(len(calls), 1)
        queued = next(j for j in self.s.project(self.p['id'])['jobs'] if j['id']==calls[0])
        self.assertEqual(queued['kind'], 'generate_music')
        self.assertEqual(json.loads(queued['options']), {'seconds':6,'seed':38})
        self.assertEqual(self.s.project(self.p['id'])['active'], self.p['active'])
        self.finish_job(calls[0], {}, 'failed')
        calls=[]; tick(self.s, calls.append)
        retry = next(j for j in self.s.project(self.p['id'])['jobs'] if j['id']==calls[0])
        self.assertEqual(retry['kind'],'codex_plan')
        self.assertEqual(json.loads(retry['options'])['goal'],'اختبار موسيقى فقط')

    def test_narration_comes_from_current_revision_and_is_bounded(self):
        job = self.s.enqueue(self.p['id'],'transcribe')
        self.finish_job(job, {'transcript':[{'start_ms':0,'end_ms':1000,'text':'السعودية'}]*601})
        narration = context(self.s.project(self.p['id']))['narration']
        self.assertEqual(narration['job_id'],job)
        self.assertEqual(len(narration['segments']),600)
        self.assertTrue(narration['truncated'])
        p = self.s.save(self.p['id'], self.p['active'], self.p['revision']['timeline'], 'new clock')
        self.assertEqual(context(p)['narration']['segments'],[])

    def test_director_can_search_storyblocks_but_cannot_license_a_random_item(self):
        with patch('storyblocks_connector.available',return_value=True):
            job=start(self.s,self.p['id'],'ابحث عن لقطات مدينة')['new_job']
            self.finish_job(job,{'decision':{'action':'storyblocks_search','reason':'city','ready_for_release':False,'tool_options_json':dump({'query':'city','subject':'city'})}})
            calls=[];tick(self.s,calls.append)
            queued=next(j for j in self.s.project(self.p['id'])['jobs']if j['id']==calls[0]);self.assertEqual(queued['kind'],'storyblocks_search')
            self.assertIn('storyblocks_search',context(self.s.project(self.p['id']))['available_tools'])
        with self.assertRaises(Invalid):options_for('storyblocks_collect',dump({'item_id':123,'consent_license':True}),self.p)

    def test_invalid_goal_rejected_before_queue(self):
        with self.assertRaises(Invalid): start(self.s,self.p['id'], {'not':'text'})
        self.assertEqual(self.s.project(self.p['id'])['jobs'],[])

    def test_continue_does_not_create_competing_workflow(self):
        from workflow import advance, get
        job = start(self.s, self.p['id'], 'تجميع الخامات')['new_job']
        result = advance(self.s, self.p['id'])
        self.assertIsNone(result['new_job'])
        self.assertEqual(get(self.s, self.p['id'])['state'], 'codex_controlled')
        self.assertEqual(len(self.s.project(self.p['id'])['jobs']), 1)
        self.assertEqual(state(self.s, self.p['id'])['job'], job)

    def test_pause_cancels_director_and_continue_resumes_its_goal(self):
        from workflow import pause, advance, get
        job = start(self.s, self.p['id'], 'موسيقى فقط للاختبار')['new_job']
        pause(self.s, self.p['id'])
        self.assertEqual(state(self.s, self.p['id'])['state'], 'paused')
        calls=[]; tick(self.s, calls.append); self.assertEqual(calls, [])
        resumed = advance(self.s, self.p['id'])['new_job']
        self.assertNotEqual(resumed, job)
        self.assertEqual(state(self.s, self.p['id'])['goal'], 'موسيقى فقط للاختبار')
        self.assertEqual(get(self.s, self.p['id'])['state'], 'codex_controlled')

    def test_old_revision_decision_does_not_execute(self):
        from workflow import get
        job = start(self.s, self.p['id'], 'اختبار المصادر')['new_job']
        self.finish_job(job, {'decision':{'action':'generate_music','tool_options_json':'{"seconds":6,"seed":40}'}})
        newer = self.s.save(self.p['id'], self.p['active'], self.p['revision']['timeline'], 'changed')
        calls=[]; tick(self.s, calls.append)
        self.assertEqual(calls, [])
        self.assertEqual(state(self.s, self.p['id'])['state'], 'needs_attention')
        self.assertEqual(get(self.s, self.p['id'])['state'], 'needs_input')
        self.assertEqual(self.s.project(self.p['id'])['active'], newer['active'])

if __name__ == '__main__': unittest.main()
