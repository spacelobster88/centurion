from __future__ import annotations


class CenturionError(Exception):
    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class TaskTimeoutError(CenturionError):
    def __init__(self, message: str, *, timeout_seconds: float = 0.0):
        super().__init__(message, retryable=True)
        self.timeout_seconds = timeout_seconds


class AgentProcessError(CenturionError):
    TRANSIENT_EXIT_CODES = {-9, -15, -11, 137, 139}
    SIGKILL_EXIT_CODES = {-9, 137}

    def __init__(self, message: str, *, exit_code: int | None = None, stderr: str = "", jetsam: bool = False):
        retryable = exit_code in self.TRANSIENT_EXIT_CODES if exit_code else False
        super().__init__(message, retryable=retryable)
        self.exit_code = exit_code
        self.stderr = stderr
        self.jetsam = jetsam


class AgentAPIError(CenturionError):
    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

    def __init__(self, message: str, *, status_code: int | None = None):
        retryable = status_code in self.RETRYABLE_STATUS_CODES if status_code else False
        super().__init__(message, retryable=retryable)
        self.status_code = status_code


class SchedulerError(CenturionError):
    def __init__(self, message: str):
        super().__init__(message, retryable=False)


class ConfigurationError(CenturionError):
    def __init__(self, message: str):
        super().__init__(message, retryable=False)
