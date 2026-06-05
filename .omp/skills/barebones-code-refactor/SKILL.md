---
name: barebones-code-refactor
description: Performs a conservative repo-wide refactor driven by objective checks: formatters, linters, typecheckers, tests, dead-code reports, complexity/size hotspots, duplication, dependency hygiene, and small mechanical splits of oversized files or functions. Use when asked to do a broad cleanup/refactor without changing product behavior.
license: MIT
metadata:
  domain: quality
  role: refactoring
  scope: repository
  triggers: barebones refactor, repo cleanup, code cleanup, mechanical refactor, split giant files, reduce complexity
---

# Barebones Code Refactor

Conservative whole-repo cleanup that improves maintainability without changing behavior. Prefer objective, tool-supported changes over speculative redesign.

## Definition of "Barebones"

Included:

- Formatter/linter fixes using the repo's configured tools.
- Import cleanup, unused variables, unreachable code, trivial dead code.
- Typecheck errors where the correct fix is local and obvious.
- Test failures caused by stale expectations or cleanup changes.
- Oversized files/functions/classes split along existing boundaries.
- High-complexity functions simplified by extracting named helpers, guard clauses, or removing duplication.
- Duplicate code collapsed only when callsites already share the same concept.
- Dependency/package hygiene: unused dependencies, stale scripts, duplicate config, broken entry points.
- Repository hygiene: generated/cache artifacts accidentally tracked, obsolete aliases/re-exports, dead config.
- Documentation comments or README snippets only when they become inaccurate because of the refactor.

Excluded unless explicitly requested:

- Product behavior changes.
- Framework/library migrations.
- Public API redesigns.
- New architecture layers or abstractions.
- Performance rewrites that need benchmarking to justify.
- Style changes not enforced by configured tooling.
- Test rewrites that change what behavior is asserted.

## Core Workflow

1. **Establish baseline**
   - Read repo instructions and package/tooling config.
   - Identify languages, package managers, test runners, formatters, linters, typecheckers, and complexity/dead-code tools already present.
   - Run existing fast checks first. Do not add new tools until repo-native checks are understood.
   - Record failing baseline checks separately from failures introduced by edits.

2. **Run objective scans**
   - Format/lint/typecheck/test with configured commands.
   - Locate oversized files and symbols with language-aware tools where available.
   - Locate dead code using project-appropriate tools when already available, or lightweight static checks when not.
   - Locate duplicate code only when a configured tool exists or a simple script can report exact/near-exact repeated blocks.
   - Inspect dependency metadata for unused scripts, duplicate config, and obviously unused packages.

3. **Prioritize safe changes**
   - Fix formatter/linter/import issues first.
   - Remove code proven unused only after checking references and dynamic entry points.
   - Split giant files by moving cohesive private helpers/classes into existing or clearly named neighboring modules.
   - Split giant functions by extracting local, side-effect-preserving helpers with narrow inputs and return values.
   - Reduce branching with guard clauses only when it makes control flow simpler and preserves order of side effects.
   - Consolidate duplication only when naming the shared helper makes the domain clearer.

4. **Edit in small batches**
   - Keep public names stable. If an exported symbol must move, update all imports with LSP/code-aware tooling.
   - Prefer moving code over rewriting it.
   - Preserve comments that explain intent; delete comments that only restate removed code.
   - Do not introduce compatibility aliases unless required for a public API and explicitly justified.
   - Do not create broad utility modules like `helpers`, `common`, or `utils` unless the repo already uses that pattern.

5. **Verify after each batch**
   - Run the narrowest relevant tests/checks after a batch.
   - Re-run formatter/linter/typecheck after mechanical edits.
   - Run full repo checks before finishing when feasible.
   - If a baseline failure remains, report it as pre-existing only if observed before edits.

## Refactor Heuristics

### Oversized files

Split a file when it contains multiple independently named concepts, such as:

- CLI parsing mixed with business logic.
- Data models mixed with I/O.
- Test fixtures mixed with unrelated test cases.
- Multiple components/classes that are imported independently.

Do not split solely because a file exceeds a line count if it is cohesive and generated-like.

### Oversized functions

Extract when the function has a named phase that can be tested or reasoned about independently:

- Parse/validate/transform/apply/report phases.
- Repeated condition blocks.
- Deeply nested branches with a clear predicate.
- Long setup code obscuring the main behavior.

Avoid extraction when it would require passing many mutable values, hide critical ordering, or create a one-use helper with a vague name.

### Dead code

Safe removals usually include:

- Unused private functions/classes/variables confirmed by references.
- Unused imports and unreachable branches reported by tooling.
- Obsolete config/scripts not referenced by package metadata, CI, docs, or tests.

Treat these as risky and verify before removal:

- Public exports.
- CLI commands and plugin entry points.
- Framework hooks, migrations, serializers, signal handlers, route handlers.
- Reflection/dynamic imports/string-based references.
- Test fixtures discovered by naming convention.

### Duplication

Consolidate duplication only when:

- Blocks are semantically the same, not just textually similar.
- Shared helper name is more specific than the duplicated code.
- Error handling and side effects remain identical.
- Callers do not need extra flags to recover old behavior.

Leave duplication in place when abstraction would introduce boolean parameters, callback plumbing, or unclear ownership.

## Tool Selection

Use repo-native tools first. Common examples:

- JavaScript/TypeScript: `npm`/`pnpm`/`yarn` scripts, ESLint, Prettier, `tsc --noEmit`, Vitest/Jest/Playwright.
- Python: Ruff, Black, mypy/pyright, pytest, Vulture.
- Rust: `cargo fmt`, `cargo clippy`, `cargo test`.
- Go: `gofmt`, `go vet`, `go test`.
- .NET: `dotnet format`, analyzers, `dotnet test`.

If no configured tool exists, prefer read-only analysis and small local scripts over adding new dependencies. Ask before adding dependencies or changing tool configuration.

## Safety Rules

- Preserve external behavior unless the user explicitly approves a behavior change.
- Never suppress diagnostics to make checks pass.
- Never remove public APIs without reference checks and an explicit compatibility decision.
- Never perform broad text renames when LSP/code-aware renames are available.
- Never mix mechanical formatting with semantic refactors in the same edit batch when avoidable.
- Never introduce speculative abstractions.
- Never leave moved code duplicated in old locations.

## Output

Final response must include:

1. What objective checks were run and their results.
2. What categories of changes were made.
3. Any files/functions split and why those boundaries were chosen.
4. Any pre-existing failures that remain, with the command output summary.
5. Any deliberately skipped risky findings and why.
