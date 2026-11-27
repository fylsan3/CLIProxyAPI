"""Exercise packaging reminders without compiling, contacting accounts or deploying."""
import contextlib,io,json,runpy,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
import build,build_inputs

class ReminderReached(Exception):pass

class BuildReviewTests(unittest.TestCase):
    def test_each_invocation_has_its_own_pending_record_and_never_edits_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'src/internal/accountheaders/policy.go'
            source.parent.mkdir(parents=True);source.write_text('fictional input')
            with contextlib.redirect_stdout(io.StringIO()) as output:
                first=build_inputs.remind_linked_review(root,'fixture')
                second=build_inputs.remind_linked_review(root,'fixture')
            self.assertEqual(source.read_text(),'fictional input')
            self.assertEqual(len(list((root/'evidence/build-reviews').glob('*.json'))),2)
            for report in (first,second):
                self.assertEqual(report['verification_status'],'pending')
                self.assertEqual(set(report['groups']),{'oauth_headers','go_executor_headers','cc_version'})
                self.assertTrue(report['reminder_triggered'])
            self.assertEqual(output.getvalue().count('[打包必查]'),2)
            source.write_text('changed fictional input')
            with contextlib.redirect_stdout(io.StringIO()):third=build_inputs.remind_linked_review(root,'fixture')
            self.assertNotEqual(first['input_sha256'][str(source.relative_to(root))],third['input_sha256'][str(source.relative_to(root))])

    def test_all_build_functions_trigger_before_build_work(self):
        for entry,operation in [('build:full',lambda:build.build()),('build:compile-only',lambda:build.build(False)),('build:control-only',build.build_control),('build:capture-only',build.build_capture)]:
            with self.subTest(entry=entry),patch.object(build_inputs,'remind_linked_review',side_effect=ReminderReached) as reminder:
                with self.assertRaises(ReminderReached):operation()
                reminder.assert_called_once_with(ROOT,entry)

    def test_compatibility_and_ui_entrypoints_are_covered(self):
        for name in ['build_central.py','build_worker_image.py','build_image.py','build_config.py','build_header_fixture.py','build_page.py']:
            with self.subTest(entry=name),patch.object(build_inputs,'remind_linked_review',side_effect=ReminderReached) as reminder:
                with self.assertRaises(ReminderReached):runpy.run_path(str(ROOT/name),run_name='__main__')
                reminder.assert_called_once_with(ROOT,'build:management-page' if name=='build_page.py' else 'build:full')

if __name__=='__main__':unittest.main(verbosity=2)
