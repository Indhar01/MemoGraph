# SSO setup

MemoGraph's auth is provider-neutral: any IdP that publishes a JWKS
endpoint and signs tokens with RS256/RS384/RS512/ES256/ES384/ES512
will work. The same code path serves WorkOS, Auth0, Clerk, Okta,
Azure AD, Google Workspace, and Keycloak. Pick one.

This guide covers:

1. The four env vars MemoGraph needs no matter the provider.
2. Per-provider notes for the most common IdPs.
3. How to map your IdP's claims onto MemoGraph's `User` and scopes.
4. How to test the setup before flipping production.

## The four env vars

```bash
MEMOGRAPH_AUTH_PROVIDER=oidc      # or "multi" if you also accept API keys
MEMOGRAPH_OIDC_JWKS_URL=https://<idp>/.well-known/jwks.json
MEMOGRAPH_OIDC_AUDIENCE=memograph-api
MEMOGRAPH_OIDC_ISSUER=https://<idp>/        # optional but recommended
```

- **JWKS URL** is the public-keys endpoint; MemoGraph fetches and
  caches it on first use. We do not embed the static JWK in config —
  if your IdP rotates keys, MemoGraph picks up the new ones.
- **Audience** must match the `aud` claim on issued tokens *exactly*.
  Pin it tightly; never accept wildcard audiences.
- **Issuer** is optional but recommended: when set, MemoGraph
  verifies the `iss` claim equals this string. It catches the
  "stolen token from another IdP" failure mode.

Tokens use one of the asymmetric algorithms above. HMAC (HS256, etc.)
and "none" (unsigned) are explicitly rejected — for a JWKS-style
flow, HMAC tokens would mean the JWKS endpoint becomes a credential.

## Per-provider notes

### Auth0

1. Auth0 dashboard → APIs → Create API. Identifier = `memograph-api`.
2. Auth0 dashboard → Applications → your app → Settings → grab the
   `Domain`. JWKS URL is `https://<your-domain>/.well-known/jwks.json`.
3. Issuer is `https://<your-domain>/`.

```bash
MEMOGRAPH_OIDC_JWKS_URL=https://acme.us.auth0.com/.well-known/jwks.json
MEMOGRAPH_OIDC_AUDIENCE=memograph-api
MEMOGRAPH_OIDC_ISSUER=https://acme.us.auth0.com/
```

For admin-scope users, add a "permission" of `admin` on the API
configuration and assign it via Auth0's RBAC dashboard. Permissions
land in the `permissions` claim by default; MemoGraph reads `scope`
and `scopes` claims, so configure your action/rule to project
`permissions` into one of those.

### WorkOS

1. WorkOS dashboard → API Keys → enable AuthKit (the OIDC issuer).
2. JWKS URL is `https://api.workos.com/sso/jwks/<client_id>`.
3. Audience is your client ID by default; rename it via the
   AuthKit settings if you want a stable name like `memograph-api`.

```bash
MEMOGRAPH_OIDC_JWKS_URL=https://api.workos.com/sso/jwks/client_xxx
MEMOGRAPH_OIDC_AUDIENCE=client_xxx
MEMOGRAPH_OIDC_ISSUER=https://api.workos.com
```

WorkOS organization roles are surfaced in the `org_role` claim;
project them into a `scope` or `scopes` claim via a JWT template.

### Clerk

1. Clerk dashboard → JWT Templates → New template named
   `memograph-api`. Add a `scopes` claim that interpolates the
   user's role(s).
2. JWKS URL: `https://<your-frontend-api>/.well-known/jwks.json`
   (visible on the dashboard).

```bash
MEMOGRAPH_OIDC_JWKS_URL=https://acme.clerk.accounts.dev/.well-known/jwks.json
MEMOGRAPH_OIDC_AUDIENCE=memograph-api
MEMOGRAPH_OIDC_ISSUER=https://acme.clerk.accounts.dev
```

### Okta

1. Okta admin → API → Authorization Servers → create one named
   `memograph` (or use `default`). Note the issuer URI.
2. Add a custom scope (`admin`) for elevated callers.
3. JWKS URL: `<issuer>/v1/keys`.

