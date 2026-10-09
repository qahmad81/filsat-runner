"""Terminate the complete provider process tree, including children surviving their launcher."""
import ctypes
import os
import signal
import subprocess

class ProcessTree:
    def __init__(self):
        self.handle=None
        if os.name!='nt': return
        from ctypes import wintypes as w
        class Limits(ctypes.Structure):
            _fields_=[('process_time',ctypes.c_longlong),('job_time',ctypes.c_longlong),('flags',w.DWORD),('min_ws',ctypes.c_size_t),('max_ws',ctypes.c_size_t),('active_processes',w.DWORD),('affinity',ctypes.c_size_t),('priority',w.DWORD),('scheduling',w.DWORD)]
        class IO(ctypes.Structure):
            _fields_=[(name,ctypes.c_ulonglong) for name in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
        class Extended(ctypes.Structure):
            _fields_=[('basic',Limits),('io',IO),('process_memory',ctypes.c_size_t),('job_memory',ctypes.c_size_t),('peak_process',ctypes.c_size_t),('peak_job',ctypes.c_size_t)]
        self.api=ctypes.WinDLL('kernel32',use_last_error=True)
        self.api.CreateJobObjectW.restype=w.HANDLE
        self.api.CreateJobObjectW.argtypes=[ctypes.c_void_p,w.LPCWSTR]
        self.api.SetInformationJobObject.argtypes=[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD]
        self.api.AssignProcessToJobObject.argtypes=[w.HANDLE,w.HANDLE]
        self.api.CloseHandle.argtypes=[w.HANDLE]
        self.handle=self.api.CreateJobObjectW(None,None)
        limits=Extended(); limits.basic.flags=0x2000 # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.handle or not self.api.SetInformationJobObject(self.handle,9,ctypes.byref(limits),ctypes.sizeof(limits)):
            self.close(); raise OSError('Cannot create provider process containment')

    def spawn(self,command,**kwargs):
        opts={'creationflags':subprocess.CREATE_NEW_PROCESS_GROUP|0x4} if os.name=='nt' else {'start_new_session':True}
        proc=subprocess.Popen(command,**kwargs,**opts)
        if os.name=='nt':
            from ctypes import wintypes as w
            if not self.api.AssignProcessToJobObject(self.handle,w.HANDLE(int(proc._handle))):
                proc.kill(); proc.wait(); self.close(); raise OSError('Cannot contain provider process tree')
            nt=ctypes.WinDLL('ntdll'); nt.NtResumeProcess.argtypes=[w.HANDLE]; nt.NtResumeProcess.restype=ctypes.c_long
            if nt.NtResumeProcess(w.HANDLE(int(proc._handle)))!=0:
                self.close(); proc.wait(); raise OSError('Cannot start provider process')
        return proc

    def close(self,proc=None):
        if self.handle:
            self.api.CloseHandle(self.handle); self.handle=None
        elif proc is not None and os.name!='nt':
            try: os.killpg(proc.pid,signal.SIGKILL)
            except ProcessLookupError: pass
        if proc is not None:
            try: proc.wait(timeout=10)
            except subprocess.TimeoutExpired: proc.kill(); proc.wait()
