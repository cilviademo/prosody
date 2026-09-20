# ADR-0002: Ship a compatibility shim for PyFLP on Python >= 3.11

Date: 2026-09-20
Status: Accepted
Supersedes: the Python 3.12 requirement in CLAUDE.md (kept, now viable)

## Context

**Measured in Phase 0: PyFLP 2.2.1 cannot parse any `.flp` file on Python 3.11,
3.12 or 3.13.** This includes the Python 3.12 that CLAUDE.md mandates.

PyFLP resolves every event id with `EventEnum(id)`. `EventEnum` declares no
members of its own; the right member lives on a subclass (`ProjectID`,
`ChannelID`, …) and is found by `EventEnum._missing_`. CPython 3.11 added a
guard to `Enum.__new__`:

```python
# still not found -- verify that members exist, in-case somebody got here mistakenly
if not cls._member_map_:
    raise TypeError("%r has no members defined" % cls)
```

It runs *before* `_missing_`. Parsing dies on the first event of every file —
id 199, `FLVersion`, which is present in every real project.

Measured:

| Python | `EventEnum(199)` |
| --- | --- |
| 3.10.20 | `ProjectID.FLVersion` (PyFLP also enables `fastenum` below 3.11) |
| 3.11.15 | `TypeError: <enum 'EventEnum'> has no members defined` |
| 3.12.3 | `TypeError: <enum 'EventEnum'> has no members` |
| 3.13.12 | guard present, same failure |

PyFLP 2.2.1 is the latest release on PyPI; there is no fixed version to upgrade to.

Options:

1. **Pin Python 3.10.** Works today with no patching. But 3.10 reaches
   end-of-life in October 2026, it contradicts the spec, and it relies on
   `fastenum` monkeypatching `enum` — a second-order fragility, not a fix.
2. **Vendor a patched PyFLP fork.** Takes on maintenance of a 9,000-line parser
   to change three lines.
3. **Seed one sentinel member so `_missing_` is reached.** Four lines, in our
   code, reversible.
4. **Abandon PyFLP.** Disproportionate; the library is otherwise correct, as
   the 217-test unit tier against real FLP binaries shows.

## Decision

Option 3. `flpfinisher/parse/_pyflp_compat.py` seeds `EventEnum._member_map_`
with a single sentinel whose value is `-1` — outside the 0–255 range an event id
can occupy. The guard then passes and `_missing_` runs exactly as upstream
intends. `_member_names_` is left untouched, so `list(EventEnum)`, iteration and
member `repr` are unchanged.

`apply()` is idempotent, returns whether it did anything, and is reported by
`flpf doctor` so the shim is never invisible.

## Consequences

- Python 3.10 through 3.13 all work. `requires-python` is `>=3.10`; 3.12 is the
  supported target, matching CLAUDE.md.
- We depend on two PyFLP internals: `EventEnum._member_map_` and the fact that
  `_missing_` searches subclasses. Both are asserted directly by
  `tests/unit/test_pyflp_compat.py`, so an upstream change fails the unit tier
  loudly rather than corrupting a parse.
- **Retirement path:** if PyFLP fixes this upstream, `apply()` returns `False`
  and becomes a no-op. No code needs removing; the tests keep passing. This
  should be contributed upstream.
- The shim touches no parsing logic, so it cannot change what is parsed — only
  whether parsing runs at all.

## Verification

`tests/unit/test_pyflp_compat.py` proves: the guard exists on this interpreter,
known ids resolve to the correct subclass member, unknown ids still become
pseudo-members (so unknown events are preserved per EXECUTE.md T1), public enum
iteration is unchanged, `apply()` is idempotent, and the sentinel value cannot
collide with a real id.
