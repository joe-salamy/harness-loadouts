# Eval Methodology

## Core Standard

Evaluate the agent as a user experiences it: live LLM calls, the real orchestration path, real tool execution, real knowledge retrieval, and observable final outcomes. Mocked model responses can support unit tests, but they are not a substitute for live agent evals.

## Use-Case Source Material

Build eval cases from:

- repository-wide use-case analysis
- production or staging logs when available
- support tickets, bug reports, user interviews, and product docs
- workflows that require cross-feature coordination
- high-cost mistakes, edge cases, and ambiguous user language
- known regression areas and previously failed eval traces

Do not start from the tool list and write one test per tool. Start from what real people want done and let the agent decide which tools, knowledge, and state operations are needed.

## Eval Shape

Each eval scenario should include:

- a human-style user prompt or short conversation
- seeded state, fixtures, or environment assumptions
- expected durable outcomes
- forbidden outcomes or unsafe side effects
- grading checks
- trace requirements
- complexity label: simple, medium, or complex

Complex scenarios should require multi-step reasoning and multiple system capabilities. Include tasks that combine retrieval, planning, tool calls, updates, validation, ambiguity handling, and a final user-facing explanation.

## Grading

Use a hybrid rubric:

- Deterministic checks for database state, files, API responses, event logs, tool outputs, and generated artifacts.
- LLM or human grading for judgment-heavy outputs such as helpfulness, synthesis, explanation quality, ambiguity handling, and refusal quality.
- Trace review for whether the agent used available information efficiently and recovered from errors appropriately.

Calibrate LLM judges against human review for a small representative set before trusting them broadly.

## Eval Integrity

Protect the eval from overfitting:

- Do not include required tool names in user prompts unless a real user would name them.
- Do not weaken assertions because the current agent cannot pass.
- Do not add brittle checks for internal implementation details unless those details are part of the public contract.
- Keep held-out scenarios for regression confidence after improvements.
- Prefer new general capabilities over test-specific patches.

## Improvement Loop

For each iteration:

1. Run the bounded live eval suite.
2. Read failures with traces, logs, state diffs, and final responses.
3. Classify root causes: prompt, tool design, tool schema, orchestration, knowledge, retrieval, context, state access, UI/API contract, model choice, or missing capability.
4. Make the smallest real improvement that should generalize.
5. Remove or simplify instructions/tools/knowledge that add cost without measurable value.
6. Rerun failed scenarios and a representative regression slice.

Stop when all target evals pass or the iteration limit is exhausted. If stopping on limit, report the remaining failures, likely causes, and next experiments.
