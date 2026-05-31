---
name: cleanup-dead-code
description: Dead Code Cleanup for TypeScript (using ts-prune, depcheck, and ESLint)
---

1. Run dead code analysis and present the report:

   **Unused exports** — `npx ts-prune --skip "*.d.ts" | grep -v "(used in module)"`:
   - Group by file, show export names and types (functions, classes, types, constants)
   - Largest files first
   - Flag potential false positives (barrel re-exports, framework entry points, declaration files, dynamic imports)

   **Unused dependencies** — `npx depcheck --ignores="@types/*"`:
   - List unused dependencies and devDependencies
   - List missing dependencies (imported but not in package.json)
   - Flag false positives (dependencies used in config files, scripts, or build tooling)

   **Unused imports/variables** — `npx eslint . --rule '{"@typescript-eslint/no-unused-vars": "warn", "no-unused-imports/no-unused-imports": "warn"}' --no-fix`:
   - Group by file
   - Distinguish unused imports from unused local variables

2. After I approve, remove dead code automatically (no per-edit confirmation):
   - Work file-by-file in small batches
   - Show clear diffs for each edit
   - Preserve formatting, comments, JSDoc, and structure
   - Keep barrel exports (`index.ts`) intact unless the underlying export is also removed
   - Skip anything flagged as a potential false positive unless obviously safe

3. Run `npx eslint . --fix --rule '{"@typescript-eslint/no-unused-vars": "error", "no-unused-imports/no-unused-imports": "error"}'` to auto-fix remaining unused imports

4. Run `npx depcheck` again and suggest removing any confirmed unused packages from `package.json`

**Safety rules:**

- Never break public APIs, barrel exports, or tests
- Account for dynamic imports (`import()`) and framework conventions (e.g., Next.js page exports, NestJS decorators)
- Respect `.d.ts` declaration files — these define types for consumers and may appear unused locally
- Suggest `git stash` before large changes
