"""Offline export/status regression: no provider URLs or account credentials."""
import ctypes,ctypes.util,json,sys,unittest,tempfile,time
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'image')]
from sample_export import Sanitizer,decode_brotli,BodyDecodeError
from sample_status import capture_summary,response_review

def compress(raw):
    lib=ctypes.CDLL(ctypes.util.find_library('brotlienc'))
    lib.BrotliEncoderCompress.argtypes=[ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_size_t,ctypes.c_void_p,ctypes.POINTER(ctypes.c_size_t),ctypes.c_void_p]
    size=ctypes.c_size_t(len(raw)*2+1024);buf=ctypes.create_string_buffer(size.value)
    assert lib.BrotliEncoderCompress(5,22,0,len(raw),raw,ctypes.byref(size),buf)==1
    return buf.raw[:size.value]

class BrotliTests(unittest.TestCase):
    def test_json_structure_redacted_without_python_brotli(self):
        raw=json.dumps({'account':{'email':'PRIVATE_EMAIL'},'five_hour':{'utilization':15},'access_token':'PRIVATE_TOKEN'}).encode()
        encoded=compress(raw)
        with patch.dict(sys.modules,{'brotli':None}):
            result=Sanitizer().body(encoded,{'Content-Encoding':[' Br ']})
        self.assertEqual(result['format'],'json');self.assertEqual(result['value']['five_hour']['utilization'],15)
        self.assertNotIn('PRIVATE',json.dumps(result));self.assertEqual(decode_brotli(encoded),raw)
    def test_stream_multiple_output_chunks_and_empty(self):
        raw=b'abcd'*70000
        self.assertEqual(decode_brotli(compress(raw)),raw)
        self.assertEqual(decode_brotli(compress(b'')),b'')
    def test_size_bound_exact_limit_and_overflow(self):
        raw=b'x'*1000;encoded=compress(raw)
        self.assertEqual(decode_brotli(encoded,1000),raw)
        with self.assertRaisesRegex(BodyDecodeError,'decoded_body_too_large'):decode_brotli(encoded,999)
    def test_truncated_invalid_and_trailing_are_not_success(self):
        encoded=compress(b'{"text":"PRIVATE"}')
        for raw in (encoded[:-1],b'\xff'*20,encoded+b'junk'):
            result=Sanitizer().body(raw,{'content-encoding':['br']})
            self.assertEqual(result['format'],'encoded_or_binary_redacted');self.assertIn('decode_error',result)
            self.assertNotIn('PRIVATE',json.dumps(result))
    def test_missing_library_explicit_error_no_sensitive_exception(self):
        with patch('ctypes.util.find_library',return_value=None):
            result=Sanitizer().body(b'PRIVATE',{'content-encoding':['br']})
        self.assertEqual(result['decode_error'],'brotli_decoder_unavailable')
        self.assertNotIn('PRIVATE',json.dumps(result))

GOOD={'http_request':'complete','http_response':'complete','original_full_replay_eligible':True}
BAD={'http_request':'complete','http_response':'end_unconfirmed','model_response':'complete','original_full_replay_eligible':False}

class CorrelationTests(unittest.TestCase):
    def test_legacy_issue_does_not_taint_complete_latest(self):
        value=capture_summary({'last_archive':'new','capture_issue':'response_capture_incomplete'},{'new-0001':GOOD},[{'sample_id':'old-0001','codes':['response_capture_incomplete']}],['new-0001'])
        self.assertEqual(value['state'],'complete');self.assertEqual(value['current_issues'],[])
        self.assertEqual(value['historical_issues'][0]['sample_id'],'old-0001')
        self.assertEqual(value['unattributed_legacy_issue'],'response_capture_incomplete')
    def test_latest_partial_not_cleared_by_model_end(self):
        value=capture_summary({'last_archive':'new'},{'new-0001':BAD},[],['new-0001'])
        self.assertEqual(value['state'],'issue');self.assertEqual(value['current_issues'][0]['sample_id'],'new-0001')
    def test_two_usage_exchanges_must_both_be_reviewed(self):
        value=capture_summary({'last_archive':'new'},{'new-0001':GOOD},[],['new-0001','new-0002'])
        self.assertEqual(value['state'],'pending');self.assertEqual(value['pending_sample_ids'],['new-0002'])
    def test_stale_monitor_or_wrong_archive_not_success(self):
        value=capture_summary({'last_archive':'new'},{'old-0001':GOOD},[],['old-0001'])
        self.assertEqual(value['state'],'pending');self.assertEqual(value['current_issues'],[])
    def test_decode_failure_does_not_change_raw_http_completeness(self):
        sample={'completeness':{'request':True,'response':True,'original_full_replay_eligible':True},'request':{'path':'/api/oauth/profile'},'response':{'body':{'decode_error':'brotli_decoder_unavailable'}}}
        review=response_review(sample);self.assertEqual(review['http_response'],'complete')
        value=capture_summary({'last_archive':'new'},{'new-0001':review},[],['new-0001'])
        self.assertEqual(value['state'],'issue');self.assertIn('body_decode_failed',value['current_issues'][0]['codes'])
    def test_old_encoded_export_keeps_explicit_decode_uncertainty(self):
        sample={'completeness':{'request':True,'response':True,'original_full_replay_eligible':True},'request':{'path':'/api/oauth/usage'},'response':{'body':{'format':'encoded_or_binary_redacted'}}}
        review=response_review(sample)
        self.assertEqual(review['http_response'],'complete')
        self.assertEqual(review['decode_errors']['response'],'historical_decode_unconfirmed')

