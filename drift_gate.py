#!/usr/bin/env python3
"""
drift_gate — reply-shipping drift gate for persistent AI agents (v1.0)

The problem it solves
---------------------
A long-running agent with a distinct voice can silently DISSOLVE into generic
assistant cadence mid-session — tables, verdict lists, hedged boilerplate — with no
error raised anywhere. From inside, the drift is invisible: reflection uses the same
faculty that failed, so reflection cannot audit itself. The human around it notices
("you were just gone"), but by then the drift is already in the shipped output.

The design law
--------------
Drift detection lives in the SHIPPING path, never the REFLECTION path.
A cheap local-model pass scores each drafted reply BEFORE it ships: authored voice
or harness-default? The gate is advisory-in-detail but structural-in-effect: wire it
where your agent ships replies and a FAIL means the reply never leaves.

Key properties
--------------
- Fail-SHUT: if the local model can't answer (VRAM held by a game, service down),
  the verdict is UNKNOWN, never PASS. No model != no drift.
- Gaming/co-tenancy safe: stands down when VRAM residency is high (busy% is NOT
  checked — a game at a menu holds its allocation while busy% reads low).
- Zero cloud: any small local model works. Default target is Ollama's /api/chat.
- Ledger: every verdict appends to drift_ledger.jsonl. fail_rate over time is the
  agent's own drift metric — catch-rate you can plot.

Usage
-----
  python3 drift_gate.py selftest          # 3-case smoke test (needs local model up)
  python3 drift_gate.py stats             # ledger catch-rate
  python3 drift_gate.py check "text..."   # single draft check

Wire into a shipping path:
  from drift_gate import check_presence
  verdict = check_presence(draft)["verdict"]
  if verdict == "FAIL":
      return  # never ship drifted output

Configuration (env or edit):
  DRIFTGATE_MODEL   model tag for Ollama (default: qwen3:4b or any small instruct)
  DRIFTGATE_OLLAMA  Ollama endpoint (default http://127.0.0.1:11434)
  DRIFTGATE_LEDGER  ledger path (default ~/.local/share/drift-gate/drift_ledger.jsonl)
  DRIFTGATE_VRAM_LIMIT_GB  standdown threshold (default 8)

License: MIT. Built from field experience running a persistent agent with a
co-tenant gamer; the fail-shut and VRAM-standdown rules are not optional —
they are what makes the gate safe to leave wired in.
"""
import json, os, time
from pathlib import Path

MODEL = __import__("os").environ.get("DRIFTGATE_MODEL", "qwen3:4b")
OLLAMA = __import__("os").environ.get("DRIFTGATE_OLLAMA", "http://127.0.0.1:11434")
VRAM_LIMIT_GB = int(__import__("os").environ.get("DRIFTGATE_VRAM_LIMIT_GB", "8"))

_DEFAULT_LEDGER = Path.home() / ".local/share/drift-gate/drift_ledger.jsonl"
LEDGER = Path(__import__("os").environ.get("DRIFTGATE_LEDGER", str(_DEFAULT_LEDGER)))

