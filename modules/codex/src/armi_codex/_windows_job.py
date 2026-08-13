"""Minimal non-breakaway Windows Job Object ownership."""

from __future__ import annotations

import ctypes
import os
from types import TracebackType
from typing import Self

from ._runner_contract import CodexRunnerViolation

_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_LIMIT_ACTIVE_PROCESS = 0x00000008
_LIMIT_JOB_MEMORY = 0x00000200
_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000


class _IoCounters(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_uint64)
        for name in (
            "read_operation_count",
            "write_operation_count",
            "other_operation_count",
            "read_transfer_count",
            "write_transfer_count",
            "other_transfer_count",
        )
    ]


class _BasicLimitInformation(ctypes.Structure):
    _fields_ = (
        ("per_process_user_time_limit", ctypes.c_int64),
        ("per_job_user_time_limit", ctypes.c_int64),
        ("limit_flags", ctypes.c_uint32),
        ("minimum_working_set_size", ctypes.c_size_t),
        ("maximum_working_set_size", ctypes.c_size_t),
        ("active_process_limit", ctypes.c_uint32),
        ("affinity", ctypes.c_size_t),
        ("priority_class", ctypes.c_uint32),
        ("scheduling_class", ctypes.c_uint32),
    )


class _ExtendedLimitInformation(ctypes.Structure):
    _fields_ = (
        ("basic_limit_information", _BasicLimitInformation),
        ("io_info", _IoCounters),
        ("process_memory_limit", ctypes.c_size_t),
        ("job_memory_limit", ctypes.c_size_t),
        ("peak_process_memory_used", ctypes.c_size_t),
        ("peak_job_memory_used", ctypes.c_size_t),
    )


class WindowsJob:
    __slots__ = ("_handle",)

    def __init__(self, *, active_process_limit: int = 32, memory_limit: int = 2 << 30):
        if os.name != "nt":
            raise CodexRunnerViolation("CODEX-JOB-UNAVAILABLE")
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p)
        kernel32.CreateJobObjectW.restype = ctypes.c_void_p
        kernel32.SetInformationJobObject.argtypes = (
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
        )
        kernel32.SetInformationJobObject.restype = ctypes.c_int
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise CodexRunnerViolation("CODEX-JOB-UNAVAILABLE")
        self._handle = handle
        limits = _ExtendedLimitInformation()
        limits.basic_limit_information.limit_flags = (
            _LIMIT_ACTIVE_PROCESS | _LIMIT_JOB_MEMORY | _LIMIT_KILL_ON_JOB_CLOSE
        )
        limits.basic_limit_information.active_process_limit = active_process_limit
        limits.job_memory_limit = memory_limit
        if not kernel32.SetInformationJobObject(
            ctypes.c_void_p(handle),
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            kernel32.CloseHandle(ctypes.c_void_p(handle))
            self._handle = None
            raise CodexRunnerViolation("CODEX-JOB-UNAVAILABLE")

    def assign(self, process_handle: int) -> None:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.AssignProcessToJobObject.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
        kernel32.AssignProcessToJobObject.restype = ctypes.c_int
        if self._handle is None or not kernel32.AssignProcessToJobObject(
            ctypes.c_void_p(self._handle), ctypes.c_void_p(process_handle)
        ):
            raise CodexRunnerViolation("CODEX-JOB-ASSIGN")

    def close(self) -> None:
        if self._handle is not None:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
            kernel32.CloseHandle.restype = ctypes.c_int
            kernel32.CloseHandle(ctypes.c_void_p(self._handle))
            self._handle = None

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        self.close()
        return False


__all__ = ("WindowsJob",)
