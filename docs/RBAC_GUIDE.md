# RBAC guide

MemoGraph's authorization model in v1.0 is intentionally narrow.
This document describes what's enforced today, what's not, and why.

## Today (v1.0): scopes

There is one named role: `admin`. Everything else is "authenticated."

| Scope | Reach |
|---|---|
| (no auth) | When `MEMOGRAPH_AUTH_PROVIDER=none`, every route returns 200 to anonymous callers. The startup banner warns about this; it is not safe for production. |
| (any authenticated user) | All non-admin `/api/v1/*` routes. |
| `admin` | All routes including `/api/v1/admin/tenants/*`. |

The `admin` scope is the only role check enforced in code. It is
applied at router-mount time:

```python
admin_dep = [Depends(require_scope("admin"))]
app.include_router(admin.router, prefix=prefix, dependencies=admin_dep)
```

A user without `admin` who calls an admin route gets a 403. An
unauthenticated caller gets a 401 (the auth dependency runs first).

## What enforces tenant isolation

In multi-tenant mode, a user's `tenant_id` comes from the auth
context — never from a query parameter or path segment on a
non-admin route. Today the wiring isn't yet in `kernel.py` (Phase
3.5); the admin routes are the only ones that name a tenant
explicitly. When Phase 3.5 lands, the contract becomes:

- Non-admin routes: tenant resolved from `current_user.organization_id`
  (or whatever claim your IdP populates — see `auth.py`).
- Admin routes: tenant_id is a path parameter, but the caller still
  needs the `admin` scope.

## What's *not* enforced (yet)

- **Memory-level ACL within a tenant.** All authenticated users
  within a tenant can read and write all memories. Per-memory
  access control is deferred to v1.1 because most enterprise
  customers don't need it day-1, and getting it wrong is worse
  than not having it.
- **Read-only roles.** No `viewer` scope today; if you need one,
  put a read-only proxy in front of MemoGraph that strips
  `POST/PUT/DELETE`. We will add `editor` / `viewer` scopes in
  v1.1 alongside the per-memory ACL work.
- **Per-tool authorization for the MCP server.** Phase 1.1d added
  the auth surface; per-tool scopes are a v1.1 follow-up.

## Granting `admin`

The `admin` scope is plumbed through whatever your IdP supports:

- **Auth0**: Permission named `admin` on the API; assigned via
  RBAC. Project the `permissions` claim into `scopes` via an
  Action.
- **WorkOS**: Org role mapped to `scopes` via a JWT template.
- **Clerk**: Custom claim in your JWT template that interpolates
  the user's role(s) into `scopes`.
- **Okta**: Custom scope on the authorization server.
- **Azure AD**: Application scope (`admin`) and require admin
  consent if your tenant is opted in.
- **Keycloak**: Realm role mapped to `scopes` via a client mapper.

For API keys (`MEMOGRAPH_AUTH_PROVIDER=api_key`), today every key
gets only the `api_key` scope. To grant `admin` to a specific key,
use OIDC instead, or use the `multi` provider mode and have your
admins authenticate via the OIDC path.

A future minor will add a key→scope map (env-driven JSON), so an
operator can assign `admin` per key without standing up an IdP.

## Scopes returned by `/api/v1/auth/me`

Quick way for clients to discover what they can do:

```bash
curl -fsS https://memograph.example.com/api/v1/auth/me \
  -H "Authorization: Bearer $TOKEN"
```

Response:

```json
{
  "id": "auth0|66...",
  "email": "alice@acme.example",
  "organization_id": "org_acme",
  "scopes": ["openid", "profile", "email", "admin"]
}
```

If `scopes` is missing `admin`, attempts on admin routes will 403 —
clients should hide the relevant UI based on this.

## Audit trail

Every action that mutates the vault writes an `Action` record via
`memograph/core/action_logger.py`. The record includes:

- `user`: the caller's `User.id` (e.g. `auth0|66...`, `apikey:<8-char-prefix>`).
- `tenant_id`: filled in by Phase 3.5; today it's a stub.
- `verb`, `target`, `timestamp`, `outcome`.

The audit log is the source of truth for who-did-what. Logs are
flushed on every action (no batching) so a crashed process never
loses an action mid-flight.

## Roadmap

| Version | Adds |
|---|---|
| v1.0 (current) | `admin` scope; tenant scoping at admin-route layer. |
| v1.1 | `editor` / `viewer` scopes; per-memory ACL; key→scope env map. |
| v1.2 | Group-based ACL; revocable per-tenant API keys. |
| v2.0 | OPA / Cedar policy plug-in for custom authorization. |
