"""Gestione di lezioni.md e delle sue versioni nel DB."""
from __future__ import annotations

from .config import env
from .db import LessonVersion, session_scope


def current_lessons() -> tuple[str, int | None]:
    """Contenuto attuale di lezioni.md e id della versione registrata nel DB (creata se manca)."""
    path = env.lessons_path
    content = path.read_text(encoding="utf-8") if path.exists() else "# Lezioni di SolBot\n\n(nessuna lezione ancora)\n"
    with session_scope() as s:
        last = s.query(LessonVersion).order_by(LessonVersion.id.desc()).first()
        if last and last.content == content:
            return content, last.id
        # file modificato a mano o prima esecuzione: registra una nuova versione
        v = LessonVersion(content=content, trigger="manual" if last else "initial", model=None, metrics=None)
        s.add(v)
        s.flush()
        return content, v.id


def save_lessons(content: str, trigger: str, model: str | None, metrics: dict | None, closed_trades: int) -> int:
    env.lessons_path.write_text(content, encoding="utf-8")
    with session_scope() as s:
        v = LessonVersion(content=content, trigger=trigger, model=model, metrics=metrics, closed_trades=closed_trades)
        s.add(v)
        s.flush()
        return v.id
