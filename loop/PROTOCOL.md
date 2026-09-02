# The research loop — one iteration, exactly

> An agent session (or a human) runs **one iteration at a time** of hypothesis → change → test → verdict → critique. The loop's memory is [`LEDGER.md`](LEDGER.md) and the experiment files — not the session. If it isn't written down, the next iteration doesn't know it happened.

To run an iteration: start a session in this repo and say **"run one research-loop iteration"**. This file is the procedure.

## 0 · Orient

Read [`GOAL.md`](GOAL.md), the last ~10 rows of [`LEDGER.md`](LEDGER.md), and any RUNNING or OPEN review (R-numbered) entries. If a review is open, resolving it **is** the iteration.

## 1 · Hypothesize — pre-register before touching code

**When the family is new, or the family's obvious hypotheses are exhausted, the hypothesis comes from the discovery loop** ([`../discovery/PROTOCOL.md`](../discovery/PROTOCOL.md)) — run a discovery cycle there first. That loop harvests constraints from this ledger's verdicts, researches the binding one externally, and hands back a memo (`../discovery/memos/M<NNN>-<slug>.md`) plus a hypothesis card in [`../discovery/BACKLOG.md`](../discovery/BACKLOG.md). The memo's ranked list becomes this experiment's **pre-named candidate set** — naming candidates before testing is also the multiple-comparisons guard. Commit the memo before pre-registering here; once cited, the memo is append-only. (The operator's Kaufman-ER contribution is the pattern the discovery loop institutionalizes: domain knowledge in, testable hypothesis out.)

Then create `experiments/E<NNN>-<slug>.md` from [`experiments/TEMPLATE.md`](experiments/TEMPLATE.md) and fill in, BEFORE running anything:

- **Hypothesis** — one falsifiable claim. "Wider ranges net more after IL" is testable; "improve the model" is not.
- **The one variable** — exactly one thing changes vs. a named baseline (the bot repo's one-variable-per-trial rule applies here too).
- **Decision rule** — what result counts as SUPPORTED and what as REFUTED, with thresholds, written down before the run. Moving this goalpost after seeing results is the cardinal sin of this loop.
- **Abort criteria** — what stops the run early.

Add the LEDGER row with verdict RUNNING.

## 2 · Run

The smallest experiment that can falsify the hypothesis. Fixed seeds; exact checkpoint/config paths recorded in the experiment file; artifacts under the experiment's own directory (or the simulation dir it extends — link it). An experiment that grows into a full training run becomes `research/simulation_N+1` per repo convention; the E-file then wraps and links it.

## 3 · Judge

Compare the result against the pre-registered decision rule — nothing else. Wanting a different metric after seeing the data = a new experiment.

Verdicts: **SUPPORTED / REFUTED / INCONCLUSIVE** (INCONCLUSIVE must say what would disambiguate). REFUTED is a first-class result — record it with the same care; falsifications are how this project stops re-proposing dead ends.

## 4 · Record

Fill the Result/Verdict/Critique sections, update the LEDGER row, update GOAL.md's "Current focus" if the verdict changes it, and commit. Anything the bot repo must act on also gets recorded in `bot/docs/` (tracker / issues / decisions) — this ledger is not visible from there.

## 5 · Critique — every iteration, in the experiment file

One honest line each:

1. Did I optimize the proxy or the goal? (env reward vs. net PnL under honest costs)
2. Would this survive Gate 2 — real costs, real funding, IL? (the bot repo's backtest engine is the arbiter)
3. Is the environment still faithful enough for this claim? (the hedge leg is frictionless — signal-only)
4. Did exactly one variable change?
5. Is this iteration a symptom-fix of the previous one?

## 6 · Step back when it's whack-a-mole

**Trigger (mandatory, not a judgment call):** 3 consecutive REFUTED/INCONCLUSIVE verdicts in the same hypothesis family, OR critique question 5 answered "yes" twice in a row.

The next iteration is then a **review, not an experiment**: create `experiments/R<NNN>-<slug>.md`:

- Restate the goal and what the failing family assumed.
- List the family's experiments and the pattern in their failures.
- Enumerate **≥ 2 structurally different alternatives** — a different family, not another tweak.
- Verdict: **PIVOT** to a named alternative, **PERSIST** with a stated reason, or **ESCALATE** to the operator with a concrete question.

Tells that you're in whack-a-mole before the trigger fires: each fix creates the next symptom; the metric plateaus while complexity rises; you cannot state what would falsify the family as a whole.

## 7 · Stop conditions

End the **loop** (not just the iteration) when any of these hit — never loop past them:

- The current GOAL sub-goal is met → write a closing summary under "Closed sub-goals" in the LEDGER and stop.
- A decision needs the operator (capital, live trials, target changes, promoting a model to serving) → ESCALATE and stop.
- A review would repeat its own previous verdict — the loop is structurally stuck → ESCALATE.

## House rules that bind here

- Simulations stay append-only; published numbers stay reproducible.
- Training-env numbers are never quoted as live profitability.
- Promotion to serving follows `UPLOAD_MODEL.md` + a bot-repo decision entry — never from inside the loop alone.
