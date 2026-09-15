# Auth0 team setup for Hirava

Prepared 2026-09-13 against the current repository. This is a setup handoff; no Auth0 tenant has been created or connected by this document. Configure development first. Changing environment variables alone does not complete the identity migration.

## 1. Ownership and environments

- Use a company-controlled email to create the Auth0 account. Assign named dashboard administrators and enable MFA for their dashboard accounts.
- Create a development tenant, suggested name `hirava-dev` (use an available company-specific suffix if needed), environment Development.
- The company must choose the hosting region according to its requirements; record the selected region. Do not infer residency requirements from the developer's location.
- Use a separate production tenant before launch. Development and production identities/secrets are separate. [Auth0 environment guidance](https://auth0.com/docs/get-started/auth0-overview/create-tenants/set-up-multiple-environments)

## 2. Register the frontend

Dashboard → Applications → Applications → Create Application:

| Setting | Development value |
| --- | --- |
| Name | Hirava Webapp Dev |
| Application type | Regular Web Application |
| Allowed Callback URLs | `http://localhost:3000/api/auth/callback` |
| Allowed Logout URLs | `http://localhost:3000` |
| Allowed Web Origins | `http://localhost:3000` |

Use localhost consistently for browser testing. The callback is explicitly customized in `hirava-webapp/src/modules/hrms/lib/auth0.ts`; it differs from the SDK default `/auth/callback`. Do not point it at FastAPI port 8000 or private port 8001. Save settings.

Keep Authorization Code enabled. Enable Refresh Token grant for session renewal and coordinate refresh-token settings with the integration test. Leave password/implicit flows unused. Copy Domain, Client ID and Client Secret using secure storage. [Auth0 Next.js setup](https://auth0.com/docs/quickstart/webapp/nextjs)

## 3. Register the FastAPI resource

Dashboard → Applications → APIs → Create API:

| Setting | Development value |
| --- | --- |
| Name | Hirava API Dev |
| Identifier / audience | `https://hirava-api.dev` |
| JWT profile | Auth0 |
| Signing algorithm | RS256 |
| Access-token expiration | 3600 seconds (initial project setting) |
| Allow Offline Access | Enabled for refresh-token renewal |

The identifier is an exact, permanent token audience, not a deployment URL; it need not resolve. Use no trailing slash and use exactly the same value in frontend and backend. Authorize Hirava Webapp Dev to access this API in the **user flow**; if the tenant uses client grants, explicitly grant this application access. A machine-to-machine test token is not a user login token. [Register APIs](https://auth0.com/docs/get-started/auth0-overview/set-up-apis)

No custom permissions, role Action or Auth0 Organizations setup is required for the current integration. Hirava currently enforces native database roles, not Auth0 role claims. Auth0 RBAC configuration alone does not change application access.

## 4. Configure login and first users

- Enable New Universal Login under Branding → Universal Login; use Hirava branding.
- Under Authentication → Database, use `Username-Password-Authentication` and enable it for Hirava Webapp Dev. Preserve this name because retained provisioning code references it.
- For this initial staff rollout, enable Disable Sign Ups on this connection. Administrators create the test identities. Candidate self-registration remains a separate application workflow to implement and verify. [Disable signups](https://support.auth0.com/center/s/article/Disable-Signups-at-Connection-Level)
- Create one first administrator using a real, team-controlled mailbox. Verify that mailbox through the verification flow. Record the Auth0 `user_id` (typically `auth0|...`). An Auth0 dashboard administrator and a Hirava administrator are separate identities/permissions.
- Create distinct test identities for recruiter, HR, manager, interviewer, employee and candidate. Supply each email and exact Auth0 user_id to the developer. Users set their own passwords; do not put passwords in the handoff.

## 5. Developer configuration — merge into existing files

Do not overwrite AWS, database, customer, gateway or other existing settings.

`hirava-webapp/.env.local`:

```dotenv
HIRAVA_API_URL=http://127.0.0.1:8000
APP_BASE_URL=http://localhost:3000
AUTH0_DOMAIN=<tenant-domain-without-https-or-trailing-slash>
AUTH0_CLIENT_ID=<Hirava-Webapp-Dev-client-id>
AUTH0_CLIENT_SECRET=<Hirava-Webapp-Dev-client-secret>
AUTH0_SECRET=<new-random-32-byte-hex-secret>
AUTH0_AUDIENCE=https://hirava-api.dev
```

Generate AUTH0_SECRET once locally (it is not the Auth0 Client Secret):

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

`hirava-api/.env`, applied during coordinated cutover:

```dotenv
AUTH_MODE=auth0
AUTH0_DOMAIN=<same-tenant-domain-without-https-or-trailing-slash>
AUTH0_AUDIENCE=https://hirava-api.dev
```

Keep the current CUSTOMER_ID and RDS/S3 settings. Keep the local environment profile for localhost testing. FastAPI validates RS256 using Auth0 public keys and does not need the web application's client secret. Secrets stay in local environment files/secret management, never Git or NEXT_PUBLIC variables.

## 6. Required identity cutover — developer-owned

Before switching authentication, link the first administrator's verified Auth0 subject to the intended `hirava_core.users` record under the existing customer, with role `admin` and active status. This must be an explicit, reviewed mapping; do not automatically grant access by matching an email. The current UI cannot bootstrap the first Auth0 administrator from an already locked-out state.

Preserve existing native user IDs and their business relationships. If converting a local account, reconcile its retained `public.User` identity from `local|<native-id>` to the verified Auth0 subject transactionally, preserving `Employee.user_id`; also review any imported party identity. Do not create a second employee. Creating a new Auth0 identity does not migrate existing local passwords or records.

Restart the frontend and FastAPI together after mapping/configuration, sign in afresh, and verify `/api/v1/auth/me`. Then register additional Auth0-linked accounts in Account Access and explicitly link employees where appropriate. The target roles are:

| Native role | Intended access to test |
| --- | --- |
| admin | RMS and HRMS |
| recruiter | RMS recruitment |
| hr | HRMS plus RMS approvals and hiring handoff |
| manager | Assigned hiring and direct-team management |
| interviewer | Assigned interviews and scorecards |
| employee | Own HRMS self-service |
| candidate | Own applications and offers |

This table is the acceptance target, not a certification that every imported screen already enforces it. The native role is authoritative; employee job titles and Auth0 role assignments alone do not grant this access.

## 7. Automatic invitations: service configuration

The single-screen invitation implementation is now in Hirava. Enable it with a separate Machine-to-Machine application `Hirava User Provisioning Dev`, authorized for Auth0 Management API with `read:users` and `create:users`. Enable that application for the database connection. This flow does not assign Auth0 roles, so it does not require role-write scopes.

Store AUTH0_MGMT_CLIENT_ID and AUTH0_MGMT_CLIENT_SECRET in `hirava-api/.env`. AUTH0_WEB_CLIENT_ID is the existing regular web application's Client ID, and AUTH0_CONNECTION defaults to Username-Password-Authentication. The Management API audience is `https://<tenant-domain>/api/v2/`; it is different from the Hirava business API audience. [Management API tokens](https://auth0.com/docs/secure/tokens/access-tokens/management-api-access-tokens)

Restart FastAPI after configuration. The administrator then opens Account Access from the sidebar, enters name/email/role and optionally selects an employee, and clicks Invite. Missing configuration disables Invite. See [invitation setup, recovery and limits](account-invitations.md). Actual provider scopes and mailbox delivery must still be tested; creating environment variables alone does not certify delivery.

## 8. Acceptance checks and production preparation

Developer and team verify: login/logout; refresh/session renewal; unregistered Auth0 user denied; inactive Hirava user denied; wrong issuer/audience/expired token denied; each role's allowed and forbidden APIs; employee sees only their own records; existing employee/document remains accessible; no duplicate employee after linking; password reset and verification delivery. Confirm email verification policy and Auth0 blocking/session-revocation behavior before launch—the current native API checks its own active flag and does not itself enforce email_verified or real-time Auth0 blocking on every request.

Before production, supply the real HTTPS frontend/API domains and configure the production tenant with exact callback/logout/origin URLs and fresh secrets. Configure and verify a company email sender/provider for production password-reset/verification delivery, and agree end-user MFA policy. Auth0 setup does not complete RMS/HRMS feature work or multi-customer isolation.

## Team handoff checklist

Return tenant name/domain/region, frontend application name/client ID, API audience, connection name, first administrator email/Auth0 user_id, the role-test email/user_id list, and planned production domains. Deliver the web Client Secret through the team's secret manager or directly into the local environment file. If optional provisioning was prepared, deliver its separate client ID/secret the same way. Do not send the company Auth0 dashboard password, user passwords, AWS keys or RDS password.
