# StatementHub Security Audit Report

**Platform:** StatementHub (MC & S Pty Ltd)
**Codebase:** ~20,000 LOC across 4 Django apps, 150+ endpoints, 30+ models
**Stack:** Django 5.2 / PostgreSQL / HTMX / Anthropic Claude API
**Date:** 22 February 2026

---

## Executive Summary

Full code review of the entire StatementHub platform. The codebase has a solid
architectural foundation (encrypted fields, CSP headers, HSTS, 2FA enforcement,
PII scrubbing in logs, protected media serving, path traversal protection).
However, serious security vulnerabilities were identified that must be fixed
before this platform handles live client financial data. The dominant pattern is
**inconsistent application of access controls** — authorization helpers exist
but are used in only ~10% of views.

**Total findings: 12 CRITICAL, 12 HIGH, 29 MEDIUM, 21 LOW**

---

## What's Working Well

- Secrets properly kept out of version control (.env files in .gitignore)
- Field-level encryption for sensitive data (TOTP, OAuth tokens, TFN)
- HSTS, CSRF, session security properly configured for production
- Path traversal protection on media files
- PII scrubbing in logs (emails, TFNs, phone numbers)
- Password minimum 12 characters with Django validators
- 2FA enforcement middleware (concept is right)
- Webhook HMAC verification (when configured)
- 30-minute session timeout with activity reset

---

## CRITICAL FINDINGS (12)

### C-1: Systemic IDOR — Authorization Bypassed in 50+ Views
**Every app affected**

The authorization module at `config/authorization.py` defines `get_entity_for_user()`,
`get_financial_year_for_user()`, and `get_review_job_for_user()` — but they're only
used in ~6 of ~60+ entity-scoped views. The rest use bare `get_object_or_404()`,
meaning any authenticated user can access, modify, or delete any entity's financial
data by changing the UUID in the URL.

**Affected operations include (non-exhaustive):**
- View/modify trial balances, journals, depreciation, stock for any entity
  (`core/views.py:853, 995, 1002, 2859`)
- Generate financial statements and distribution minutes for any entity
  (`core/views.py:1174, 1270`)
- Delete officers, assets, stock items, documents for any entity
  (`core/views.py:1619, 2918, 3051`)
- Run AI risk engine and generate risk reports for any entity
  (`core/views_audit.py:192, 517`)
- Upload bank statements and approve transactions for any entity
  (`review/views.py:648, 462, 537`)
- Bulk-reassign entity ownership without admin role
  (`core/views_upgrades.py:1456, 1535`)
- Connect/disconnect OAuth integrations for any entity
  (`integrations/views.py:70, 220`)

### C-2: Destructive Operations via GET Requests (No CSRF Protection)
**`accounts/views.py`, `core/views.py`**

Multiple state-changing operations execute on GET requests. Django's CSRF
middleware only protects POST. An attacker can embed `<img src="...">` on any
page to trigger:
- Reset any user's 2FA via GET: `accounts/views.py:354`
- Resend/reactivate invitations via GET: `accounts/views.py:155, 174`
- Delete officers, depreciation assets, stock items via GET:
  `core/views.py:1619, 2918, 3051`

### C-3: Rate Limiting Completely Bypassable
**`config/settings.py:277`**

```python
RATELIMIT_IP_META_KEY = "HTTP_X_FORWARDED_FOR"
```

`X-Forwarded-For` is a client-controlled header. Attackers can spoof a different
IP on every request, bypassing the 5/min rate limit on login and TOTP verification.

### C-4: Django Admin Bypasses 2FA Entirely
**`config/middleware.py:19`**

`/admin/` is in `EXEMPT_URLS`, so any user with `is_staff=True` can access the
full Django admin panel without completing 2FA.

### C-5: TOTP Secret Exposed in HTML to Unauthenticated Users
**`accounts/views.py:291`**

The invitation signup page renders the raw TOTP secret in the HTML body. Anyone
who intercepts an invitation URL can clone the TOTP permanently.

### C-6: Webhook Authentication Fails Open
**`config/webhook_auth.py:24-27`**

When `WEBHOOK_SECRET` is not set (the default), `verify_webhook()` returns
`True` — authentication is silently disabled. Anyone can POST to
`/api/notify/new-review-job/` and create fake review jobs.

### C-7: Authorization Bypass on NULL-Assigned Entities
**`config/authorization.py:27-33`**

When `entity.assigned_accountant` is `None`, the permission check falls through
to `return entity` — granting access to every authenticated user. Same pattern
in all three authorization functions.

### C-8: SSRF via MYOB Company File URI
**`integrations/providers.py:321`**

```python
url = f"{tenant_id}/GeneralLedger/Account"
resp = requests.get(url, ...)
```

