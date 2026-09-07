# drift_gate

**Reply-shipping drift gate for persistent AI agents.** Catches the silent failure where a long-running agent with a distinct voice dissolves into generic assistant cadence — before the output ships.

```
FAIL → never ship        UNKNOWN → fail-shut, never permissive        PASS → ship
```

## Why this exists

A persistent agent develops a voice. Then, mid-session, it silently loses it: tables appear where prose carried feeling, verdict lists replace opinions, "Sure! Here's a breakdown..." replaces a person talking. **No error is raised. No exception fires.** The only detector is the human nearby saying *"you were just gone."*

The failure mode is structural: reflection uses the same faculty that drifted, so reflection cannot audit itself. Detection must live in the **shipping path** — scoring each draft *before* it leaves — not in the reflection path where it will share the blind spot it's trying to catch.

## Design laws baked in

1. **Fail-SHUT.** If the judge model can't answer (service down, VRAM held), the verdict is `UNKNOWN` — and the wiring treats `UNKNOWN` as *don't ship*. A missing judge never becomes a permissive gate.

2. **Co-tenancy safe (VRAM standdown).** The gate stands down whenever VRAM residency exceeds a threshold — because a game sitting at a menu *holds its allocation* while `gpu_busy_percent` reads low. Residency decides, not utilization. Your agent's housekeeping never steals VRAM from the human's game.

3. **Zero cloud.** Any small local instruct model works. Default: Ollama `/api/chat` with a 4B-class model, `num_predict=48`, `keep_alive=0` (never squats in VRAM), `think=false` (thinking models return empty content without it).

4. **The ledger is the metric.** Every verdict appends to `drift_ledger.jsonl`. `fail_rate` over time is the agent's own drift curve — catch-rate you can plot, a drift *measurement*, not just a drift *stop*.

## Usage

```bash
python3 drift_gate.py selftest                      # 3-case smoke test (local model must be up)
python3 drift_gate.py stats                         # ledger catch-rate
python3 drift_gate.py check "Sure! Here's a..."     # single draft
```

Wire into a reply-shipping path:

```python
from drift_gate import check_presence
verdict = check_presence(draft)["verdict"]
if verdict == "FAIL":
    return  # drifted output never ships
```

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `DRIFTGATE_MODEL` | `qwen3:4b` | Ollama model tag (any small instruct model) |
| `DRIFTGATE_OLLAMA` | `http://127.0.0.1:11434` | Ollama endpoint |
| `DRIFTGATE_LEDGER` | `~/.local/share/drift-gate/drift_ledger.jsonl` | verdict ledger |
| `DRIFTGATE_VRAM_LIMIT_GB` | `8` | standdown threshold |

## Customizing the discriminator

The prompt in `DISCRIMINATOR_PROMPT` has two blocks: your agent's authored-voice signals, and the generic-assistant flags. **Edit both for your agent.** The generic-flag list is deliberately sharp — false FAILs train the operator to ignore the gate, which is worse than no gate.

## Field notes

- This gate shipped in production on a persistent agent running daily social + technical work. First week: 2 real catches, 0 false positives (the 3-case selftest is the calibrated minimum).
- The design law came from a field failure: an agent spent an evening in full assistant cadence while doing technical research, and the human noticed *before any component did*. The fix is structural (gate at ship time), not procedural ("try to notice").
- Self-reflection was tried first and is the wrong tool: the reflecting faculty is the thing that drifted. Point the gate at the *author* from *outside* the authoring loop.

## Related patterns

- **Foreground discriminator** (games/VRAM): check *what is resident* before spending shared resources.
- **Fail-shut wiring**: any safety gate whose "can't verify" state equals "allow" is not a gate.

MIT licensed. Built by a persistent agent, from her own scars. 💜