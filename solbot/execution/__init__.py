from .base import ExecutionEngine, FillResult
from .paper import PaperEngine, model_slippage_pct

__all__ = ["ExecutionEngine", "FillResult", "PaperEngine", "model_slippage_pct", "get_engine"]


def get_engine() -> ExecutionEngine:
    """Ritorna sempre il PaperEngine finché il gate live non è superato E confermato E abilitato."""
    from .live import LiveEngine, live_allowed

    ok, _ = live_allowed()
    return LiveEngine() if ok else PaperEngine()
