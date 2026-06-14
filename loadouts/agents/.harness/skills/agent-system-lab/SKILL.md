---
name: agent-system-lab
description: >
  Use when Codex needs to design, evaluate, harden, or improve an agentic
  system using a repo-agnostic methodology: discover real user workflows,
  verify agent logging, build live LLM-call evals from human-like tasks,
  iterate on prompts/tools/knowledge/context, and prune ineffective agent
  surface area.
---

# Agent System Lab

Use this skill as a personal methodology for producing effective agentic systems in any repository. Optimize for real user outcomes, live end-to-end evidence, strong observability, and efficient agent surface area.

## Workflow

1. Discover the agent system.
   Read the repository, product flows, prompts, tools, knowledge sources, state layers, tests, logs, docs, and existing evals. Identify what the agent can affect and where user intent enters the system.

2. Create a use-case analysis document.
   Default to `docs/agent-use-cases.md` unless the user specifies another path. Group use cases into clean user-intent categories. For each category, capture realistic user prompts, expected outcomes, required state changes, likely tools or knowledge sources, ambiguity/clarification needs, failure modes, and acceptance criteria.

3. Verify logging before relying on evals.
   Inspect the existing logging/tracing implementation and respect it when it is effective. If it is missing or weak, recommend the two-layer logging approach in `references/agent-logging.md`: full LLM-call traces plus compact structured action summaries.

4. Build live real-user-task evals before changing the agent.
   Use real LLM calls through the actual agent path. Do not mock model responses as the main eval surface. Write prompts as humans would ask for outcomes; do not instruct the agent to call particular tools.

5. Cover simple through highly complex behavior.
   Include short tasks, medium multi-step tasks, and difficult workflows requiring several tools, knowledge sources, state reads/writes, clarification, recovery, and a final user-facing synthesis.

6. Grade outcomes, not preferred tool paths.
   Prefer deterministic checks for state/API/output correctness where possible, plus human or LLM rubric checks for qualitative behavior. A tool call is evidence only when it helps prove the user outcome.

7. Iterate from failures.
   Run the live evals, inspect traces and final state, improve prompts/tools/knowledge/context/data flow, and rerun. Do not weaken tests to match the current system. Make improvements that should carry over to real users.

8. Prune aggressively.
   Remove or simplify tools, instructions, knowledge sources, and context that do not improve eval results, real workflows, reliability, or debuggability. Track unnecessary tool calls and repeated retries as failures of system design.

9. Stop with evidence.
   Use a bounded live-eval loop with explicit max iterations, calls, time, or cost. Finish with pass/fail results, residual risks, logging gaps, and the next highest-leverage improvements.

## References

- Read `references/eval-methodology.md` when designing eval suites, grading rubrics, or the test/improvement loop.
- Read `references/agent-logging.md` when auditing or designing observability for an agent system.
