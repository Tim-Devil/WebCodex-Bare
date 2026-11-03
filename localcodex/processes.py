"""Explicit process-tree ownership, using Job Objects on Windows and groups on Linux."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import signal
import subprocess
import time

import psutil


class ProcessTree:
    def __init__(self, argv: list[str], **kwargs):
        self.job = None
        if os.name == "nt":
            self._windows_api()
            self.job = self.api.CreateJobObjectW(None, None)
            if not self.job:
                raise ctypes.WinError()
            info = ExtendedLimit()
            info.BasicLimitInformation.LimitFlags = 0x2000
            if not self.api.SetInformationJobObject(self.job, 9, ctypes.byref(info), ctypes.sizeof(info)):
                self.api.CloseHandle(self.job)
                raise ctypes.WinError()
            try:
                self.process = subprocess.Popen(argv, creationflags=0x00000004 | 0x08000000, **kwargs)
                if not self.api.AssignProcessToJobObject(self.job, int(self.process._handle)):
                    raise ctypes.WinError()
                threads = psutil.Process(self.process.pid).threads()
                if len(threads) != 1:
                    raise RuntimeError("Suspended child has an unexpected thread count")
                thread = self.api.OpenThread(0x0002, False, threads[0].id)
                if not thread:
                    raise ctypes.WinError()
                try:
                    if self.api.ResumeThread(thread) == 0xFFFFFFFF:
                        raise ctypes.WinError()
                finally:
                    self.api.CloseHandle(thread)
            except BaseException:
                if hasattr(self, "process"):
                    self.process.kill()
                    self.process.wait(timeout=5)
                self.api.CloseHandle(self.job)
                self.job = None
                raise
        else:
            self.process = subprocess.Popen(argv, start_new_session=True, **kwargs)

    @property
    def pid(self):
        return self.process.pid

    def poll(self):
        return self.process.poll()

    def stop(self, seconds: float = 3) -> None:
        if os.name == "nt":
            if self.job:
                if not self.api.TerminateJobObject(self.job, 1):
                    raise ctypes.WinError()
                self.process.wait(timeout=seconds)
                self.api.CloseHandle(self.job)
                self.job = None
        else:
            try:
                os.killpg(self.pid, signal.SIGTERM)
            except ProcessLookupError:
                self.process.wait(timeout=seconds)
                return
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                try:
                    os.killpg(self.pid, 0)
                except ProcessLookupError:
                    self.process.wait(timeout=seconds)
                    return
                self.process.poll()
                time.sleep(0.05)
            os.killpg(self.pid, signal.SIGKILL)
            self.process.wait(timeout=seconds)

    def _windows_api(self):
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
            "SetInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
            "AssignProcessToJobObject": ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
            "TerminateJobObject": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
            "OpenThread": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            "ResumeThread": ([wintypes.HANDLE], wintypes.DWORD),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.api, name)
            function.argtypes = arguments
            function.restype = result


class BasicLimit(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD)]


class IOCounts(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class ExtendedLimit(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", BasicLimit), ("IoInfo", IOCounts),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]
