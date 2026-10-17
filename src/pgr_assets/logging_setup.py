import logging
import multiprocessing
import os
import sys
from collections.abc import Generator
from contextlib import contextmanager
from logging.handlers import QueueHandler, QueueListener
from multiprocessing.queues import Queue

from tqdm import tqdm

VERBOSE_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

RESET = "\033[0m"
LEVEL_COLOR = {
    logging.WARNING: "\033[33m",  # yellow
    logging.ERROR: "\033[31m",  # red
    logging.CRITICAL: "\033[31m",
}


class TqdmLoggingHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            tqdm.write(self.format(record), file=sys.stderr)
        except Exception:
            self.handleError(record)


class CliFormatter(logging.Formatter):
    def __init__(self, color: bool):
        super().__init__("%(message)s")
        self._color = color

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)  # keeps %(message)s plus any traceback
        if record.levelno >= logging.WARNING:
            base = f"{record.levelname.lower()}: {base}"
        color = LEVEL_COLOR.get(record.levelno)
        if self._color and color:
            return f"{color}{base}{RESET}"
        return base


def configure_logging(level: int | str = logging.INFO) -> None:
    if isinstance(level, str):
        level = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)

    handler = TqdmLoggingHandler()
    if level <= logging.DEBUG:
        handler.setFormatter(logging.Formatter(VERBOSE_FORMAT))
    else:
        color = sys.stderr.isatty() and not os.environ.get("NO_COLOR")
        handler.setFormatter(CliFormatter(color))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


@contextmanager
def worker_logs() -> Generator[tuple[Queue, int]]:
    """
    Print worker process records through this process's handlers, so they
    clear and redraw the progress bar. Pass the yielded pair to
    `log_to_queue` in each worker's initializer.
    """
    queue: Queue = multiprocessing.Queue()
    root = logging.getLogger()
    listener = QueueListener(queue, *root.handlers, respect_handler_level=True)
    listener.start()
    try:
        yield queue, root.level
    finally:
        listener.stop()


def log_to_queue(queue: Queue, level: int) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(QueueHandler(queue))
    root.setLevel(level)
