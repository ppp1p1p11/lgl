# ADR-0003: Authentication and MFA built into the backend

- Status: Proposed — **needs founder decision** (see question Q6 in
  `docs/phase-0-plan.md`)
- Date: 2026-10-27

## Context
We need email + password login, mandatory MFA, and per-firm roles (sócio,
advogado, estagiário, administrativo). Identity data is personal data and
should stay in Brazil. Many hosted auth services store user data in the US or
EU only.

## Decision (proposed)
Implement authentication inside the backend using well-established
libraries, not hand-written cryptography:
- Passwords hashed with Argon2id.
- MFA via TOTP (authenticator app) at launch; WebAuthn/passkeys as a later
  addition. Recovery codes stored hashed.
- Server-side sessions stored in Postgres, sent as `HttpOnly`, `Secure`,
  `SameSite` cookies; CSRF protection on state-changing requests.
- Rate limiting and lockout on login and MFA endpoints.
- Roles checked in the backend on every request; the UI only hides what the
  backend already forbids.

## Consequences
- Identity data stays in our Brazilian database; no extra vendor contract.
- We own the security of the login flow. Mitigated by using standard
  libraries, a short security checklist in Phase 1, and an external review
  before the pilot.
- No single sign-on (Google/Microsoft) at launch.

## Alternatives considered
- **Hosted identity provider (Auth0, Clerk, Cognito, etc.):** less code and
  mature MFA, but user data residency must be checked per vendor (AWS Cognito
  in São Paulo may be an option — would go in `docs/VERIFY.md`), and it adds
  a vendor dependency. A good choice if the founder prefers not to own auth.
- **Self-hosted Keycloak:** feature-rich and can run in Brazil, but another
  heavy service to run and secure. Overkill for the MVP.
