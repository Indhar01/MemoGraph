# Compliance roadmap

Compliance is calendar-bound, not effort-bound. SOC 2 Type II
requires a six-month operating period regardless of how fast the
controls land in code. This document is honest about the timeline,
about what MemoGraph already supports, and about what work remains
on each track.

This is a roadmap, not an audit report. None of the assertions
below have been independently verified.

## Is MemoGraph compliant today?

No. As of v1.0:

- We have the technical foundations (auth, audit log, encryption
  in transit, backup, RBAC primitives).
- We do **not** have an attestation report from an auditor on any
  framework.
- We do **not** have a customer-facing trust portal.

If your customer requires a SOC 2 Type II report or ISO 27001
certificate today, the answer is "we are working toward it; here's
the timeline." Most enterprise customers will accept that for an
early-stage vendor *if* you are honest about it and can show the
controls plan.

## Framework selection

Pick based on your customers:

| Framework | Pick when |
|---|---|
| **SOC 2 Type II** | US-centric customers, especially in tech. Most common ask. |
| **ISO 27001** | EU customers and global enterprises. Overlaps SOC 2 by ~70%. |
| **HIPAA** | US healthcare. Different control set; not directly addressed by SOC 2. |
| **FedRAMP** | US federal. Multi-year program; do not start without a federal customer in hand. |
| **none** | Targeting SMB or developer-tool customers. Skip until a deal forces the question. |

Recommendation for v1: target **SOC 2 Type II** first. It's the
most-asked-for, the controls map cleanly onto MemoGraph's
architecture, and the auditor ecosystem (Vanta / Drata /
Secureframe) has good off-the-shelf tooling.

## SOC 2 Type II — controls inventory

The five trust service criteria (TSCs) and what MemoGraph already
ships vs. what's outstanding.

### Security (CC1–CC9)

| Control area | Status | Where |
|---|---|---|
| Access control | **Partial.** Auth is provider-neutral OIDC + API keys with `admin` scope. | `memograph/web/backend/auth.py` |
| Audit logging | **Partial.** Every mutation writes an `Action` record. Tenant-aware fields land in Phase 3.5. | `memograph/core/action_logger.py` |
| Change management | **Outstanding.** PR-template + CI gates + signed releases need to ship. | Phase 4.4 |
| Vendor management | **Outstanding.** Vendor inventory + DPAs not formalized. | Operational |
| Network security | **Partial.** Reverse-proxy TLS, body-size cap, rate limiting. | `deploy/nginx.conf`, `memograph/web/backend/middleware.py` |
| Vulnerability management | **Partial.** `bandit` + `pip-audit` in `security.yml`. Quarterly third-party pen test outstanding. | `.github/workflows/security.yml` |
| Encryption at rest | **Outstanding.** Filesystem-level only today. Per-tenant KMS-managed keys = Phase 5.1. | — |
| Incident response | **Outstanding.** Runbook templates not yet written. | Phase 5.2 |

### Availability (A1)