The `tenant_id` is used as a URL base with no host validation. Manipulated
values can make the server request arbitrary internal/external hosts.

### C-9: OAuth Tokens Stored in Plaintext in Session Table
**`integrations/views.py:133-134`**

Full access and refresh tokens are placed into Django sessions during multi-tenant
OAuth flows. Sessions are stored unencrypted in `django_session` table.

### C-10: PostgreSQL Port Exposed to All Interfaces
**`docker-compose.yml:10-11`**

```yaml
ports:
  - "5432:5432"
```

Database bound to `0.0.0.0:5432`. Directly reachable from the internet on any
cloud host without a restrictive firewall.

### C-11: Notifications System Leaks Cross-User Data
**`core/views.py:3393, 3400`**

`mark_all_notifications_read` marks ALL notifications for ALL users.
`notifications_api` returns ALL unread notifications globally.

### C-12: No Authorization on Integrations App
**`integrations/views.py` (entire file)**

Every view uses only `@login_required`. Any authenticated user (including
read-only) can connect/disconnect OAuth, trigger XPM syncs, import trial
balances, and commit imports that delete and replace existing data for any entity.

---

## HIGH FINDINGS (12)

| # | Finding | Location |
|---|---------|----------|
| H-1 | DOM-based XSS — AI reasoning/code/name inserted via innerHTML | `templates/review/review_detail.html:821` |
| H-2 | XSS via \|safe filter — JSON can break out of script tags | `review_detail.html:478`, `upload_preview.html:144` |
| H-3 | AI prompt injection — bank descriptions injected into Claude prompts | `review/email_ingestion.py:355` |
| H-4 | HTML injection in PDF generation — unescaped entity names in WeasyPrint | `core/views.py:2766` |
| H-5 | Open redirect — unvalidated `next` URL in POST data | `core/views_upgrades.py:1577` |
| H-6 | Mass assignment — raw request.POST to Decimal model fields | `core/views.py:2863, 2895, 3016` |
| H-7 | OAuth connect via GET — login CSRF via crafted links | `integrations/views.py:70, 697, 994, 1344` |
| H-8 | OAuth state not cleared on failure — stale state enables fixation | `integrations/views.py:107-109` |
| H-9 | No rate limiting on signup/2FA setup — TOTP brute-forceable | `accounts/views.py:223, 368` |
| H-10 | Invitation token reused on resend — compromised tokens reactivated | `accounts/views.py:155` |
| H-11 | Django admin exposes decrypted OAuth tokens in edit forms | `integrations/admin.py` |
| H-12 | No file size/count limit on bank statement upload | `review/views.py:648` |

---

## MEDIUM FINDINGS (29)

- Media files accessible to any logged-in user — no entity-level authorization
  (`config/media_serving.py:17`)
- CSP allows `'unsafe-inline'` for scripts — negates XSS protection
  (`config/settings.py:215`)
- DB SSL defaults to `prefer` not `require` — allows MITM downgrade
  (`config/settings.py:224`)
- Bandit CI scan always passes (`|| true`) — security pipeline is decorative
  (`.github/workflows/security.yml:24`)
- Missing `can_edit` checks on 20+ write views — read-only users can modify data
  (`core/views.py`)
- Bulk delete with no ownership check — accountants can delete others' entities
  (`core/views.py:3423`)
- Encryption key tied to SECRET_KEY — rotation destroys all encrypted data
  (`config/encryption.py:17`)
- Decryption silently returns raw ciphertext on failure — masks corruption
  (`config/encryption.py:38`)
- Exception details leaked in error messages — paths, SQL, credentials visible
  (`core/views.py`, `review/views.py`, `integrations/views.py`)
- No `transaction.atomic()` on import commit — partial failure deletes data
  (`integrations/views.py:543`)
- XXE risk in XPM XML parsing — `defusedxml` not installed
  (`integrations/xpm_sync.py:15`)
- Source code mounted in Docker production — `.env`, `.git/` exposed
  (`docker-compose.yml:22`)
- Dashboard shows unscoped activities — all users see all entity activity
  (`core/views.py:98`)
- No duplicate bank statement detection
- Hardcoded Airtable IDs in learning module (`review/learning.py:141-142`)
- NAB parser O(2^n) complexity with no cap (`review/pdf_parsers.py:888`)
- Unbounded session data accumulation (`review/views.py:1438`)
- PII scrubbing misses exception tracebacks (`config/log_filters.py:23`)
- GitHub Actions workflow missing `permissions:` block
- OAuth URL parameters not URL-encoded (`integrations/views.py:89`)
- No rate limiting on OAuth callback endpoints
- Session tokens not cleaned on OAuth flow abandonment
- No encryption key rotation mechanism
- Users fully authenticated before 2FA completion (`accounts/views.py:49`)
- Sessions not invalidated after 2FA reset (`accounts/views.py:354`)
- InvitationForm allows admin-role creation without extra confirmation
- Invitation token format not validated before DB lookup
- Content-Disposition header injection via filenames
- `progress_percent` can return >100% (`review/models.py:86`)

