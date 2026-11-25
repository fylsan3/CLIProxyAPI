"""Fail-closed Linux central guard: no outbound TCP or datagram/raw sockets."""
import ctypes,ctypes.util,errno,json,os,platform,sys

class Ruleset(ctypes.Structure):
    _fields_=[('fs',ctypes.c_uint64),('net',ctypes.c_uint64)]
class Compare(ctypes.Structure):
    _fields_=[('arg',ctypes.c_uint),('op',ctypes.c_int),('mask',ctypes.c_uint64),('value',ctypes.c_uint64)]

def enforce():
    if sys.platform!='linux' or platform.machine() not in ('aarch64','x86_64'):
        raise RuntimeError('unsupported_linux_architecture')
    libc=ctypes.CDLL(None,use_errno=True);libc.syscall.restype=ctypes.c_long
    abi=libc.syscall(444,0,0,1)
    if abi<4:raise RuntimeError('landlock_network_support_required')
    if libc.prctl(38,1,0,0,0)!=0:raise OSError(ctypes.get_errno(),'no_new_privs_failed')
    rules=Ruleset(0,2) # Handle CONNECT_TCP, with no allowed destination ports.
    fd=libc.syscall(444,ctypes.byref(rules),ctypes.sizeof(rules),0)
    if fd<0:raise OSError(ctypes.get_errno(),'landlock_create_failed')
    try:
        if libc.syscall(446,fd,0)!=0:raise OSError(ctypes.get_errno(),'landlock_enforcement_failed')
    finally:os.close(fd)
    library=ctypes.util.find_library('seccomp')
    if not library:raise RuntimeError('libseccomp_required')
    sec=ctypes.CDLL(library,use_errno=True)
    sec.seccomp_init.argtypes=[ctypes.c_uint32];sec.seccomp_init.restype=ctypes.c_void_p
    sec.seccomp_syscall_resolve_name.argtypes=[ctypes.c_char_p];sec.seccomp_syscall_resolve_name.restype=ctypes.c_int
    sec.seccomp_rule_add_array.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_int,ctypes.c_uint,ctypes.POINTER(Compare)]
    sec.seccomp_load.argtypes=[ctypes.c_void_p];sec.seccomp_release.argtypes=[ctypes.c_void_p]
    filt=sec.seccomp_init(0x7fff0000)
    if not filt:raise RuntimeError('seccomp_init_failed')
    try:
        syscall=sec.seccomp_syscall_resolve_name(b'socket')
        if syscall<0:raise RuntimeError('socket_syscall_unavailable')
        for kind in (2,3): # SOCK_DGRAM and SOCK_RAW, including creation flags.
            comparison=Compare(1,7,15,kind)
            if sec.seccomp_rule_add_array(filt,0x50000|errno.EACCES,syscall,1,ctypes.byref(comparison))!=0:
                raise RuntimeError('seccomp_rule_failed')
        if sec.seccomp_load(filt)!=0:raise RuntimeError('seccomp_load_failed')
    finally:sec.seccomp_release(filt)
    return {'landlock_abi':abi,'outbound_tcp':False,'datagram_and_raw_sockets':False,'unix_stream':True,'tcp_listen':True}

if __name__=='__main__':
    if len(sys.argv)<3 or sys.argv[1]!='--':raise SystemExit('usage: network_guard.py -- program [args]')
    if os.geteuid()==0:raise SystemExit('dedicated_unprivileged_central_user_required')
    enforce()
    os.execv(sys.argv[2],sys.argv[2:])