| Control area | Status | Where |
|---|---|---|
| Backup | **Yes.** Versioned format + integrity check + sidecar. | `memograph/core/backup.py`, [BACKUP_RESTORE_RUNBOOK.md](BACKUP_RESTORE_RUNBOOK.md) |
| DR drill | **Outstanding (operational).** Quarterly cadence required for the report. | [BACKUP_RESTORE_RUNBOOK.md](BACKUP_RESTORE_RUNBOOK.md#dr-drill) |
| Capacity planning | **Partial.** Vault size cap, rate limits. Quotas land in Phase 3.6. | `memograph/storage/vault.py` |
| Monitoring | **Yes.** Prometheus + OTel. | [OBSERVABILITY_GUIDE.md](OBSERVABILITY_GUIDE.md) |

### Processing integrity (PI1)

Generally not in scope for a memory system unless you are billing on
specific computations. If your customers do depend on result
correctness, the MCP server's tool semantics and the kernel's API
contract are the surface to attest. Out of scope for the initial
report.

### Confidentiality (C1)

| Control area | Status | Where |
|---|---|---|
| Data classification | **Outstanding (policy work).** Not a code task. | Operational |
| Data in transit | **Yes.** TLS at the proxy. | `deploy/nginx.conf` |
| Data at rest | **Outstanding.** See Security/Encryption above. | Phase 5.1 |
| Confidential disposal | **Yes.** GDPR runbook + admin offboard. | [GDPR_RUNBOOK.md](GDPR_RUNBOOK.md) |

### Privacy (P1–P8)

Add to scope only if you offer the service to consumers (B2C). For
B2B-only deployments (operator pulls in user data on the user's
behalf), the customer's privacy program covers most of P1–P8 and
MemoGraph is a sub-processor. Document the sub-processor
relationship in the customer's DPA.

## Realistic timeline

| Month | Activity |
|---|---|
| 0 | Engage auditor (Vanta / Drata / Secureframe). Pick scope. Sign engagement letter. |
| 0–1 | Implement outstanding controls. Write policies (information security policy, access control policy, change management policy, incident response, vendor management, BCP/DR). Auditor's tooling provides templates; you customize them. |
| 1 | Type I report (point-in-time): controls *exist*. ~$5–25k. Useful for early customer asks. |
| 1–7 | **Operating period.** All controls run live for ≥ 6 months. This is the calendar wall — you cannot compress it. Auditor's tooling continuously collects evidence (access reviews, on-call rotations, deploy records, security scan output). |
| 7–9 | Auditor reviews evidence, writes Type II report. ~$25–75k for the audit itself. |
| 9 | **Type II report in hand.** This is what enterprise procurement actually asks for. |

So: nine months from today to a Type II report, and that's if you
start *now* and all the policy work proceeds in parallel with code
work.

## ISO 27001 — overlaps and additions

If EU customers are in scope, ISO 27001 overlaps SOC 2 by roughly
70%. The additional work is mostly policy-driven:

- ISMS (Information Security Management System) — a governance
  document framework that SOC 2 doesn't require but ISO does.
- Statement of Applicability — explicit per-control "applies / does
  not apply / accepted risk" decisions.
- Three-year audit cycle (Stage 1 + Stage 2 + annual surveillance).

Realistic timeline: a SOC 2 Type II project that adds ISO 27001
mid-stream typically lands the ISO certificate ~3 months after the
Type II report. Do them concurrently if you have the bandwidth.

## Per-customer security questionnaires

Even before the formal report, customers will send security
questionnaires. The doc set you already have answers most of them:

| Question category | Point them at |
|---|---|
| How is data encrypted in transit? | [INSTALL_ENTERPRISE.md](INSTALL_ENTERPRISE.md) (TLS at proxy) |
| How is access controlled? | [SSO_SETUP.md](SSO_SETUP.md), [RBAC_GUIDE.md](RBAC_GUIDE.md) |
| How are audit logs handled? | [OBSERVABILITY_GUIDE.md](OBSERVABILITY_GUIDE.md), `action_logger.py` |
| What happens to my data on offboarding? | [GDPR_RUNBOOK.md](GDPR_RUNBOOK.md) |
| How is the service backed up? | [BACKUP_RESTORE_RUNBOOK.md](BACKUP_RESTORE_RUNBOOK.md) |
| How is multi-tenancy isolated? | [adr/0001-tenancy-model.md](adr/0001-tenancy-model.md) |
| What is the patch / vulnerability process? | `.github/workflows/security.yml` + `SECURITY.md` |

For everything else, be honest. "Not yet, on the roadmap" is the
right answer for outstanding controls. Trying to fudge a
questionnaire is the worst possible strategy with security teams —
they will notice, and you will lose the deal.

## Outstanding code work for Phase 5

Track separately from the audit-engagement work above:

- **Phase 5.1 — Encryption at rest with customer-managed keys**
  - Per-tenant KEK fetched from a configurable KMS (AWS / GCP /
    Vault).
  - DEK envelope-encrypted per write; derived from KEK on read.
  - BYOK switch for regulated tenants.
- **Phase 5.2 — Operational runbooks**
  - `INCIDENT_RESPONSE.md` with severity matrix, escalation paths,
    customer-comms templates.
  - `ACCESS_REVIEW.md` quarterly cadence.
- **Phase 5.3 — Penetration test**
  - Annual third-party engagement; remediate findings; ship a
    summary report (not the raw findings) to customers under NDA.
- **Phase 5.4 — Bug bounty**
  - Public program on HackerOne / Bugcrowd once the surface is
    hardened. Don't open this on day one — it generates noise that
    drowns the early-stage team.
- **Phase 5.5 — Data residency**
  - Per-tenant region pinning. Cross-region replication optional.
  - This is mostly an infra story (where the deployment runs)
    rather than a code story, but the multi-tenancy work in Phase
    3 has to honor it.

These are real engineering quarters of work each. None of them are
single-session items. The right cadence is: ship Phase 5.1 first
(it removes the most-common questionnaire blocker), schedule the
pen test for Q+2, defer the rest until customer demand requires
them.
