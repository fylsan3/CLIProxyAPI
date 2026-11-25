import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'image'))
from browser_resources import MemoryObserver,memory_snapshot
class MemoryTests(unittest.TestCase):
 def test_new_events_only_and_limits(self):
  with tempfile.TemporaryDirectory() as folder:
   p=Path(folder)
   for k,v in {'memory.current':'10','memory.max':'2147483648','memory.peak':'20','memory.events':'oom 2\noom_kill 1\n'}.items():(p/k).write_text(v)
   events=[];o=MemoryObserver(events.append,p);o.poll();self.assertEqual(events,[])
   (p/'memory.events').write_text('oom 3\noom_kill 2\n');o.poll();o.poll()
   self.assertEqual(len(events),1);self.assertEqual(events[0]['new_oom_kills'],1)
   self.assertEqual(events[0]['memory']['limit_bytes'],2147483648)
   self.assertNotIn('browser',events[0]['attribution'])
 def test_missing_or_unlimited(self):
  with tempfile.TemporaryDirectory() as folder:
   p=Path(folder);(p/'memory.max').write_text('max');self.assertIsNone(memory_snapshot(p)['limit_bytes'])
if __name__=='__main__':unittest.main()
