# TypeScript Code Review Skill

A comprehensive skill for performing professional TypeScript code reviews with focus on type safety, best practices, performance, security, and maintainability.

## Overview

This skill helps an AI coding agent conduct thorough code reviews of TypeScript projects, identifying:

- **Type Safety Issues**: Improper use of `any`, missing type annotations, unsafe type assertions
- **Security Vulnerabilities**: SQL injection, XSS, hardcoded secrets, improper input validation
- **Performance Problems**: Inefficient algorithms, unnecessary re-renders, bundle size issues
- **Code Quality**: Anti-patterns, maintainability concerns, style inconsistencies
- **Best Practices**: Modern TypeScript features, proper error handling, immutability

## Skill Structure

```
typescript-code-review/
├── SKILL.md                                    # Main skill instructions
├── README.md                                   # This file
├── references/                                 # Detailed reference materials
│   ├── type-safety-checklist.md               # Type safety best practices
│   ├── common-antipatterns.md                 # TypeScript anti-patterns to avoid
│   ├── security-checklist.md                  # Security considerations
│   └── performance-tips.md                    # Performance optimization strategies
└── examples/                                   # Example code
    ├── before-review.ts                       # Code with common issues
    ├── after-review.ts                        # Fixed version with best practices
    └── sample-review-output.md                # Example of review format
```

## How to Use

### Basic Usage

Ask your agent to review your TypeScript code:

```
"Please review this TypeScript file for issues"
"Can you check this code for type safety problems?"
"Review this React component for performance issues"
```

### Focused Reviews

You can request specific types of reviews:

```
"Review this code for security vulnerabilities"
"Check this function for performance issues"
"Analyze the type safety of this module"
```

### Configuration Reviews

Ask your agent to review your TypeScript configuration:

```
"Review my tsconfig.json settings"
"Check if my TypeScript compiler options are optimal"
```

## Review Categories

The skill performs reviews across these categories:

### 1. Type Safety

- Strict mode compliance
- Type annotations and inference
- Type guards and narrowing
- Generic types usage
- Null/undefined handling
- Return type annotations

### 2. Security

- Input validation
- XSS prevention
- SQL/NoSQL injection prevention
- Authentication & authorization
- Secrets management
- CSRF protection
- Data exposure

### 3. Performance

- Algorithm efficiency
- Memory management
- Bundle size optimization
- React/UI performance
- Network optimization
- TypeScript compilation speed

### 4. Code Quality

- Naming conventions
- Function complexity
- DRY principle
- Error handling
- Async/await usage
- Immutability
- Modern TypeScript features

## Output Format

Reviews are structured with:

1. **Summary**: High-level overview and main concerns
2. **Critical Issues 🔴**: Must-fix problems (security, bugs, type errors)
3. **Important Improvements 🟡**: Significant issues affecting quality
4. **Suggestions 🔵**: Nice-to-have improvements
5. **Positive Observations ✅**: What the code does well
6. **Detailed Findings**: Specific issues with code examples and recommendations

## Reference Materials

The skill includes detailed reference files for deeper guidance:

- **type-safety-checklist.md**: Comprehensive guide to TypeScript type safety
- **common-antipatterns.md**: Anti-patterns to avoid with better alternatives
- **security-checklist.md**: Security best practices and vulnerability prevention
- **performance-tips.md**: Performance optimization strategies

The agent can reference these when encountering specific issues.

## Examples

### Example Files

- **before-review.ts**: Contains 20 common TypeScript issues
- **after-review.ts**: Shows proper implementations and best practices
- **sample-review-output.md**: Example of a complete code review

### Common Issues Covered

1. Type safety (using `any`, missing types)
2. Security (SQL injection, XSS, hardcoded secrets)
3. Performance (O(n²) algorithms, sequential awaits)
4. Memory leaks (event listeners, timers)
5. Anti-patterns (enums, mutations, type assertions)
6. Error handling (unhandled promises, improper try-catch)

## Configuration

### Recommended tsconfig.json

```json
{
  "compilerOptions": {
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "noImplicitOverride": true,
    "noPropertyAccessFromIndexSignature": true,
    "exactOptionalPropertyTypes": true,
    "noFallthroughCasesInSwitch": true,
    "noImplicitReturns": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true
  }
}
```

### Recommended Tools

The skill suggests using these tools:

- **TypeScript Compiler**: `tsc --noEmit` for type checking
- **ESLint**: With `@typescript-eslint/parser`
- **Prettier**: For consistent formatting
- **ts-prune**: Find unused exports
- **depcheck**: Find unused dependencies
- **madge**: Detect circular dependencies

## When to Use This Skill

The skill activates when you:

- Request a code review of TypeScript code
- Ask for feedback on TypeScript implementation
- Want to check code for issues, bugs, or improvements
- Need to ensure TypeScript best practices
- Request security or performance audits
- Ask to improve code quality or type safety

## Key Features

✅ **Comprehensive**: Covers type safety, security, performance, and quality
✅ **Actionable**: Provides specific code examples and recommendations
✅ **Educational**: Explains the "why" behind each recommendation
✅ **Practical**: Prioritizes issues by severity (critical, important, suggestion)
✅ **Modern**: References latest TypeScript features (4.9+, 5.0+)
✅ **Framework-Aware**: Includes React, Node.js, and testing considerations

## Tips for Best Results

1. **Provide context**: Mention the project type (React app, Node API, library, etc.)
2. **Specify concerns**: If you're worried about specific issues, mention them
3. **Include tsconfig.json**: This helps the agent understand your TypeScript settings
4. **Show related code**: Include interfaces, types, and dependencies if relevant
5. **Ask follow-up questions**: Request clarification on any recommendations

## License

This skill is adapted for <harness>-compatible loadouts and follows the repository's license.

## Contributing

If you find issues or have suggestions for improving this skill, please contribute back to the skills repository.

---

**Adapted for <harness>**
