"""Ask Openbox to close only windows belonging to this Chromium process."""
import ctypes as c


def close_windows(pid):
    x=c.CDLL('libX11.so.6');ptr=c.c_void_p;ulong=c.c_ulong
    def fn(name,result,args):
        value=getattr(x,name);value.restype=result;value.argtypes=args;return value
    display=fn('XOpenDisplay',ptr,[c.c_char_p])(b':23')
    if not display:return False
    try:
        root=fn('XDefaultRootWindow',ulong,[ptr])(display)
        atom=fn('XInternAtom',ulong,[ptr,c.c_char_p,c.c_int])
        get=fn('XGetWindowProperty',c.c_int,[ptr,ulong,ulong,c.c_long,c.c_long,c.c_int,ulong,
                                         c.POINTER(ulong),c.POINTER(c.c_int),c.POINTER(ulong),c.POINTER(ulong),c.POINTER(ptr)])
        free=fn('XFree',c.c_int,[ptr])
        def values(window,name):
            kind=ulong();format=c.c_int();count=ulong();remaining=ulong();data=ptr()
            get(display,window,atom(display,name,False),0,4096,False,0,
                c.byref(kind),c.byref(format),c.byref(count),c.byref(remaining),c.byref(data))
            if not data:return []
            try:
                if format.value!=32:return []
                return list(c.cast(data,c.POINTER(ulong))[:count.value])
            finally:free(data)
        class Data(c.Union):
            _fields_=[('b',c.c_char*20),('s',c.c_short*10),('l',c.c_long*5)]
        class Client(c.Structure):
            _fields_=[('type',c.c_int),('serial',ulong),('send_event',c.c_int),('display',ptr),
                      ('window',ulong),('message_type',ulong),('format',c.c_int),('data',Data)]
        class Event(c.Union):
            _fields_=[('client',Client),('padding',c.c_long*24)]
        send=fn('XSendEvent',c.c_int,[ptr,ulong,c.c_int,c.c_long,c.POINTER(Event)])
        sent=False
        for window in values(root,b'_NET_CLIENT_LIST'):
            if values(window,b'_NET_WM_PID')!=[pid]:continue
            event=Event();event.client.type=33;event.client.display=display;event.client.window=window
            event.client.message_type=atom(display,b'_NET_CLOSE_WINDOW',False);event.client.format=32
            event.client.data.l[0]=0;event.client.data.l[1]=2
            sent=bool(send(display,root,False,(1<<19)|(1<<20),c.byref(event))) or sent
        fn('XFlush',c.c_int,[ptr])(display)
        return sent
    finally:fn('XCloseDisplay',c.c_int,[ptr])(display)
