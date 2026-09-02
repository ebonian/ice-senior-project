# The discovery loop — one cycle, exactly

> Sibling of the experiment loop ([`../loop/`](../loop/PROTOCOL.md)). The experiment loop **verifies**; this loop **decides what is worth verifying**. It institutionalizes the pattern the operator's Kaufman-ER contribution demonstrated — start from the constraint, research outward, come back with mechanisms — so that hypothesis generation doesn't wait on the operator. One cycle = harvest → binding constraint → external research → ranked memo → handoff. This loop never runs experiments, never edits the engine, and never touches capital.

To run a cycle: start a session in this repo and say **"run one discovery cycle"**. This file is the procedure.

## 0 · Orient

Read [`CONSTRAINTS.md`](CONSTRAINTS.md), [`BACKLOG.md`](BACKLOG.md), and the last ~10 rows of [`../loop/LEDGER.md`](../loop/LEDGER.md). Any experiment verdict that landed since the last cycle gets harvested first — a cycle that ignores a fresh falsification will re-propose it.

## 1 · Harvest — every verdict changes the constraint map

For each new verdict in the experiment loop:

- A **REFUTED** hypothesis is a new constraint (E007 → "per-hour threshold rules cannot buy contiguity: 0/540 configs positive"). Falsifications are the most durable facts this project produces.
- A **SUPPORTED** bound sharpens numbers (E006 → ceiling +$6.06/day, capture bar 6.4%).
- An **INCONCLUSIVE** verdict records what would disambiguate — that is itself a candidate research question.

Update the touched hypothesis cards in `BACKLOG.md` (status + outcome link) and the rows in `CONSTRAINTS.md`. Every constraint carries **numbers, a source link, and a status** (BINDING / INFORMATIVE / RETIRED).

## 2 · Pick the binding constraint

Name the **single** constraint that currently blocks the goal, and say why it and not another. If no constraint is both binding and researchable, the cycle ends here: either the goal is met, or the block is an operator decision — say which, and stop.

## 3 · Research outward

Time-boxed external research on the binding constraint: literature, practitioner methods, and cross-domain analogues (inventory control, market-making, regime-switching, optimal stopping — whatever the constraint rhymes with). Web search encouraged. **Cite everything** — a memo whose claims can't be chased is a memo the next cycle can't trust. Record what was searched for and **not** found; absence is a finding.

The bar, always: domain knowledge in, testable mechanism out.

## 4 · Write the memo — `memos/M<NNN>-<slug>.md`

Three sections, in order:

1. **Constraints** — restated with the numbers that define them, pulled from `CONSTRAINTS.md` (not from memory).
2. **External research** — what was found, with citations; what was looked for and not found.
3. **Ranked candidates** — each with its **mechanism** (why it should move the binding constraint), data needs, **expected effect size against the constraint's numbers**, and what result would falsify it.

The ranked list is the multiple-comparisons guard: a downstream experiment may test **only pre-named candidates**. Commit the memo before any experiment pre-registers against it; once cited by a pre-registration, the memo is append-only.

## 5 · Handoff — hypothesis cards

Each candidate worth testing becomes (or updates) a card in `BACKLOG.md`: claim, memo source, expected effect, cost to test, status. Lifecycle:

**PROPOSED → STAGED** (operator or loop picked it) **→ E<NNN>** (running) **→ SUPPORTED / REFUTED / DROPPED**

The experiment loop pre-registers from the card + memo ([`../loop/PROTOCOL.md`](../loop/PROTOCOL.md) §1); its verdict flows back through §1 of this loop. The card is the interface — neither loop reaches into the other's files beyond it.

## 6 · Stop conditions

- No binding researchable constraint → stop (goal met, or an operator decision is the blocker — name it).
- A memo would restate a previous memo's candidates → the family is structurally stuck; **ESCALATE** to the operator rather than re-ranking the same list.
- Three consecutive cycles whose candidates all die in the experiment loop → the next cycle must research a **different constraint**, not deeper on the same one.

## House rules

- This loop proposes; it never runs experiments. Verification lives in `../loop/`.
- Constraint numbers come from experiment artifacts with links — this loop repeats no live number without an anchor (bot repo single-source rule).
- Discovery cycles are deep-analysis work (opus/fable tier), not scouting.
