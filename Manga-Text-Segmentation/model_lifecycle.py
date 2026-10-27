"""Stop this model service after Photoshop exits or a local plugin request."""
import ctypes
from ctypes import wintypes
import logging
import threading
import time


def photoshop_running():
    """Check for Photoshop in this Windows session without changing any process."""
    class ProcessEntry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    for name in ("Process32FirstW", "Process32NextW"):
        function = getattr(kernel, name)
        function.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
        function.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    kernel.ProcessIdToSessionId.restype = wintypes.BOOL
    kernel.GetCurrentProcessId.restype = wintypes.DWORD
    session = wintypes.DWORD()
    if not kernel.ProcessIdToSessionId(kernel.GetCurrentProcessId(), ctypes.byref(session)):
        raise ctypes.WinError(ctypes.get_last_error())
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)  # TH32CS_SNAPPROCESS
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = ProcessEntry()
        entry.dwSize = ctypes.sizeof(entry)
        found = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while found:
            if entry.szExeFile.casefold() == "photoshop.exe":
                candidate_session = wintypes.DWORD()
                if not kernel.ProcessIdToSessionId(entry.th32ProcessID, ctypes.byref(candidate_session)):
                    # A matching process can exit while the snapshot is being read.
                    raise ctypes.WinError(ctypes.get_last_error())
                if candidate_session.value == session.value:
                    return True
            found = kernel.Process32NextW(snapshot, ctypes.byref(entry))
        if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
            raise ctypes.WinError(ctypes.get_last_error())
        return False
    finally:
        kernel.CloseHandle(snapshot)


class ModelLifecycle:
    def __init__(self, token, *, watch=False, probe=photoshop_running, check_interval=2, exit_grace=4, shutdown_delay=.4):
        self.token = token
        self.watch = watch
        self.probe = probe
        self.check_interval = check_interval
        self.exit_grace = exit_grace
        self.shutdown_delay = shutdown_delay
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._requested_at = None
        self._reason = None
        self._thread = None

    def state(self):
        with self._lock:
            return {"auto_close_on_ps_exit": self.watch, "stopping": self._requested_at is not None}

    def attach(self):
        with self._lock:
            if self._requested_at is not None:
                return False
            self.watch = True
        return True

    def request_shutdown(self, reason):
        with self._lock:
            if self._requested_at is None:
                self._requested_at = time.monotonic()
                self._reason = reason

    def start(self, stop_server):
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._monitor, args=(stop_server,), daemon=True, name="photoshop-model-lifecycle")
        self._thread.start()

    def close(self):
        self._stop.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)

    def _monitor(self, stop_server):
        next_check = 0
        missing_since = None
        probe_failed = False
        while not self._stop.wait(.05):
            now = time.monotonic()
            with self._lock:
                requested_at, reason, watch = self._requested_at, self._reason, self.watch
            if requested_at is not None:
                # Give the shutdown HTTP response time to reach the plugin.
                if now - requested_at >= self.shutdown_delay:
                    logging.getLogger("uvicorn.error").info("Stopping model: %s", reason)
                    stop_server()
                    return
                continue
            if not watch or now < next_check:
                continue
            next_check = now + self.check_interval
            try:
                alive = self.probe()
                probe_failed = False
            except OSError:
                # A failed process query must not be interpreted as Photoshop exiting.
                missing_since = None
                if not probe_failed:
                    logging.getLogger("uvicorn.error").warning("Photoshop process query failed; keeping model running.")
                probe_failed = True
                continue
            if alive:
                missing_since = None
            elif missing_since is None:
                missing_since = now
            elif now - missing_since >= self.exit_grace:
                self.request_shutdown("Photoshop exited")