class MonitorMigrationTests(unittest.TestCase):
    def test_old_encoded_fixture_reexported_once_and_alerts_reclassified(self):
        import capture_watch
        from dashboard import capture_issue_status
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);destination=root/'samples';destination.mkdir();record=root/'capture-monitor.json'
            old={'sample_id':'old-0001','request':{'path':'/api/oauth/usage'},'response':{'status':200,'body':{'format':'encoded_or_binary_redacted','value':'redacted_example'}},'completeness':{'request':True,'response':True,'original_full_replay_eligible':True}}
            (destination/'old-0001.json').write_text(json.dumps(old))
            new=dict(old,sample_id='new-0001',body_export_version=2,response={'status':200,'body':{'format':'json','value':{}}})
            (destination/'new-0001.json').write_text(json.dumps(new))
            fixed=dict(old,body_export_version=2,response={'status':200,'body':{'format':'json','value':{'five_hour':{'utilization':0}}}})
            record.write_text(json.dumps({'expires':int(time.time())+60,'accounts':{'A':{'environment_id':'env-a','skip':['unselected'],'exported':['old-0001','new-0001'],'alert_signatures':[],'review_version':1}}}))
            audit={'last_archive':'new','capture_issue':'response_capture_incomplete'}
            status={'body_export_version':2,'audit':audit,'archives':{'old':['0001'],'new':['0001'],'unselected':['0001']}}
            def execute(container,script,payload=None):
                if script==capture_watch.STATUS:return status
                self.assertEqual(script,capture_watch.EXPORT)
                self.assertEqual(payload,{'archives':['old'],'skip':['new-0001']})
                return {'samples':[fixed],'pending':[]}
            with patch.object(capture_watch,'cards',return_value=[{'owner':'A','environment_id':'env-a','container':'fictional'}]),patch.object(capture_watch,'execute',side_effect=execute) as call:
                capture_watch.watch(root,destination,record,once=True)
                self.assertEqual(call.call_count,2)
                capture_watch.watch(root,destination,record,once=True)
                self.assertEqual(call.call_count,3)
            saved=json.loads(record.read_text());account=saved['accounts']['A']
            self.assertEqual(account['body_export_pending'],[]);self.assertEqual(account['skip'],['unselected'])
            self.assertEqual(account['latest_expected_samples'],['new-0001'])
            class Fake:folder=root/'private'
            project={'slug':'a','protection':{'environment_id':'env-a'},'state':{'capture_audit':audit}}
            self.assertEqual(capture_issue_status(Fake(),project)['state'],'complete')
            project['protection']['environment_id']='different'
            self.assertEqual(capture_issue_status(Fake(),project)['state'],'pending')
    def test_missing_archive_is_not_silently_marked_reexported(self):
        import capture_watch
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);destination=root/'samples';destination.mkdir();record=root/'capture-monitor.json'
            record.write_text(json.dumps({'expires':int(time.time())+60,'accounts':{'A':{'environment_id':'env-a','skip':[],'exported':['old-0001'],'alert_signatures':[],'body_export_migration':2,'body_export_pending':['old-0001']}}}))
            observed={'body_export_version':2,'audit':{'last_archive':'old'},'archives':{}}
            with patch.object(capture_watch,'cards',return_value=[{'owner':'A','environment_id':'env-a','container':'fictional'}]),patch.object(capture_watch,'execute',side_effect=[observed,{'samples':[],'pending':[]}]) as call:
                capture_watch.watch(root,destination,record,once=True)
            self.assertEqual(json.loads(record.read_text())['accounts']['A']['body_export_pending'],['old-0001'])

if __name__=='__main__':unittest.main()
