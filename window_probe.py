import ctypes as c
X=c.CDLL('libX11.so.6'); ptr=c.c_void_p;u=c.c_ulong;l=c.c_long
def fn(n,r,types):
    f=getattr(X,n);f.restype=r;f.argtypes=types;return f
d=fn('XOpenDisplay',ptr,[c.c_char_p])(b':23');assert d
root=fn('XDefaultRootWindow',u,[ptr])(d)
atom=fn('XInternAtom',u,[ptr,c.c_char_p,c.c_int])
prop=fn('XGetWindowProperty',c.c_int,[ptr,u,u,l,l,c.c_int,u,c.POINTER(u),c.POINTER(c.c_int),c.POINTER(u),c.POINTER(u),c.POINTER(ptr)])
free=fn('XFree',c.c_int,[ptr])
def read(win,key):
    typ=u();fmt=c.c_int();n=u();rest=u();buf=ptr()
    prop(d,win,atom(d,key,0),0,2048,0,0,c.byref(typ),c.byref(fmt),c.byref(n),c.byref(rest),c.byref(buf))
    if not buf:return b''
    try:return c.string_at(buf,n.value*(c.sizeof(u) if fmt.value==32 else 1))
    finally:free(buf)
import sys,json
windows=read(root,b'_NET_CLIENT_LIST_STACKING')
items=[]
for i in range(0,len(windows),c.sizeof(u)):
 win=int.from_bytes(windows[i:i+c.sizeof(u)],'little')
 title=read(win,b'_NET_WM_NAME').decode(errors='replace')
 pid=int.from_bytes(read(win,b'_NET_WM_PID'),'little')
 status=int.from_bytes(read(win,b'WM_STATE')[:c.sizeof(u)],'little')
 items.append({'window':win,'title':title,'pid':pid,'state':status})
 if 'MINIMIZE' in globals():fn('XIconifyWindow',c.c_int,[ptr,u,c.c_int])(d,win,0)
fn('XSync',c.c_int,[ptr,c.c_int])(d,0)
print(json.dumps(items))
