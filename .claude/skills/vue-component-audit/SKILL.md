---
name: vue-component-audit
description: Analyze Vue 3 component structure and suggest performance and code-reuse optimizations. Use when asked to audit, review or optimize Vue components, find duplicated code or styles across components, or check list rendering and bundle splitting in client/src.
---

# Vue component audit

`analyze.py` scans `.vue` files and reports candidates for performance and reuse fixes. It is a text-based heuristic, not a Vue compiler: every finding must be confirmed by reading the flagged code before it is reported or acted on.

## Run

```bash
python3 .claude/skills/vue-component-audit/analyze.py client/src
python3 .claude/skills/vue-component-audit/analyze.py client/src/views/Dashboard.vue --json
```

Paths can be files or directories. `--limit N` raises the per-section cap in text output. `--json` gives every finding with `group`, `severity`, `file`, `line`, `kind`, `message`.

## Finding kinds

Performance:

| kind | meaning | confirm by reading |
|---|---|---|
| `v-for-key`, `v-for-index-key` | missing key, or key is the loop index | whether the list can reorder, insert or delete after render; on a list fixed after load an index key is harmless, say so |
| `v-if-with-v-for` | both on one element | whether a computed filter replaces the `v-if` |
| `list-in-template` | the iterated list is built by a call in the template | move it to a computed; if the same call also appears in `.length` checks, one computed serves all |
| `method-in-loop` | a function that scans an array runs once per row | precompute a lookup (Map by key) in a computed |
| `plain-calls-in-loop` | functions called per row | informational; only matters for large lists |
| `deep-watch` | `deep: true` watcher | whether a narrower source suffices |
| `eager-route` | router imports a view eagerly | `() => import('./views/X.vue')` splits it out of the first bundle |

Reuse:

| kind | meaning | confirm by reading |
|---|---|---|
| `large-template`, `large-script` | past the 100 / 150 line limits in `client/CLAUDE.md` | look for repeated markup or a composable candidate |
| `duplicate-function` | identical body in several files | extract to `client/src/utils/` or a composable |
| `diverged-function` | same utility name, different bodies | whether the difference is intended or drift |
| `duplicate-style`, `shared-styles` | identical CSS rules repeated across components | a shared base component (e.g. one modal shell) or stylesheet |

## Reporting

1. Run the analyzer, then read the code behind the highest-impact findings: `warn` first, and for style duplication the file pairs with the largest rule counts.
2. Drop false positives and say why. Keep the rest.
3. Rank by payoff: removing hundreds of duplicated lines or a quadratic scan beats a missing key on a six-row table.
4. For each kept finding give file:line, the evidence, the concrete change, and the risk (for example, a shared modal shell touches every modal and needs a visual check).
5. Do not edit files as part of the audit. Applying fixes is a separate step, and `.vue` edits go through the `vue-expert` agent per the project rules.

## Limits

- Brace and tag matching is textual. Unusual formatting, multi-line attribute values and dynamic components can hide or invent findings.
- Style comparison is exact after whitespace and case normalisation, so near-duplicate rules are not matched.
- It does not measure runtime cost. A performance claim that matters needs a profile or a measured render count.
- `<script setup>` and Options API are both read as plain text. Functions are found as `const x = () =>` and `function x()` declarations only.
