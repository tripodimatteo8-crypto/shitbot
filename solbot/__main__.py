"""Uso:
  python -m solbot            avvia bot + API/dashboard (default)
  python -m solbot report     report da terminale
  python -m solbot once       un singolo giro collect -> agente -> monitor (debug)
  python -m solbot reflect    forza una riflessione su lezioni.md
"""
from __future__ import annotations

import sys

from .config import env
from .logging_setup import setup_logging


def main() -> None:
    setup_logging()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    from .db import init_db

    init_db()
    if cmd == "run":
        import uvicorn

        uvicorn.run("solbot.api:app", host=env.host, port=env.port, log_level="warning")
    elif cmd == "report":
        from .report import print_report

        print_report()
    elif cmd == "once":
        from .agent import run_cycle
        from .collector import collect
        from .db import session_scope
        from .lessons import current_lessons
        from .portfolio import ensure_account, record_equity
        from .scheduler import monitor_positions

        with session_scope() as s:
            ensure_account(s)
        current_lessons()
        collect()
        run_cycle()
        monitor_positions()
        print(record_equity())
    elif cmd == "reflect":
        from .reflection import reflect

        print("versione:", reflect("manual"))
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
