import threading
import time
import traceback
from typing import Any, Callable, Generic, TypeVar

__all__ = [
    "Future",
    "WritableFuture",
]

T = TypeVar("T")


class Future(Generic[T]):
    """
    Future-like object representing one asynchronous execution result.

    This class is thread-safe.

    Lifecycle:

        Pending
            │
            ├── cancel()
            │
            ▼
        Cancelled

            or

        Pending
            │
            ├── set_result()
            ├── set_error()
            │
            ▼
        Finished

    Notes:
        - cancel() only cancels waiting on the host side.
        - It does NOT stop already queued graph execution.
        - Result and error are immutable once finished.
    """

    def __init__(
        self,
        *,
        cascade: Callable[[Any], T] | None = None,
    ):
        self.__event = threading.Event()
        self.__lock = threading.Lock()

        self.__payload: T | None = None
        self.__error: BaseException | None = None
        self.__cancelled = False

        self.__time_beg = time.time()
        self.__time_end: float | None = None

        self.__cascade = cascade

    @property
    def payload(self) -> T:
        """
        Return result payload.

        Raises:
            RuntimeError:
                Future has not finished yet.
        """
        if not self.done():
            raise RuntimeError("Future is not finished. Call wait() or get() first.")
        return self.__payload  # type: ignore

    @property
    def error(self) -> BaseException | None:
        """
        Return execution error.

        Raises:
            RuntimeError:
                Future has not finished yet.
        """
        if not self.done():
            raise RuntimeError("Future is not finished. Call wait() or get() first.")
        return self.__error

    @property
    def elapsed(self) -> float | None:
        """
        Return elapsed execution time in seconds.

        Returns None if the Future has not finished.
        """
        if self.__time_end is None:
            return None

        return self.__time_end - self.__time_beg

    # ----------------------------------------------------------------------
    # State
    # ----------------------------------------------------------------------

    def done(self) -> bool:
        """
        Return True if this Future has completed,
        either by success, failure or cancellation.
        """
        return self.__event.is_set()

    def cancelled(self) -> bool:
        """
        Return True if this Future has been cancelled.
        """
        with self.__lock:
            return self.__cancelled

    def cancel(self) -> bool:
        """
        Cancel this Future.

        Returns:
            True:
                Cancelled successfully.

            False:
                Already completed.
        """
        with self.__lock:
            if self.__event.is_set():
                return False

            self.__cancelled = True
            self.__time_end = time.time()
            self.__event.set()
            return True

    def wait(self, timeout: float | None = None) -> bool:
        """
        Wait until the Future completes.

        Args:
            timeout:
                Maximum waiting time in seconds.
                None means wait forever.

        Returns:
            True:
                Future has completed successfully,
                failed, or been cancelled.

            False:
                Timeout occurred.
        """
        return self.__event.wait(timeout)

    def get(self, timeout: float | None = None) -> T:
        """
        Wait and return the execution result.

        Raises:
            TimeoutError:
                Result not available before timeout.

            RuntimeError:
                Future has been cancelled.

            BaseException:
                Original execution exception.
        """
        if not self.wait(timeout):
            raise TimeoutError("Timeout waiting for Future.")

        if self.cancelled():
            raise RuntimeError("Future was cancelled.")

        if self.__error is not None:
            raise self.__error

        return self.__payload  # type: ignore

    def _set_result(self, payload: Any) -> bool:
        """
        Internal use only.

        Store result and mark Future finished.

        Returns:
            False if Future has already completed.
        """
        with self.__lock:
            if self.__event.is_set():
                return False

            if self.__cascade is not None:
                try:
                    payload = self.__cascade(payload)
                except Exception:
                    self.__error = RuntimeError("Cascade conversion failed.\n" + traceback.format_exc())
                    self.__time_end = time.time()
                    self.__event.set()
                    return True

            self.__payload = payload
            self.__time_end = time.time()
            self.__event.set()
            return True

    def _set_error(self, error: BaseException) -> bool:
        """
        Internal use only.

        Store exception and mark Future finished.
        """
        with self.__lock:
            if self.__event.is_set():
                return False

            self.__error = error
            self.__time_end = time.time()
            self.__event.set()
            return True

    def _cascade(self, converter: Callable[[Any], T]):
        """
        Set or replace payload converter.

        The converter is applied before the Future
        stores the final payload.
        """
        self.__cascade = converter


class WritableFuture(Future[T]):
    """
    Writable Future.

    Only framework internals should use this class.
    User code should only see Future[T].
    """

    def set_result(self, payload: Any) -> bool:
        return self._set_result(payload)

    def set_error(self, error: BaseException) -> bool:
        return self._set_error(error)
