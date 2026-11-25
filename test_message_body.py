"""Private framing validation remains strict after removing fixture size limits."""
import io,json,sys,unittest
from email.message import Message
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'runtime-persistence/project'))
from message_body import read_message
from runtime_guard import PolicyError

class MessageTests(unittest.TestCase):
 def headers(self,raw):
  h=Message();h['Content-Length']=str(len(raw));return h
 def test_large_unicode_body_is_preserved(self):
  raw=json.dumps({'messages':[{'role':'user','content':'研发'*70000}]},ensure_ascii=False).encode()
  actual,value=read_message(self.headers(raw),io.BytesIO(raw));self.assertEqual(actual,raw);self.assertEqual(value['messages'][0]['content'],'研发'*70000)
 def test_ambiguous_framing_rejected(self):
  for kind in ('duplicate','chunked','negative','invalid','missing'):
   h=Message()
   if kind!='missing':h['Content-Length']='-1' if kind=='negative' else 'bad' if kind=='invalid' else '2'
   if kind=='duplicate':h['Content-Length']='2'
   if kind=='chunked':h['Transfer-Encoding']='chunked'
   with self.subTest(kind=kind),self.assertRaises(PolicyError):read_message(h,io.BytesIO(b'{}'))
 def test_short_or_nonobject_body_rejected(self):
  for raw,supplied in [(b'{}',b'{'),(b'[]',b'[]'),(b'{',b'{')]:
   with self.subTest(raw=raw),self.assertRaises(PolicyError):read_message(self.headers(raw),io.BytesIO(supplied))

if __name__=='__main__':unittest.main()
