"""One-time calling-thread controls; no imports or changes to numerical pools."""

from threading import local

from qfr_eval.runtime_contracts import RuntimeCompatibilityError


class _ThreadControls(local):
    attempted: bool = False
    initialized: bool = False
    accelerate: bool = False


_controls = _ThreadControls()


def initialize_thread_controls(*, accelerate: bool) -> None:
    """Set only a fresh thread's controls, never repair drift on a reused thread.

    Callers must observe/verify the complete runtime after this setup. A failed
    setup is terminal for this thread; use a fresh worker after fixing readiness.
    The CLI bootstrap and capture share this guard with worker initialization.
    """
    if _controls.attempted:
        if not _controls.initialized:
            raise RuntimeCompatibilityError("thread_initialization_failed")
        if _controls.accelerate != accelerate:
            raise RuntimeCompatibilityError("thread_numerical_backend_changed")
        return
    _controls.attempted = True
    _controls.accelerate = accelerate
    if accelerate:
        from qfr_eval.apple_runtime import initialize_single_thread

        initialize_single_thread()
    _controls.initialized = True
