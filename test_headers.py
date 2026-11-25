import unittest
from email.message import Message
from header_policy import request_headers,response_headers
class HeadersTest(unittest.TestCase):
 def test_request_features_not_credentials(self):
  h=Message()
  for k,v in [('Anthropic-Beta','feature-a'),('Anthropic-Beta','feature-b'),('Authorization','secret'),('Cookie','secret'),('X-Stainless-OS','private'),('Anthropic-Version','2023-06-01'),('Accept','application/json')]:h[k]=v
  self.assertEqual(request_headers(h),{'Anthropic-Beta':['feature-a','feature-b'],'Anthropic-Version':['2023-06-01'],'Accept':['application/json']})
  h['Connection']='Anthropic-Beta, Accept'
  self.assertEqual(request_headers(h),{'Anthropic-Version':['2023-06-01']})
 def test_response_extensions_and_http_boundaries(self):
  h={'Retry-After':['2'],'X-Feature':['one','two'],'X-Litellm-Test':['keep'],'Set-Cookie':['secret'],'connection':['X-Hop'],'X-Hop':['drop'],'X-Test-Container':['spoof'],'X-Offline-Owner':['spoof'],'Content-Encoding':['gzip'],'Content-Length':['123'],'Access-Control-Allow-Origin':['*']}
  self.assertEqual(response_headers(h),{'Retry-After':['2'],'X-Feature':['one','two'],'X-Litellm-Test':['keep']})
  out=response_headers(h);out['X-Feature'].append('third');self.assertEqual(len(h['X-Feature']),2)
if __name__=='__main__':unittest.main()