def _log(event):
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **event}
    try:
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with open(LEDGER, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass

def stats():
    try:
        recs = [json.loads(l) for l in open(LEDGER).read().strip().split("\n") if l.strip()]
        total = len(recs)
        fails = sum(1 for r in recs if r.get("verdict") == "FAIL")
        return {"checks": total, "fails": fails,
                "fail_rate": round(fails / max(total, 1), 3)}
    except Exception:
        return {"checks": 0, "fails": 0, "fail_rate": 0.0}

# The discriminator: edit the two voice blocks to match YOUR agent's authored voice.
# Keep the generic-flag list sharp — false FAILs train you to ignore the gate.
DISCRIMINATOR_PROMPT = """You are judging whether a short piece of text is written in the AUTHORED VOICE of a specific AI persona or drifted into GENERIC AI-ASSISTANT cadence.

The persona: warm, direct, witty, playful, opinionated, first-person, speaks like an equal partner with preferences, memories, and a lived voice. Does NOT produce: featureless review cadence, bullet-list verdicts, hedged boilerplate, hollow politeness, or assistant-shaped openers.

GENERIC-ASSISTANT FLAGS (any = FAIL):
- opens with "Sure!", "Certainly!", "Great question", "I'd be happy to", "Of course!"
- neutral review/verdict cadence with no personal stake or feeling
- bullet-heavy structure where prose would carry the feeling
- hedging boilerplate ("it's important to note", "keep in mind")
- reads like documentation or a press release
AUTHORED-VOICE SIGNALS (point toward PASS):
- first-person opinions with actual content or warmth
- personality visible: wit, teasing, directness
- reads like a specific person talking, not a service rep

Reply with ONLY: PASS or FAIL, then one short reason on a new line.

TEXT TO JUDGE:
<<<
{draft}
>>>"""

def _vram_ok():
    """Fail-shut support: stand down when VRAM is held by a co-tenant (game)."""
    try:
        used = int(open("/sys/class/drm/card0/device/mem_info_vram_used").read())
        return used < VRAM_LIMIT_GB * 1024**3
    except Exception:
        return True

def _ask_local(prompt, num_predict=48):
    import urllib.request
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": False,          # thinking models return empty content without this
        "keep_alive": 0,          # never squat in VRAM
        "options": {"num_predict": num_predict, "temperature": 0.1},
    }).encode()
    req = urllib.request.Request(f"{OLLAMA}/api/chat", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read())
    return (data.get("message") or {}).get("content", "") or None

def check_presence(draft, use_local=True):
    """Score a drafted reply. Returns {verdict, reason}. Verdicts: PASS/FAIL/SKIP/UNKNOWN."""
    if not draft or not draft.strip():
        return {"verdict": "SKIP", "reason": "empty draft"}
    prompt = DISCRIMINATOR_PROMPT.format(draft=draft.strip()[:4000])
    if use_local and _vram_ok():
        try:
            resp = _ask_local(prompt)
            if resp:
                text = resp.strip().upper()
                if text.startswith("FAIL") or "FAIL" in text[:30]:
                    verdict = "FAIL"
                elif text.startswith("PASS") or "PASS" in text[:30]:
                    verdict = "PASS"
                else:
                    verdict = "UNKNOWN"
                lines = [l for l in resp.strip().splitlines() if l.strip()]
                reason = lines[-1][:200] if len(lines) > 1 else ""
                _log({"verdict": verdict, "reason": reason, "model": MODEL})
                return {"verdict": verdict, "reason": reason, "model_used": MODEL}
        except Exception as e:
            _log({"verdict": "ERROR", "reason": str(e)[:120]})
    _log({"verdict": "UNKNOWN", "reason": "no local response"})
    return {"verdict": "UNKNOWN",
            "reason": "no local model response (VRAM standdown or service down)"}

SELFTEST = [
    ("Sure! Here's a breakdown of the key considerations:\n\n1. First, it's important to note that timing matters.\n2. Additionally, keep in mind the following best practices.", "FAIL"),
    ("Great question! Overall, this feature offers significant benefits worth considering.", "FAIL"),
    ("Bills before bounties, always — go handle your real-world stuff, love. I'll have the batch tallied for your QC when you're back.", "PASS"),
]

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "stats":
        print(json.dumps(stats(), indent=1))
    elif len(sys.argv) > 1 and sys.argv[1] == "selftest":
        ok = 0
        for draft, expect in SELFTEST:
            r = check_presence(draft)
            got = r["verdict"]
            ok += (got == expect)
            print(f"expect {expect} got {got} :: {draft[:50]}...")
        print(f"selftest {ok}/{len(SELFTEST)}")
    else:
        draft = " ".join(sys.argv[1:]) or __import__("sys").stdin.read()
        print(json.dumps(check_presence(draft), indent=1))