# Repo Checklist

Itemized checklist for repo-level file and configuration audits. Each item includes how to verify and its severity.

## Severity Definitions

| Severity       | Meaning                                                       |
| -------------- | ------------------------------------------------------------- |
| Blocker        | Must fix before publishing — risk of data leak or broken repo |
| Recommendation | Should fix for quality and first impressions                  |
| Optional       | Nice to have for mature open-source projects                  |

---

## 1. Security & Privacy

### 1.1 .gitignore Completeness — Blocker

**Verify:** Read `.gitignore` and confirm it includes at minimum:

```
# Dependencies
node_modules/

# Build output
dist/
build/
out/

# Environment / secrets
.env
.env.*
*.pem
*.key

# TypeScript
*.tsbuildinfo

# Test coverage
coverage/

# IDE
.vscode/
.idea/
*.swp
*.swo
*~

# AI tooling
.<harness>/
AGENTS.md

# OS
.DS_Store
Thumbs.db
```

**Pass:** All relevant patterns present. Missing patterns for tools not used by the project are acceptable.

### 1.2 No Tracked Secret Files — Blocker

**Verify:** Run:

```bash
git ls-files | grep -iE '\.(env|pem|key|p12|pfx|jks|keystore|credentials|secret)$'
git ls-files | grep -iE '(credentials|secrets?|tokens?)\.(json|yaml|yml|toml|ini|cfg)$'
```

**Pass:** No results, or results are clearly template/example files (e.g., `.env.example` with no real values).

### 1.3 No Secrets in Source Code — Blocker

**Verify:** Search source files for common secret patterns:

