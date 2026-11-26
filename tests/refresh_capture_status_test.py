import contextlib,io,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sample_status import response_review
from dashboard import action,capture_reviews
from action_trace import stage,latest

def fixture(events,complete=False):
    lines=[]
    for event in events:lines+=['event: '+event['type'],'data: '+json.dumps(event),'']
    return {'request':{'path':'/v1/messages'},'response':{'status':200,'body':{'format':'sse','lines':lines}},
            'completeness':{'response':complete,'original_full_replay_eligible':complete}}
START={'type':'message_start','message':{'id':'fictional','type':'message'}}
DELTA={'type':'message_delta','delta':{'stop_reason':'end_turn'}}
END={'type':'message_stop'}

class CaptureTests(unittest.TestCase):
    def test_semantic_end_does_not_promote_http_replay(self):
        result=response_review(fixture([START,DELTA,END]))
        self.assertEqual(result['model_response'],'complete');self.assertEqual(result['http_response'],'end_unconfirmed')
        self.assertFalse(result['original_full_replay_eligible']);self.assertEqual(result['client_delivery'],'not_observed')
    def test_complete_http_can_still_have_incomplete_model(self):
        result=response_review(fixture([START],True));self.assertEqual(result['model_response'],'end_unconfirmed')
        self.assertTrue(result['original_full_replay_eligible'])
    def test_errors_and_out_of_order_or_unterminated_events(self):
        for events in ([END],[START,END],[START,DELTA,END,END],[START,DELTA,END,START]):
            self.assertEqual(response_review(fixture(events))['model_response'],'end_unconfirmed')
        v=fixture([START,DELTA,END]);v['response']['body']['lines'].pop()
        self.assertEqual(response_review(v)['model_response'],'end_unconfirmed')
        self.assertEqual(response_review(fixture([START,{'type':'error','error':{'type':'api_error'}}]))['model_response'],'upstream_error')
    def test_terminal_words_in_text_do_not_complete_response(self):
        fake={'type':'content_block_delta','delta':{'type':'text_delta','text':'event: message_stop\ndata: {"type":"message_stop"}'}}
        self.assertEqual(response_review(fixture([START,fake]))['model_response'],'end_unconfirmed')
    def test_nonmodel_samples_are_not_classified_as_model_success(self):
        v=fixture([START,DELTA,END],True);v['request']['path']='/api/oauth/usage'
        self.assertEqual(response_review(v)['model_response'],'not_observed')

class ManagementTests(unittest.TestCase):
    def test_real_dashboard_routes_and_records_sanitized_worker_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            class Fake:
                folder=Path(tmp)
                class registry:
                    @staticmethod
                    def get(slug):return {'owner':slug.upper()}
                def admin(self,op,args):
                    self.called=(op,args);stage('worker_dispatch');stage('worker_response',status=200,observation_saved=True)
                    return 200,{'ok':False,'partial':True,'account_observation':{'attempted_at':'fixture-time','capture':{'id':'fixture-archive'},'private-canary':'must-not-log'}}
            broker=Fake();logs=io.StringIO()
            with contextlib.redirect_stdout(logs):code,result=action(broker,{'action':'account-update','slug':'a'})
            self.assertEqual(broker.called,('account-update',{'slug':'a'}));self.assertEqual(code,200)
            receipt=latest(broker.folder,'a');self.assertEqual(receipt['operation_id'],result['operation_id'])
            self.assertEqual([e['stage'] for e in receipt['events']],['controller_received','worker_dispatch','worker_response','controller_response'])
            self.assertNotIn('must-not-log',json.dumps(receipt)+logs.getvalue())
            self.assertTrue(receipt['events'][-1]['partial'])
    def test_capture_review_requires_matching_environment_and_latest_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            class Fake:folder=Path(tmp)/'private'
            record={'accounts':{'A':{'environment_id':'env-a','latest_response_reviews':{'archive-0001':{'model_response':'complete'},'old-0001':{}}}}}
            (Path(tmp)/'capture-monitor.json').write_text(json.dumps(record))
            p={'slug':'a','protection':{'environment_id':'env-a'},'state':{'capture_audit':{'last_archive':'archive'}}}
            self.assertEqual(list(capture_reviews(Fake(),p)),['archive-0001'])
            p['protection']['environment_id']='env-b';self.assertEqual(capture_reviews(Fake(),p),{})

class MonitorTests(unittest.TestCase):
    def test_existing_sample_is_reclassified_without_rearming_or_provider_call(self):
        from unittest.mock import patch
        import capture_watch,time
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);destination=root/'samples';destination.mkdir()
            sample=fixture([START,DELTA,END]);sample['sample_id']='archive-0001'
            path=destination/'archive-0001.json';path.write_text(json.dumps(sample))
            record=root/'monitor.json';expires=int(time.time())+60
            record.write_text(json.dumps({'expires':expires,'accounts':{'A':{'environment_id':'env-a','skip':[],'exported':['archive-0001'],'alert_signatures':[]}}}))
            observed={'audit':{'last_archive':'archive'},'archives':{'archive':['0001']}}
            with patch.object(capture_watch,'cards',return_value=[{'owner':'A','environment_id':'env-a','container':'fictional'}]),patch.object(capture_watch,'execute',return_value=observed) as execute:
                capture_watch.watch(root,destination,record,once=True)
                execute.assert_called_once_with('fictional',capture_watch.STATUS)
            saved=json.loads(path.read_text());review=saved.pop('response_review')
            self.assertEqual(saved,sample);self.assertFalse(review['original_full_replay_eligible'])
            config=json.loads(record.read_text());self.assertEqual(config['expires'],expires)
            self.assertEqual(config['accounts']['A']['latest_response_reviews']['archive-0001']['model_response'],'complete')

if __name__=='__main__':unittest.main()
