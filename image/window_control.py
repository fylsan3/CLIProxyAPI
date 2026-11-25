"""Restore only X11 windows owned by the currently running account browser."""
import ctypes as c


class MessageData(c.Union):
    _fields_=[('b',c.c_char*20),('s',c.c_short*10),('l',c.c_long*5)]
class ClientMessage(c.Structure):
    _fields_=[('type',c.c_int),('serial',c.c_ulong),('send_event',c.c_int),('display',c.c_void_p),
              ('window',c.c_ulong),('message_type',c.c_ulong),('format',c.c_int),('data',MessageData)]
class Event(c.Union):
    _fields_=[('client',ClientMessage),('padding',c.c_long*24)]


def restore_browser(pid):
    x=c.CDLL('libX11.so.6');ptr=c.c_void_p;ulong=c.c_ulong
    def bind(name,result,args):
        fn=getattr(x,name);fn.restype=result;fn.argtypes=args;return fn
    display=bind('XOpenDisplay',ptr,[c.c_char_p])(b':23')
    if not display:raise ValueError('desktop_unavailable')
    close=bind('XCloseDisplay',c.c_int,[ptr])
    try:
        root=bind('XDefaultRootWindow',ulong,[ptr])(display)
        atom_fn=bind('XInternAtom',ulong,[ptr,c.c_char_p,c.c_int])
        def atom(name):return atom_fn(display,name.encode(),0)
        get=bind('XGetWindowProperty',c.c_int,[ptr,ulong,ulong,c.c_long,c.c_long,c.c_int,ulong,c.POINTER(ulong),c.POINTER(c.c_int),c.POINTER(ulong),c.POINTER(ulong),c.POINTER(ptr)])
        free=bind('XFree',c.c_int,[ptr])
        def numbers(window,name):
            kind=ulong();fmt=c.c_int();count=ulong();left=ulong();data=ptr()
            get(display,window,atom(name),0,4096,0,0,c.byref(kind),c.byref(fmt),c.byref(count),c.byref(left),c.byref(data))
            if not data:return []
            try:return list(c.cast(data,c.POINTER(ulong))[:count.value]) if fmt.value==32 else []
            finally:free(data)
        windows=[win for win in numbers(root,'_NET_CLIENT_LIST_STACKING') if numbers(win,'_NET_WM_PID')==[pid]]
        if not windows:raise ValueError('browser_window_unavailable')
        show=bind('XMapRaised',c.c_int,[ptr,ulong])
        for win in windows:show(display,win)
        event=Event();event.client.type=33;event.client.display=display;event.client.window=windows[-1]
        event.client.message_type=atom('_NET_ACTIVE_WINDOW');event.client.format=32
        event.client.data.l[0]=2
        bind('XSendEvent',c.c_int,[ptr,ulong,c.c_int,c.c_long,c.POINTER(Event)])(display,root,0,(1<<20)|(1<<19),c.byref(event))
        bind('XSync',c.c_int,[ptr,c.c_int])(display,0)
    finally:close(display)


if __name__=='__main__':
    import sys
    restore_browser(int(sys.argv[1]))
