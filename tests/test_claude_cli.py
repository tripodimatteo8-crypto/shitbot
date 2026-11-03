"""Backend abbonamento (CLI `claude -p`) con subprocess finto."""
import json
from types import SimpleNamespace as NS

import pytest

from solbot import agent, claude_cli
from solbot.config import env
from solbot.db import Candidate, ClaudeUsage, Decision, Position, Snapshot, session_scope
from solbot.portfolio import ensure_account


def cli_stdout(structured, is_error=False, result="ok"):
    return json.dumps({
        "type": "result", "is_error": is_error, "result": result, "structured_output": structured,
        "total_cost_usd": 0.12, "usage": {"input_tokens": 9000, "output_tokens": 400},
        "modelUsage": {"claude-opus-5-5": {}},
    })


@pytest.fixture()
def fake_cli(fresh_db, monkeypatch):
    calls = []
    state = {"stdout": cli_stdout({"decisions": []}), "rc": 0, "stderr": ""}

    def fake_run(cmd, input, capture_output, text, cwd, env, timeout):
        calls.append({"cmd": cmd, "input": input, "env": env})
        return NS(stdout=state["stdout"], returncode=state["rc"], stderr=state["stderr"])

    monkeypatch.setattr(claude_cli, "cli_path", lambda: "/usr/bin/claude")
    monkeypatch.setattr(claude_cli.subprocess, "run", fake_run)
    monkeypatch.setattr(claude_cli, "_paused_until", None)
    monkeypatch.setattr(claude_cli, "_last_call", None)
    monkeypatch.setattr(env, "anthropic_api_key", None)
    monkeypatch.setattr(env, "decider", "auto")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "non-deve-passare")
    return NS(calls=calls, state=state)


def test_auto_uses_subscription_without_key(fake_cli):
    assert agent.choose_decider() == "claude_cli"


def test_parse_output_from_result_text():
    out = claude_cli.parse_output(json.dumps({"is_error": False, "result": '```json\n{"decisions": []}\n```'}))
    assert out["structured"] == {"decisions": []}


def test_cli_cycle_executes_decisions(fake_cli):
    fake_cli.state["stdout"] = cli_stdout({
        "decisions": [
            {"mint": "MINT", "action": "buy", "usd_amount": 30, "reason": "volume e holder ok", "confidence": 0.62},
            {"mint": "MINT2", "action": "skip", "reason": "già +200% in 1h", "confidence": 0.8},
            {"mint": "ESTRANEO", "action": "buy", "usd_amount": 30, "reason": "x", "confidence": 0.9},
        ],
        "sells": [],
        "summary": "1 acquisto, 1 skip",
    })
    with session_scope() as s:
        ensure_account(s)
        for m, p in (("MINT", 0.001), ("MINT2", 0.002)):
            s.add(Snapshot(mint=m, price_usd=p, liquidity_usd=50_000))
            s.add(Candidate(mint=m, symbol=m, price_usd=p, liquidity_usd=50_000, passed_filters=True, status="pending", features={}))
    res = agent.run_cycle()
    assert res["decider"] == "claude_cli" and res["decided"] == 2
    call = fake_cli.calls[0]
    assert "ANTHROPIC_API_KEY" not in call["env"]  # usa l'abbonamento, non l'API
    assert call["cmd"][call["cmd"].index("--tools") + 1] == ""  # nessuno strumento
    assert "--json-schema" in call["cmd"]
    assert "MINT2" in call["input"]
    with session_scope() as s:
        decs = {d.mint: d for d in s.query(Decision).all()}
        assert decs["MINT"].action == "buy" and decs["MINT"].decider == "claude_cli"
        assert "ESTRANEO" not in decs  # non era un candidato: ignorato
        assert s.query(Position).count() == 1
        u = s.query(ClaudeUsage).one()
        assert u.purpose == "decision_cli" and u.input_tokens == 9000


def test_quota_and_spacing(fake_cli):
    claude_cli.run("x", "s", None, "decision_cli")
    ok, why = claude_cli.can_call()
    assert not ok and "prossima chiamata" in why  # distanza minima tra chiamate
    from solbot.config import invalidate_cache
    from solbot.db import Setting

    with session_scope() as s:
        s.add(Setting(key="cli_calls_per_window", value="1"))
    invalidate_cache()
    ok, why = claude_cli.can_call(min_spacing=False)
    assert not ok and "quota" in why


def test_limit_reached_pauses(fake_cli):
    fake_cli.state.update(stdout=cli_stdout(None, is_error=True, result="Claude usage limit reached. Your limit will reset at 2am"), rc=1)
    assert claude_cli.run("x", "s", None, "decision_cli") is None
    ok, why = claude_cli.can_call(min_spacing=False)
    assert not ok and "pausa" in why


def test_reflection_via_cli(fake_cli, tmp_path):
    from solbot import reflection

    fake_cli.state["stdout"] = cli_stdout({"lessons_md": "# Lezioni\n\n- [ipotesi, n=3] regola di prova con abbastanza testo per essere salvata"})
    vid = reflection.reflect("periodic")
    assert vid is not None
    assert "regola di prova" in env.lessons_path.read_text()
