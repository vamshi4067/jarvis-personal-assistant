"""Request-scoped draft progress; never replaces the agent's completed answer."""
from contextlib import contextmanager
from contextvars import ContextVar

_listener=ContextVar('jarvis_live_reply_listener',default=None)
_early_speech=ContextVar('jarvis_early_speech',default=False)
_cancelled=ContextVar('jarvis_live_reply_cancelled',default=None)


def check_cancelled():
    flag=_cancelled.get()
    if flag is not None and flag.is_set():raise RuntimeError('This reply was cancelled.')


def emit(kind,**data):
    check_cancelled()
    callback=_listener.get()
    if callback is not None:callback({'kind':kind,**data})


def speech_allowed():
    return _early_speech.get()


@contextmanager
def progress_context(listener,cancelled,early_speech=False):
    a=_listener.set(listener);b=_cancelled.set(cancelled);c=_early_speech.set(early_speech)
    try:yield
    finally:_listener.reset(a);_cancelled.reset(b);_early_speech.reset(c)
