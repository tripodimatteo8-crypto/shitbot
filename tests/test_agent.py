"""Ciclo dell'agente Claude con un client finto (nessuna chiamata reale)."""
from types import SimpleNamespace as NS

from solbot import agent
from solbot.config import env
from solbot.db import Candidate, ClaudeUsage, Decision, Position, Snapshot, session_scope
from solbot.portfolio import ensure_account


def _usage():
    return NS(input_tokens=1000, output_tokens=200, cache_read_input_tokens=0, cache_creation_input_tokens=500)


class FakeMessages:
    def __init__(self, script):
        self.script = script
        self.calls = []

    def create(self, **kw):
        self.calls.append(kw)
        content = self.script.pop(0)
        stop = "tool_use" if any(b.type == "tool_use" for b in content) else "end_turn"
        return NS(content=content, stop_reason=stop, usage=_usage(), model=kw["model"])


def tool(id_, name, **inp):
    return NS(type="tool_use", id=id_, name=name, input=inp)


def test_claude_cycle_buys_and_skips(fresh_db, monkeypatch):
    fresh_db.price["MINT2"] = 0.002
    with session_scope() as s:
        ensure_account(s)
        for m, p in (("MINT", 0.001), ("MINT2", 0.002)):
            s.add(Snapshot(mint=m, price_usd=p, liquidity_usd=50_000))
            s.add(Candidate(mint=m, symbol=m, price_usd=p, liquidity_usd=50_000, passed_filters=True, status="pending", features={}))
    script = [
        [tool("t1", "get_portfolio")],
        [
            NS(type="text", text="Analizzo."),
            tool("t2", "paper_buy", mint="MINT", usd_amount=30, reason="volume forte, holder distribuiti", confidence=0.6),
            tool("t3", "skip_token", mint="MINT2", reason="pump verticale", confidence=0.7),
        ],
        [NS(type="text", text="Fatto.")],
    ]
    fake = FakeMessages(script)
    client = NS(messages=fake, beta=NS(messages=fake))
    monkeypatch.setattr(agent.anthropic, "Anthropic", lambda **kw: client)
    monkeypatch.setattr(env, "anthropic_api_key", "test-key")
    monkeypatch.setattr(env, "decider", "auto")
    from solbot import claude_cli

    monkeypatch.setattr(claude_cli, "cli_path", lambda: None)  # niente CLI: si usa l'API

    res = agent.run_cycle()
    assert res["decider"] == "claude" and res["decided"] == 2
    with session_scope() as s:
        decs = {d.mint: d for d in s.query(Decision).all()}
        assert decs["MINT"].action == "buy" and decs["MINT"].executed and decs["MINT"].confidence == 0.6
        assert decs["MINT2"].action == "skip"
        assert s.query(Position).filter(Position.status == "open").count() == 1
        assert s.query(ClaudeUsage).count() == 3
        statuses = {c.mint: c.status for c in s.query(Candidate).all()}
        assert statuses == {"MINT": "buy", "MINT2": "skip"}
    # system prompt con cache e lezioni, tool definiti
    first = fake.calls[0]
    assert first["system"][0]["cache_control"]["type"] == "ephemeral"
    assert {t["name"] for t in first["tools"]} >= {"paper_buy", "paper_sell", "skip_token", "get_token_data"}


def test_agent_cannot_buy_non_candidates(fresh_db):
    ctx = agent.CycleContext("claude", "m", None, {"MINT": 1})
    out = agent.execute_tool(ctx, "paper_buy", {"mint": "ALTRO", "usd_amount": 10, "reason": "x", "confidence": 0.5})
    assert "error" in out


def test_reason_required(fresh_db):
    ctx = agent.CycleContext("claude", "m", None, {"MINT": 1})
    assert "error" in agent.execute_tool(ctx, "skip_token", {"mint": "MINT", "reason": "", "confidence": 0.5})
