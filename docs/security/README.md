# Security documentation index

VITA security governance for the psychological life companion system.

| Document | Purpose |
|----------|---------|
| [threat-model.md](threat-model.md) | STRIDE-oriented threat model and mitigations |
| [secrets-policy.md](secrets-policy.md) | Secret storage, rotation, CI rules |
| [key-rotation-runbook.md](key-rotation-runbook.md) | Staging drill: DB, JWT, API_KEY, webhook |
| [prompt-injection-mitigations.md](prompt-injection-mitigations.md) | Input sanitizer, audit logging (TD-004) |
| [dependency-scanning.md](dependency-scanning.md) | pip-audit in CI and local workflow |
| [session-isolation.md](session-isolation.md) | Session data boundaries and log shipping |

Related:

- [../database/data-classification.md](../database/data-classification.md)
- [../clinical/companion-language-guide.md](../clinical/companion-language-guide.md)
- [../operations/crisis-playbook.md](../operations/crisis-playbook.md)
