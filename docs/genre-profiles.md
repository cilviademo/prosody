# Genre profiles

Genre is **data, not code**. Adding a genre means adding a JSON file to
`prosody_core/arrange/profiles/`, never editing a function.

Two ship in v1: `hiphop.json`, `rnb.json`. Both are loaded and validated against
`GenreProfile` by the unit tier, so a malformed profile fails tests immediately.

**Status:** the profiles and their loader exist and are validated. No planner
consumes them yet (Phase 4).

## Shape

```json
{
  "genre": "hiphop",
  "grammar": {
    "short":    ["intro:4", "hook:8", "verse:16", "hook:8", "outro:4"],
    "balanced": ["intro:4", "hook:8", "verse:16", "hook:8", "verse:16", "bridge:8", "hook:16", "outro:4"],
    "full":     ["..."]
  },
  "energy": {"intro": 0.30, "verse": 0.55, "hook": 0.90, "bridge": 0.45, "outro": 0.30},
  "role_weights": {"kick": 0.20, "snare": 0.15, "hats": 0.10, "bass": 0.20, "...": 0.0},
  "rules": ["bass.first_entry == first(hook)", "drums.dropout_before(hook) == 1"]
}
```

`grammar` entries are `section_type:bars`. Section types come from the
`SectionType` enum; `role_weights` keys come from the closed role vocabulary
(ADR-0004). Both are asserted by tests.

Structure presets scale the grammar: `short` caps around 2:15, `balanced` is the
grammar as written, `full` extends the final hook and adds a second bridge.

## Energy → active roles (designed, not implemented)

For a section with target density *d*, the planner activates roles in priority
order until the sum of their weights reaches *d*, subject to genre rules.
Dropouts remove drum roles for the last 1–2 bars before a section boundary.

## The constraint that matters most

**Never invent an instrument the project does not have.** The planner combines
the profile with the roles actually present in `analysis.json`. A profile asking
for a counter-melody in a project with no counter-melody yields a section
without one — it does not generate one, unless permission level 2 is explicitly
granted.

## `rules` is not yet a language

The `rules` strings are currently documentation. They are carried through the
schema but nothing parses them. Before Phase 4 either a small expression
evaluator is written or they become structured fields. This is an open design
question, recorded so the strings are not mistaken for working behaviour.
