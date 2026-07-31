# Feature Flags

This file documents runtime feature flags supported by Laura.

- `LAURA_ENABLE_AUTO_SKILLS` (default: enabled)
  - Description: controls whether the `AutonomousLoop` will auto-execute decisions that include
    a `skill`/`skill_name` key in their `metadata`.
  - Valid false values: `0`, `false`, `no`, `off`.
  - Use case: disable during testing, review of skills, or when auditing is required before
    automatic execution.

Runtime override: set the environment variable, or set the instance attribute `enable_auto_skills`
on the `AutonomousLoop` instance (bool) to override behavior programmatically.

Audit: when a skill is executed, Laura appends an audit record to `reports/laura_skill_executions.jsonl`.
Each line is a JSON object with `timestamp`, `decision_id`, `skill`, `result`, and `metadata`.
