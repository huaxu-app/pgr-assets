import os

from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# (connect timeout, read timeout) in seconds. A dead CDN must not hang the run forever.
_DEFAULT_TIMEOUT = (10, 60)

_session: Session | None = None
_session_pid: int | None = None


class _TimeoutHTTPAdapter(HTTPAdapter):
    """Applies a default timeout to every request that doesn't set one explicitly."""

    def __init__(self, *args, timeout=None, **kwargs):
        self._timeout = timeout
        super().__init__(*args, **kwargs)

    def send(self, request, **kwargs):
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = self._timeout
        return super().send(request, **kwargs)


def get_session() -> Session:
    """Return a pooled, retrying requests.Session for the current process.

    Connection pooling, retries and a default timeout are configured on the
    adapter, so callers can just use ``get_session().get(url)``.

    The session is cached per-PID: after a fork the child gets a fresh session
    instead of reusing the parent's connection pool (whose open sockets are
    unsafe to share across processes).
    """
    global _session, _session_pid

    pid = os.getpid()
    if _session is not None and _session_pid == pid:
        return _session

    session = Session()
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=(500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
    )
    adapter = _TimeoutHTTPAdapter(
        timeout=_DEFAULT_TIMEOUT,
        pool_connections=32,
        pool_maxsize=32,
        max_retries=retry,
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    _session = session
    _session_pid = pid
    return session