```bash
MEMOGRAPH_OIDC_JWKS_URL=https://acme.okta.com/oauth2/default/v1/keys
MEMOGRAPH_OIDC_AUDIENCE=memograph-api
MEMOGRAPH_OIDC_ISSUER=https://acme.okta.com/oauth2/default
```

### Azure AD / Microsoft Entra ID

1. Azure Portal → Microsoft Entra ID → App registrations → New.
2. Expose an API named `memograph-api` and add an `admin` scope.
3. JWKS URL: `https://login.microsoftonline.com/<tenant>/discovery/v2.0/keys`.

```bash
MEMOGRAPH_OIDC_JWKS_URL=https://login.microsoftonline.com/<tenant-id>/discovery/v2.0/keys
MEMOGRAPH_OIDC_AUDIENCE=api://<application-id>
MEMOGRAPH_OIDC_ISSUER=https://login.microsoftonline.com/<tenant-id>/v2.0
```

### Keycloak (self-hosted)

1. Realm → Clients → Create client `memograph-api`. Access type =
   `bearer-only` (we never run an OAuth flow ourselves).
2. JWKS URL: `<base>/realms/<realm>/protocol/openid-connect/certs`.

```bash
MEMOGRAPH_OIDC_JWKS_URL=https://keycloak.example.com/realms/acme/protocol/openid-connect/certs
MEMOGRAPH_OIDC_AUDIENCE=memograph-api
MEMOGRAPH_OIDC_ISSUER=https://keycloak.example.com/realms/acme
```

Keycloak roles are in the `realm_access.roles` claim by default; map
them to `scope`/`scopes` via a Mapper on the client.

## Claim mapping

The `User` MemoGraph constructs from a verified JWT pulls:

| `User` field | Claim source |
|---|---|
| `id` | `sub` |
| `email` | `email` (if present) |
| `organization_id` | `org_id` (if present) — for the multi-tenancy bridge |
| `scopes` | `scope` (space-delimited string) **or** `scopes` (string list) |

If neither `scope` nor `scopes` is present, the user has *no* scopes
and cannot reach admin routes. Make sure your IdP projects roles
into one of those claims.

For the `admin` scope specifically: any user with `admin` in their
`scopes` tuple can call `/api/v1/admin/tenants/*`. There is no
separate "super-admin" — within the deployment, `admin` is the
top role.

## Testing the setup

A quick local smoke test against any production IdP without going
through the full browser flow:

```bash
# Get a token from your IdP (provider-specific). For Auth0:
TOKEN=$(curl -s -X POST https://acme.us.auth0.com/oauth/token \
  -H "Content-Type: application/json" \
  -d "{\"client_id\":\"...\",\"client_secret\":\"...\",\"audience\":\"memograph-api\",\"grant_type\":\"client_credentials\"}" \
  | jq -r .access_token)

# Hit a protected route.
curl -fsS https://memograph.example.com/api/v1/auth/me \
  -H "Authorization: Bearer $TOKEN"
```

Expected JSON:

```json
{
  "id": "auth0|66...",
  "email": "alice@acme.example",
  "organization_id": "",
  "scopes": ["openid", "profile", "email", "admin"]
}
```

## Common failure modes

| Symptom | Likely cause |
|---|---|
| `401` with `WWW-Authenticate: Bearer error="invalid_token"` | Wrong audience, expired, signature mismatch. Server logs the *category* of failure but never echoes it to clients (so attackers can't fingerprint the verifier). |
| `403` after a successful auth | Token is valid but lacks the required scope. For admin routes, ensure your scope mapper populates `scopes` (or `scope`) with `admin`. |
| `503` from `/api/v1/admin/*` | Multi-tenancy is not enabled. Set `MEMOGRAPH_TENANCY_ENABLED=1`. |
| Hangs on first request | First JWKS fetch is slow if your IdP is far away. Set up a JWKS cache warmup probe in your readiness check. |

## Rotating credentials

- **JWKS keys** rotate on the IdP side; MemoGraph picks new keys up
  on the next request after the cache TTL expires. No restart
  needed.
- **API keys** rotate by updating `MEMOGRAPH_API_KEYS` and
  restarting (or re-loading via `kill -HUP` once the reload signal
  handler lands in Phase 4.4). Keep two keys live during rotation.
- **OIDC client secrets** are an IdP concern — MemoGraph never
  holds them.