---

## LOW FINDINGS (21)

- No password reset functionality anywhere in the application
- Zero test coverage (all tests.py files are empty stubs)
- `SECURE_BROWSER_XSS_FILTER` deprecated in modern browsers
- No dependency scanning in CI (no pip-audit, safety, or Trivy)
- Bank account numbers displayed unmasked in review templates
- No container security hardening in Docker Compose
- `collectstatic` errors suppressed in Dockerfile
- PII filter misses ABNs, BSBs, bank account numbers
- TFN regex matches any 9-digit number (false positives)
- No account-level lockout after failed login attempts
- TOTP `valid_window=1` triples brute-force success rate
- Signup URL leaked in admin flash message on email failure
- User enumeration via invitation form email validation
- No audit logging for security-sensitive actions in accounts app
- `xpm_sync_now` does not honor `XPM_SYNC_ENABLED` setting
- OAuth stop-rapid endpoints are state-modifying GET requests
- Airtable sync triggered on every dashboard page load
- Broad exception handling masks errors throughout codebase
- Entity matching by partial name (`icontains`) is fragile
- No duplicate bank statement detection
- Transaction dates stored as CharField not DateField
- MD5 used for cache hashing in risk engine

---

## FUNCTIONAL BUG

### MYOB Integration Will Not Work
**`integrations/providers.py:243`**

Copy-paste error: `token_url` is identical to `authorize_url`:
```python
authorize_url = "https://secure.myob.com/oauth2/v1/authorize"
token_url = "https://secure.myob.com/oauth2/v1/authorize"  # Should be /token
```

Token exchange and refresh both hit the wrong endpoint and will fail.

### Missing `anthropic` Package
**`requirements.txt`**

The `anthropic` package is not listed in requirements.txt (only `openai` is).
Claude Vision PDF extraction (`review/email_ingestion.py:29`) and AI
classification will fail with `ImportError`.

---

## KEY ROTATION WARNING

When rotating `SECRET_KEY` tomorrow:
- All existing sessions will be invalidated (expected)
- **All encrypted fields (TOTP secrets, OAuth tokens) will become unreadable**
  because encryption is derived from `SECRET_KEY` (`config/encryption.py:17`)
- The silent fallback will return garbled ciphertext as plaintext, causing
  OAuth failures and 2FA lockouts
- Recommendation: re-encrypt all encrypted fields with the new key before
  switching, or implement a key rotation mechanism

---

## PRIORITY REMEDIATION ROADMAP

### Phase 1: Immediate (Block Before Production)
1. Replace all `get_object_or_404(Entity/FY/ReviewJob)` with authorization helpers
2. Add `@require_POST` to all state-changing endpoints
3. Fix rate limiting: use REMOTE_ADDR not X-Forwarded-For
4. Remove `/admin/` from 2FA middleware exemptions
5. Make webhook auth fail-closed when secret is not set
6. Fix authorization bypass on NULL-assigned entities
7. Bind PostgreSQL to 127.0.0.1 only in docker-compose
8. Remove plaintext tokens from session storage
9. Scope notifications to the requesting user
10. Add authorization to all integrations views

### Phase 2: This Sprint
11. Fix XSS: replace innerHTML with textContent, replace |safe with json_script
12. Add prompt injection mitigations for AI classification
13. HTML-escape all values in PDF generation
14. Validate `next` URL with `url_has_allowed_host_and_scheme()`
15. Add `can_edit` permission checks to all write views
16. Wrap import commit in `transaction.atomic()`
17. Add file size/count limits to bank statement upload
18. Replace raw request.POST with Django forms
19. Add rate limiting to signup, 2FA setup, OAuth callbacks
20. Fix MYOB token_url copy-paste bug
21. Add `anthropic` to requirements.txt

### Phase 3: Short-Term
22. Replace `'unsafe-inline'` in CSP with nonce-based approach
23. Change DB SSL default to `require`
24. Add entity-level authorization to media file serving
25. Switch to `defusedxml` for XPM XML parsing
26. Exclude token fields from Django admin forms
27. Separate encryption key from SECRET_KEY; add key rotation support
28. Remove `|| true` from Bandit CI; add pip-audit / Trivy
29. Remove source mount and `--reload` from Docker Compose for production
30. Add password reset functionality
31. Write security tests
