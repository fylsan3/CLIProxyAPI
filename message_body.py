"""Read native-approved bodies from the private central bridge only."""
import json
from runtime_guard import PolicyError

def read_message(headers,stream):
 lengths=headers.get_all('Content-Length',[])
 if headers.get('Transfer-Encoding') or len(lengths)!=1:raise PolicyError('invalid_request')
 try:size=int(lengths[0])
 except ValueError:raise PolicyError('invalid_request') from None
 if size<0:raise PolicyError('invalid_request')
 raw=stream.read(size)
 if len(raw)!=size:raise PolicyError('invalid_request')
 try:value=json.loads(raw)
 except ValueError:raise PolicyError('invalid_request') from None
 if not isinstance(value,dict):raise PolicyError('invalid_request')
 return raw,value
