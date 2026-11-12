# ADR-0008: Deadline engine as pure, explainable rules

- Status: Accepted
- Date: 2026-11-12

## Context
Brief rule 5: deadlines are proposals with visible reasoning and are never final without
a lawyer. A wrong date is the most damaging error this product can make, and the rules
(CPC, CLT, Juizados) have not been checked by a lawyer yet (VERIFY DL-1 to DL-12).

## Decision
- `legalos.deadlines.engine` is a set of pure functions: no database, no clock. Input is
  the triggering event, the rule set, the number of days and a map of holidays; output is
  a proposed date plus every step of the reasoning in Portuguese.
- No AI is involved in the calculation.
- Every rule cites its legal article next to the code, and the same citation is shown
  to the user in the reasoning.
- Holidays are data. Only fixed-date national holidays ship with the system; movable
  dates (Carnaval, Sexta-feira Santa, Corpus Christi), state/municipal holidays and court
  suspensions are suggested or typed in and must be confirmed by the firm.
- A proposal becomes a deadline only when a user with `confirm_deadlines` (sócio or
  advogado) confirms it. Confirming a different date requires a written justification.
  Confirmation creates a task; rejection creates nothing.

## Consequences
- The engine is easy to test exhaustively (dates in, dates out) and easy for a lawyer to
  review: the reasoning on screen is the specification.
- A holiday missing from the calendar produces a date that is too **early** (safe
  direction). A wrongly added holiday produces a date that is too late; that is why
  holidays are never added silently.
- Rules that depend on facts the system does not know (who the parties' lawyers are,
  whether the case is electronic, local court acts) stay as explicit user choices.

## Alternatives considered
- Letting the AI read the intimação and compute the date: not explainable, not testable.
  The AI may later *suggest* the inputs (event date, kind of deadline); the engine still
  computes, and the lawyer still confirms.
- A third-party deadline API: none verified; would move the liability without removing it.
