"""Elapsed awake Windows time, independent of wall-clock corrections."""

import ctypes


def awake_microseconds() -> int:
    value = ctypes.c_ulonglong()
    query = ctypes.WinDLL(
        "api-ms-win-core-realtime-l1-1-2.dll", use_last_error=True
    ).QueryUnbiasedInterruptTimePrecise
    query.argtypes = [ctypes.POINTER(ctypes.c_ulonglong)]
    query.restype = None
    query(ctypes.byref(value))
    return value.value // 10
