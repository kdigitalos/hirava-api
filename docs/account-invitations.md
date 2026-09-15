# Account invitations

Account Access is available from the main HRMS sidebar and the Organization Setup sidebar. The older embedded provisioning panel now points to this single screen.

In Auth0 mode the default form asks for name, email, application role and an optional employee record. Candidate accounts cannot receive employee links. An advanced manual identity-link option remains for existing verified subjects. Application roles remain native; Auth0 role assignments are not used as authorization.

## Enable provider access

Create a separate Auth0 Machine-to-Machine application, authorize it for Auth0 Management API, grant `read:users` and `create:users`, and enable it for the `Username-Password-Authentication` database connection. Store only these dedicated credentials in `hirava-api/.env`:

```dotenv
AUTH0_MGMT_CLIENT_ID=<management-application-client-id>
AUTH0_MGMT_CLIENT_SECRET=<management-application-client-secret>
AUTH0_WEB_CLIENT_ID=<existing-regular-web-application-client-id>
AUTH0_CONNECTION=Username-Password-Authentication
```

The existing AUTH0_DOMAIN and AUTH_MODE=auth0 are used. The web client ID has been copied from the configured frontend; the web client secret stays in the frontend server environment. Restart FastAPI after adding management credentials. Missing configuration disables Invite with a visible explanation. Configuration presence does not prove provider scopes, connection authorization or email delivery.

Auth0's password-change email implements password setup for the invitee. Customize that template/sender in Auth0 and test delivery with a team-controlled mailbox. A successful API response is displayed as an email request accepted by Auth0, never as confirmed inbox delivery. [Auth0 invitation approach](https://support.auth0.com/center/s/article/Email-Invitations-for-Application-Signup)

## Recovery and identity rules

The additive `account_invitations` table records the native user, optional employee, attempt time, state and a sanitized error code. Migration: `b72d5306ef01`.

The account is initially inactive. A successful provider identity lookup/creation and employee link are committed before requesting email. New identities use a cryptographically random password that is never returned, stored locally or logged. Provider metadata contains the invitation ID for recovery after an interrupted create. Existing identities are linked only when they are an unambiguous, unblocked identity in the configured database connection, with matching email and either verified email or this exact invitation's recovery marker. Other matches require administrator review; no social identity or conflicting native subject is automatically linked.

Failed provisioning leaves the reserved account inactive. If identity/link succeeded but email failed, those completed steps stay saved and retry only requests email. Completed retries do not re-send. Processing attempts have a five-minute recovery window; concurrent attempts are serialized. If the process dies after Auth0 accepts email but before recording success, a later retry may request another email; exactly-once external delivery is not claimed.

Employee links use existing conflict checks and preserve employee IDs/documents. A failed link can leave a provider identity that the same invitation can recover; no compensating deletion of an external user occurs. An inactive, already-provisioned account is not automatically reactivated on retry. Invitation failures and successful steps are audited. Admin-only API guards enforce all invitation operations.

## Verification and current limits

Automated tests cover permission denial, configuration gating, duplicate prevention, provider failure, recovery, completed retry idempotency, verified-existing identity checks, blocked identities and employee-link-before-email ordering. Provider tests are mocked and send no email. SQLite migration rehearsal and additive RDS migration passed. RDS had zero invitations after testing.

Live provider creation and mailbox delivery still require dedicated credentials and an explicitly selected test recipient. Existing administrator Auth0 login is unchanged. Role changes for existing accounts, invitation cancellation/resending completed invitations, and organization membership invitations are not implemented in this batch. No Auth0 Organizations feature is required by this flow.
