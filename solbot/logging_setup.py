import logging
import logging.handlers

from .config import env


def setup_logging() -> None:
    env.log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)-18s %(message)s", "%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    fh = logging.handlers.RotatingFileHandler(env.log_dir / "solbot.log", maxBytes=10_000_000, backupCount=10, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(ch)
    root.addHandler(fh)
    for noisy in ("httpx", "httpcore", "apscheduler", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
