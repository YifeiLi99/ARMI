"""Bounded capture for private workers; never install on protocol stdout."""

from __future__ import annotations

import io
import json
import threading

from armi_kernel.application import record_diagnostic


class DiagnosticTextStream(io.TextIOBase):
    encoding = "utf-8"

    def __init__(self, source: str) -> None:
        self.source = source
        self._buffer = ""
        self._lock = threading.RLock()

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        with self._lock:
            self._buffer += text
            while "\n" in self._buffer or len(self._buffer) >= 4096:
                end = self._buffer.find("\n")
                if end < 0 or end > 4096:
                    end = 4096
                    line, self._buffer = self._buffer[:end], self._buffer[end:]
                else:
                    line, self._buffer = self._buffer[:end], self._buffer[end + 1 :]
                self._emit(line)
        return len(text)

    def _emit(self, line: str) -> None:
        try:
            value: object = json.loads(line)
        except ValueError:
            value = line
        record_diagnostic(
            "process.output",
            component="process",
            stream=self.source,
            output=value,
            unstructured=not isinstance(value, dict),
        )

    def flush(self) -> None:
        with self._lock:
            if self._buffer:
                line, self._buffer = self._buffer, ""
                self._emit(line)
