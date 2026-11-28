#!/usr/bin/env python3
"""Official CLI browser launcher; login URL remains inside this account container."""
import sys
from claude_code import rpc,SOCKET
if len(sys.argv)!=2:raise SystemExit(2)
result=rpc(SOCKET,{'op':'browser-open','url':sys.argv[1]},timeout=45)
if result.get('error'):raise SystemExit(1)