```bash
grep -rnI --include="*.ts" --include="*.tsx" --include="*.js" -E '(password|secret|api_key|apiKey|apiSecret|token|private_key|privateKey)\s*=\s*["\x27`][^"\x27`]{8,}' .
grep -rnI --include="*.ts" --include="*.tsx" --include="*.js" -E '(sk-[a-zA-Z0-9]{20,}|ghp_[a-zA-Z0-9]{36}|AKIA[0-9A-Z]{16})' .
grep -rnI --include="*.ts" --include="*.tsx" --include="*.js" '-----BEGIN.*PRIVATE KEY-----' .
```

**Pass:** No real credentials found. False positives to ignore: test fixtures with dummy values, documentation examples, environment variable reads (`process.env.`), constant names without values.

### 1.4 No Secrets in Git History — Blocker

**Verify:** Search commit diffs for secret patterns:

```bash
git log -p --all -S 'password' --diff-filter=A -- '*.ts' '*.tsx' '*.js' '*.env' '*.json' '*.yaml' '*.yml'
git log -p --all -S 'api_key' --diff-filter=A -- '*.ts' '*.tsx' '*.js' '*.env' '*.json'
git log -p --all -S 'secret' --diff-filter=A -- '*.ts' '*.tsx' '*.js' '*.env' '*.json'
git log -p --all -S 'BEGIN.*PRIVATE KEY' -- '*.ts' '*.js' '*.pem' '*.key'
```

**Pass:** No real credentials in history. If secrets were committed and removed, recommend `git filter-repo` or `BFG Repo-Cleaner` to scrub history before publishing.

### 1.5 No Hardcoded Personal Paths — Recommendation

**Verify:** Search for absolute paths with usernames:

```bash
grep -rnI --include="*.ts" --include="*.tsx" --include="*.js" -E '(C:\\Users\\|/home/|/Users/)[a-zA-Z]' .
```

**Pass:** No hardcoded user-specific paths. Use `path.resolve()`, `path.join()`, or relative paths instead.

### 1.6 AI Tooling Files Excluded — Recommendation

**Verify:** Check whether local AI harness files are tracked:

```bash
git ls-files | grep -iE '(^\.<harness>/|^AGENTS\.md$)'
```

**Pass:** No results, or patterns already in `.gitignore`.

**Remediation:** Add `.<harness>/` and `AGENTS.md` to `.gitignore`, then remove from the index only (preserves history):

```bash
git rm --cached -r .<harness>/
git rm --cached AGENTS.md
```

Do **not** scrub these from git history — they contain no secrets and serve as a record of the tooling used during development.

### 1.7 No Personal Information — Recommendation

**Verify:** Manually review README, config files, and comments for:

- Personal email addresses (non-public)
- Phone numbers
- Internal company URLs or IP addresses
- Names of colleagues or private organizations

**Pass:** Only intentionally public contact info present (e.g., author email in package.json).

---

## 2. License

### 2.1 LICENSE File Exists — Blocker

**Verify:** Check for `LICENSE`, `LICENSE.md`, or `LICENSE.txt` at repo root.

**Pass:** File exists with a recognized open-source license body (MIT, Apache-2.0, GPL-3.0, BSD-2-Clause, BSD-3-Clause, ISC, MPL-2.0, etc.).

### 2.2 License Field in Package Metadata — Recommendation

**Verify:** Check `package.json` for a `license` field:

```json
{
  "license": "MIT"
}
```

**Pass:** License field present and matches the LICENSE file content. If no `package.json`, skip.

---

## 3. README

### 3.1 README Exists — Blocker

**Verify:** Check for `README.md` at repo root.

**Pass:** File exists and is non-empty.

### 3.2 README Required Sections — Recommendation

**Verify:** README should contain:

- **Project description** — What does this project do? (first paragraph or heading)
- **Installation** — How to install (`npm install`, clone + setup, etc.)
- **Usage** — Basic quickstart or example
- **License** — Mention of license type (can be a one-liner at the bottom)

**Pass:** All four sections present in some form. Exact headings don't matter.

### 3.3 README Freshness — Recommendation

**Verify:** Cross-check references in README against actual code:

- Module/package names referenced exist
- CLI commands shown actually work
- Function/class names mentioned exist in source
- Installation commands reference the correct package name

**Pass:** No stale references found.

---

## 4. Dependencies

### 4.1 package.json Exists — Recommendation

**Verify:** Check for `package.json` at repo root with at minimum:

- `name`
- `version`
- `description`
- `license`

**Pass:** File exists with required fields populated.

### 4.2 Dependencies Match Imports — Recommendation

**Verify:** Cross-reference:

```bash
# Find all imports
grep -rn --include="*.ts" --include="*.tsx" --include="*.js" -E "^import .+ from ['\"]" . | grep -v node_modules | grep -v dist
grep -rn --include="*.ts" --include="*.tsx" --include="*.js" -E "require\(['\"]" . | grep -v node_modules | grep -v dist
```

Compare against declared dependencies in `package.json`. Check for:

- Third-party imports missing from dependencies
- Declared dependencies not imported anywhere (may be plugins or peer deps — verify before flagging)

**Pass:** All third-party imports have corresponding dependency declarations.

### 4.3 Node.js Version Constraint — Recommendation

**Verify:** Check for:

- `package.json`: `"engines": { "node": ">=18" }` (or similar)
- `.nvmrc` or `.node-version` file

**Pass:** Node.js version constraint is declared somewhere.

### 4.4 Dev Dependencies Separated — Recommendation

**Verify:** Dev-only packages (typescript, eslint, prettier, jest, vitest, ts-node, etc.) should be in `devDependencies`, not `dependencies`.

**Pass:** Dev tools are not in the main dependency list.

### 4.5 TypeScript Configuration — Recommendation

**Verify:** Check that `tsconfig.json` exists and includes:

- `"strict": true`
- Appropriate `target` and `module` settings
- `outDir` pointing to build directory (e.g., `dist/`)

**Pass:** tsconfig.json exists with strict mode enabled.

### 4.6 Lock File Committed — Recommendation

**Verify:** Check that `package-lock.json`, `yarn.lock`, or `pnpm-lock.yaml` is tracked:

```bash
git ls-files | grep -E '(package-lock\.json|yarn\.lock|pnpm-lock\.yaml)$'
```

**Pass:** Exactly one lock file is tracked.

---

## 5. Repo Hygiene

### 5.1 No Large Binary Files — Recommendation

**Verify:**

```bash
git ls-files | while read f; do wc -c "$f"; done | sort -rn | head -20
```

Flag files over 1MB that are binary (images, compiled files, data files).

**Pass:** No large binaries tracked. If needed, use Git LFS or document why they're included.

### 5.2 No Generated Files Committed — Recommendation

**Verify:** Check that these are NOT tracked:

```bash
git ls-files | grep -E '(^dist/|^build/|^out/|^node_modules/|^coverage/|\.tsbuildinfo$)'
```

**Pass:** No generated/build artifact directories tracked.

---

## 6. Optional Files

These are not required but are recommended for mature projects. Report as **Optional Enhancement** if missing.

| File                               | Purpose                              |
| ---------------------------------- | ------------------------------------ |
| `CHANGELOG.md`                     | Track notable changes per release    |
| `CONTRIBUTING.md`                  | Guide for contributors               |
| `CODE_OF_CONDUCT.md`               | Community standards                  |
| `SECURITY.md`                      | Vulnerability reporting instructions |
| `.github/ISSUE_TEMPLATE/`          | Structured issue creation            |
| `.github/PULL_REQUEST_TEMPLATE.md` | PR guidelines                        |
| `.github/workflows/*.yml`          | CI/CD automation                     |
| `.husky/`                          | Git hooks via Husky                  |
