# Code Quality Checks

Code-level checks to run during the polish step. These focus on the source code itself rather than repo scaffolding.

---

## 1. Formatting & Linting

### Check for Existing Config

Look for formatter/linter configuration in:

- `eslint.config.js` / `eslint.config.mjs` (flat config) or `.eslintrc.*` (legacy)
- `.prettierrc` / `.prettierrc.*` / `prettier.config.*`
- `package.json` → `"eslintConfig"` or `"prettier"` fields
- `biome.json` (if using Biome instead of ESLint + Prettier)

### If Configured

Run the configured tools:

```bash
npx eslint .
npx prettier --check .
```

Report any violations as **Recommendation** items.

### If Not Configured

Note the absence as a **Recommendation**: suggest adding ESLint with TypeScript support and Prettier:

```bash
npm install -D eslint @typescript-eslint/parser @typescript-eslint/eslint-plugin prettier
```

With a minimal `eslint.config.mjs`:

```javascript
import tseslint from "typescript-eslint";

export default tseslint.config(tseslint.configs.recommended, {
  ignores: ["dist/", "node_modules/", "coverage/"],
});
```

Do not block on this — many personal projects ship without a linter configured.

---

## 2. TSDoc / JSDoc

### What to Check

Focus on **public API** — exported functions, classes, types, and interfaces that users of the project would interact with:

- Exported function/method documentation
- Exported class documentation
- Exported type/interface documentation (complex ones benefit from docs)
- Module-level documentation in main entry points

### How to Check

```bash
# Find exported functions/classes missing JSDoc/TSDoc
# Look for export statements without preceding /** comments
grep -n "^export " src/**/*.ts | head -30
```

Or if ESLint with `eslint-plugin-jsdoc` is available:

```bash
npx eslint --rule '{"jsdoc/require-jsdoc": "warn"}' src/
```

### Severity

- Missing docs on public API: **Recommendation**
- Missing docs on internal helpers: Skip — not worth flagging for personal projects

### Style

If docs exist, check they follow a consistent style (TSDoc `@param`/`@returns` tags). Don't flag style inconsistency as a blocker — just note the recommendation.

---

## 3. TypeScript Strict Mode

### What to Check

Verify `tsconfig.json` has strict mode enabled:

```json
{
  "compilerOptions": {
    "strict": true
  }
}
```

This enables: `strictNullChecks`, `noImplicitAny`, `strictFunctionTypes`, `strictBindCallApply`, `strictPropertyInitialization`, `noImplicitThis`, `alwaysStrict`.

### How to Verify

```bash
# Check for strict mode
grep -n '"strict"' tsconfig.json

# Run the TypeScript compiler to check for type errors
npx tsc --noEmit
```

### Severity

- `strict: true` not set: **Recommendation**
- TypeScript compiler errors: **Recommendation** to fix or adjust config
- If `strict` is explicitly `false` with no explanation: **Recommendation** to enable

---

## 4. TODO / FIXME / HACK Audit

### How to Check

```bash
grep -rnI --include="*.ts" --include="*.tsx" --include="*.js" -E '\b(TODO|FIXME|HACK|XXX|NOCOMMIT|TEMP)\b' . | grep -v node_modules
```

### For Each Match, Decide

- **Resolved but not cleaned up** → Recommendation to remove the comment
- **Still relevant** → Recommendation to convert to a GitHub issue and reference it: `// TODO(#42): description`
- **Intentional / acceptable** → Note in report but don't flag as action item
- **NOCOMMIT** → **Blocker** — these should never ship

### Severity

- NOCOMMIT tags: **Blocker**
- Unresolved TODO/FIXME: **Recommendation**
- HACK with no explanation: **Recommendation** to either explain or refactor

---

## 5. Tests

### Existence Check

Look for test files:

```bash
# Common test locations and patterns
ls -d __tests__/ tests/ test/ 2>/dev/null
find . -name "*.test.ts" -o -name "*.spec.ts" -o -name "*.test.tsx" -o -name "*.spec.tsx" | grep -v node_modules | head -20
```

### If Tests Exist

Run them if possible:

```bash
npx jest --passWithNoTests 2>&1 | tail -20
# or
npx vitest run 2>&1 | tail -20
```

Check `package.json` for a `test` script and use that if available:

```bash
npm test 2>&1 | tail -20
```

Report:

- All passing: note in checklist as pass
- Failures: **Recommendation** to fix before publishing
- If test runner not installed: note as skip, recommend adding to devDependencies

### If No Tests Exist

Report as **Recommendation** — having some tests improves credibility but is not a blocker for personal projects.

### Coverage (Optional)

If coverage is configured:

```bash
npx jest --coverage 2>&1 | tail -20
# or
npx vitest run --coverage 2>&1 | tail -20
```

Report coverage percentage as informational. Do not set a minimum threshold.

---

## 6. Secrets in Source Code

### Patterns to Search

```bash
# Hardcoded credentials
grep -rnI --include="*.ts" --include="*.tsx" --include="*.js" -E '(password|passwd|secret|apiKey|apiSecret|accessKey|privateKey)\s*[:=]\s*["\x27`][^"\x27`]{8,}' . | grep -v node_modules

# Known API key formats
grep -rnI --include="*.ts" --include="*.tsx" --include="*.js" -E '(sk-[a-zA-Z0-9]{20,}|ghp_[a-zA-Z0-9]{36}|AKIA[0-9A-Z]{16}|xox[bpoa]-[0-9a-zA-Z-]+)' . | grep -v node_modules

# Private keys
grep -rnI --include="*.ts" --include="*.tsx" --include="*.js" '-----BEGIN.*PRIVATE KEY-----' . | grep -v node_modules

# Connection strings with credentials
grep -rnI --include="*.ts" --include="*.tsx" --include="*.js" -E '(mysql|postgres|mongodb|redis)://[^:]+:[^@]+@' . | grep -v node_modules
```

### False Positives to Ignore

- `process.env.API_KEY` or `process.env['SECRET']` — reading from environment is fine
- `password = undefined` or `password = ''` — empty/null assignments
- Test fixtures with obviously fake values (`password: 'test123'`, `apiKey: 'fake-key'`)
- Constants that are names, not values (`PASSWORD_FIELD = 'password'`)
- Documentation strings explaining what a variable is for
- Type definitions (`password: string`) — these are type annotations, not values

### Severity

- Real credentials found: **Blocker**
- Suspicious patterns that need manual review: **Recommendation** to verify
