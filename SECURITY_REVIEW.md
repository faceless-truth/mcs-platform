# Security Review — StatementHub (MCS Platform)

**Date:** 2026-02-21
**Scope:** Full codebase review for handling sensitive financial data (bank statements, tax info, TFNs, phone numbers, financial statements) and commercialisation readiness.

---

## Executive Summary

StatementHub is a Django-based financial statement preparation platform that handles highly sensitive data — TFNs, bank account numbers, BSBs, ABNs, trial balances, and financial statements for Australian SMEs. The platform has **solid foundational security** (Django ORM, CSRF, TOTP 2FA, role-based access, session timeouts) but has **several critical and high-severity gaps** that must be addressed before handling real client financial data at scale or commercialising.

### Severity Legend

| Severity | Meaning |
|----------|---------|
| **CRITICAL** | Immediate risk of data breach or unauthorised access. Fix before any production use. |
| **HIGH** | Significant security gap that needs to be addressed before commercialisation. |
| **MEDIUM** | Important hardening for a commercial-grade platform. |
| **LOW** | Best practice improvements for long-term security posture. |

---

## CRITICAL Findings

### C1. `.env.docker` Committed to Git with Database Credentials

**File:** `.env.docker` (tracked in git), `docker-compose.yml`

The file `.env.docker` is tracked in git and contains:
```
SECRET_KEY=change-this-to-a-long-random-secret-key-in-production
DATABASE_URL=postgres://mcs_user:mcs_dev_password_2026@db:5432/mcs_platform
```

`docker-compose.yml` also hardcodes:
```yaml
POSTGRES_PASSWORD: mcs_dev_password_2026
DATABASE_URL: postgres://mcs_user:mcs_dev_password_2026@db:5432/mcs_platform
```

**Risk:** Anyone with access to the repository can see database credentials. The `SECRET_KEY` placeholder string in `.env.docker` could accidentally end up being used in production, which would compromise all session cookies, CSRF tokens, and password reset links.

**Fix:**
1. Add `.env.docker` to `.gitignore` and remove it from git history (`git rm --cached .env.docker`)
2. Create a `.env.docker.example` template with placeholder values
3. Use a proper secrets manager (AWS Secrets Manager, HashiCorp Vault, or at minimum environment variables injected at deployment time)
4. Generate a strong random `SECRET_KEY` for production (50+ chars)

---

### C2. OAuth2 Tokens Stored in Plain Text in Database

**Files:** `integrations/models.py:43-44`, `integrations/models.py:159-160`, `integrations/models.py:279-280`, `integrations/models.py:380-382`, `integrations/models.py:489-490`

All OAuth2 tokens (Xero, MYOB, QuickBooks, XPM) are stored as plain `TextField`:

```python
access_token = models.TextField(blank=True, default="")
refresh_token = models.TextField(blank=True, default="")
```

These tokens provide full access to client financial data in Xero, MYOB, and QuickBooks. A database breach would give an attacker access to **every connected client's accounting system**.

**Risk:** If the database is compromised (SQL injection, backup leak, insider threat), all OAuth tokens are immediately usable.

**Fix:**
1. Encrypt tokens at rest using `django-fernet-fields` or `django-encrypted-model-fields`
2. Consider storing tokens in a dedicated secrets vault rather than the application database
3. Implement token rotation policies

---

### C3. TOTP Secrets Stored in Plain Text

**File:** `accounts/models.py:32`

```python
totp_secret = models.CharField(max_length=64, blank=True, default="")
```

TOTP secrets are stored in plain text. If the database is compromised, an attacker could generate valid 2FA codes for any user, completely defeating the purpose of 2FA.

**Risk:** Complete 2FA bypass upon database compromise.

**Fix:**
1. Encrypt TOTP secrets at rest using symmetric encryption with a key stored outside the database
2. Consider using `django-otp` which has better security practices for secret storage

---

### C4. MYOB Company File Passwords Stored in Plain Text

**File:** `integrations/models.py:549-556`

```python
cf_username = models.CharField(max_length=255, blank=True, default="Administrator")
cf_password = models.CharField(max_length=255, blank=True, default="")
```

The comment says "stored encrypted in production" but there is **no encryption implementation**. These are plain `CharField` fields.

**Risk:** Direct credential exposure upon database compromise.

**Fix:**
1. Implement actual encryption for these fields
2. The comment claiming encryption is misleading and dangerous — remove it or implement it

---

### C5. Webhook Endpoint Has No Authentication

**File:** `review/views.py:894-941`

```python
@csrf_exempt
@require_POST
def notify_new_review_job(request):
```

This endpoint is `@csrf_exempt` (necessary for webhooks) but has **no authentication whatsoever** — no API key, no HMAC signature verification, no IP allowlist. Anyone on the internet can:

1. Create fake review jobs
2. Inject arbitrary `client_name` values
3. Flood the system with data

**Risk:** Unauthenticated data injection, denial of service, data pollution.

**Fix:**
1. Implement webhook signature verification (HMAC-SHA256 with a shared secret)
2. Alternatively, require a Bearer token in the `Authorization` header
3. Add IP allowlisting for the n8n server
4. Rate limit this endpoint

---

## HIGH Findings

### H1. TFN (Tax File Number) Stored in Plain Text

**File:** `core/models.py:156-159`

```python
tfn = models.CharField(
    max_length=20, blank=True, verbose_name="TFN",
    help_text="Tax File Number",
)
```

Australian TFNs are extremely sensitive — it is a **criminal offence** under the *Taxation Administration Act 1953* (Division 355) to record or disclose TFNs inappropriately. The ATO requires TFNs to be encrypted at rest and access-logged.

**Risk:** Regulatory non-compliance (potential fines), data breach consequences amplified.

**Fix:**
1. Encrypt TFN at rest (mandatory for ATO compliance)
2. Implement access logging specifically for TFN field access
3. Consider storing only a masked version (last 3 digits) as done for `ClientAssociate.tfn_last_three`
4. Display only masked TFN in the UI (e.g., `***-***-789`)
5. Restrict TFN access to Admin and Senior Accountant roles only

---

### H2. No Encryption at Rest for Sensitive Financial Data

**Files:** All model files

The platform stores bank account numbers, BSBs, ABNs, financial balances, transaction descriptions, and other sensitive data with no encryption at rest. While Django ORM prevents SQL injection, a database backup leak or server compromise would expose all client financial data in plain text.

**Affected fields include:**
- `BankAccount.bsb`, `BankAccount.account_number`
- `Entity.tfn`, `Entity.abn`, `Entity.acn`
- `Entity.contact_phone`, `Entity.contact_email`
- `ClientAssociate.phone`, `ClientAssociate.email`, `ClientAssociate.date_of_birth`
- `PendingTransaction.description`, `PendingTransaction.amount`
- `ReviewJob.bsb`, `ReviewJob.account_number`
- All `TrialBalanceLine` financial data

**Fix:**
1. At minimum, encrypt PII fields (TFN, phone, email, DOB) and banking details (BSB, account numbers)
2. Enable PostgreSQL Transparent Data Encryption (TDE) or use full-disk encryption on the database volume
3. For commercialisation, implement column-level encryption for the most sensitive fields

---

### H3. No Rate Limiting on Any Endpoint

**Files:** All URL configurations, `config/settings.py`

There is no rate limiting configured anywhere — no `django-ratelimit`, no `django-axes`, no reverse proxy rate limiting. This means:

- Login endpoint can be brute-forced
- TOTP verification can be brute-forced (only `valid_window=1` helps slightly)
- File upload endpoints can be abused
- API endpoints can be hammered

**Fix:**
1. Install `django-axes` for login attempt limiting and lockout
2. Add `django-ratelimit` to sensitive endpoints (login, 2FA verify, file upload, webhook)
3. Configure rate limiting at the reverse proxy level (nginx, CloudFlare, etc.)
4. Implement account lockout after N failed login attempts

---

### H4. No Object-Level Authorization (IDOR Vulnerability)

**Files:** `core/views.py`, `review/views.py`, `integrations/views.py`

Views use `get_object_or_404` with just a PK lookup — there is **no check** that the requesting user has permission to access that specific entity/financial year/journal. For example:

```python
@login_required
def entity_detail(request, pk):
    entity = get_object_or_404(Entity, pk=pk)  # No ownership check
```

```python
@login_required
def review_detail(request, pk):
    job = get_object_or_404(ReviewJob, pk=pk)  # No ownership check
```

An authenticated user (even `read_only` role) can access ANY entity, financial year, or review job by guessing/enumerating UUIDs.

**Risk:** Horizontal privilege escalation — any authenticated user can view all client data.

**Fix:**
1. Implement a mixin or decorator that checks the user's assigned entities
2. For non-admin users, filter queries by `assigned_accountant` or client assignments
3. Example pattern:
   ```python
   def get_entity_or_403(request, pk):
       entity = get_object_or_404(Entity, pk=pk)
       if not request.user.is_admin and entity.assigned_accountant != request.user:
           raise PermissionDenied
       return entity
   ```

---

### H5. File Upload Has No File Type Validation or Size Limits

**Files:** `review/views.py:532-700`, `core/views.py` (trial balance upload)

The bank statement upload endpoint reads the file content directly with no validation:

```python
content = uploaded_file.read()  # No size limit
filename = uploaded_file.name   # No extension validation
if filename.lower().endswith(".pdf"):
    extracted = extract_transactions_from_pdf_direct(content, filename)
else:
    extracted = _parse_excel_bank_statement(content, filename)
```

There is no `FILE_UPLOAD_MAX_MEMORY_SIZE` or `DATA_UPLOAD_MAX_MEMORY_SIZE` configured in settings. Django defaults to 2.5MB in memory, but there is no explicit cap on total upload size.

**Risks:**
- Memory exhaustion via large file uploads
- Malicious PDF files could exploit `pdfplumber` vulnerabilities
- No content-type validation (relies solely on file extension)

**Fix:**
1. Set `FILE_UPLOAD_MAX_MEMORY_SIZE` and `DATA_UPLOAD_MAX_MEMORY_SIZE` in settings
2. Validate file content type using `python-magic` (not just extension)
3. Set explicit file size limits (e.g., 20MB for bank statements)
4. Run PDF processing in a sandboxed environment
5. Scan uploaded files for malware if commercialising

---

### H6. Media Files Served Without Access Control

**File:** `config/settings.py:112-113`

```python
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
```

Generated financial statements (Word/PDF), uploaded templates, and any other media files are served directly from the filesystem. In production with WhiteNoise, media files may not be served at all, but if a web server is configured to serve `/media/`, **any generated financial statement document is accessible without authentication** if someone knows or guesses the URL.

**Fix:**
1. Never serve media files directly via the web server
2. Serve media files through a Django view with `@login_required` and authorization checks
3. Use signed URLs with expiration for document downloads
4. Store generated documents in a private S3 bucket (or equivalent) with presigned URLs

---

### H7. Error Messages Leak Internal Details

**Files:** `review/views.py:939`, `accounts/views.py:203`

```python
return JsonResponse({"status": "error", "message": str(e)}, status=400)
```

```python
messages.warning(
    request,
    f"Invitation created but email could not be sent ({e}). "
    f"You can share the signup link manually: {signup_url}"
)
```

Exception messages are returned directly to clients, potentially leaking internal paths, database schema info, or API keys in error messages.

**Fix:**
1. Log detailed errors server-side
2. Return generic error messages to clients
3. Never include `str(e)` in user-facing responses

---

## MEDIUM Findings

### M1. TOTP Secret Displayed in Signup Page Template Context

**File:** `accounts/views.py:283`

```python
return render(request, "accounts/invitation_signup.html", {
    "form": form,
    "invitation": invitation,
    "qr_base64": qr_base64,
    "totp_secret": totp_secret,  # Raw secret sent to template
})
```

The raw TOTP secret is passed to the template for manual entry. While this is common practice, the secret is visible in the page source and could be captured by browser extensions or XSS.

**Fix:**
1. Only show the QR code by default
2. Reveal the manual secret behind a "show" button with a JavaScript toggle
3. Mark the secret display as sensitive (don't cache, set `autocomplete="off"`)

---

### M2. No HTTPS Enforcement in Development / Missing HSTS

**File:** `config/settings.py:182-187`

Security headers are only enabled when `DEBUG=False`:
```python
if not DEBUG:
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_SSL_REDIRECT = True
    CSRF_COOKIE_SECURE = True
    X_FRAME_OPTIONS = "DENY"
```

Missing from production config:
- `SECURE_HSTS_SECONDS` (HTTP Strict Transport Security)
- `SECURE_HSTS_INCLUDE_SUBDOMAINS`
- `SECURE_HSTS_PRELOAD`
- `SESSION_COOKIE_SAMESITE`

**Fix:**
Add to the `if not DEBUG` block:
```python
SECURE_HSTS_SECONDS = 31536000  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
```

---

### M3. No Audit Logging for Data Access (Only Mutations)

**Files:** `core/views.py:28-37`, `core/models.py:944-979`

The `AuditLog` model tracks actions like login, import, adjustment, generate, and status_change — but **does not log data reads**. For a platform handling financial data, you need to know who viewed which client's data.

**Fix:**
1. Add "view" as an `AuditLog.Action` choice
2. Log access to entity detail, financial year detail, and trial balance views
3. For TFN access, this is particularly important for ATO compliance
4. Consider Django middleware for automatic access logging

---

### M4. Session Fixation Risk on 2FA Login

**File:** `accounts/views.py:70-72`

```python
del request.session["2fa_user_pk"]
next_url = request.session.pop("2fa_next", "")
auth_login(request, user)
```

While Django's `auth_login()` does cycle the session key, the session is not explicitly flushed before storing `2fa_user_pk`. If an attacker can set a session cookie before the user logs in, they could potentially hijack the session.

**Fix:**
1. Call `request.session.flush()` at the start of the login process
2. Ensure `request.session.cycle_key()` is called explicitly on successful 2FA

---

### M5. 2FA Is Optional, Not Mandatory

**File:** `accounts/views.py:41-49`

```python
def form_valid(self, form):
    user = form.get_user()
    if user.has_2fa:
        # Store user pk in session for 2FA step
        ...
    # No 2FA — log in directly
    return super().form_valid(form)
```

Users without 2FA configured can log in with just username + password. For a platform handling financial data, 2FA should be mandatory.

**Fix:**
1. Require 2FA setup before granting access to any financial data
2. After login without 2FA, redirect to a mandatory 2FA setup page
3. Admin-created users should be required to set up 2FA on first login

---

### M6. Airtable Base IDs and Table IDs Hardcoded

**File:** `review/views.py:31-34`

```python
AIRTABLE_BASE_ID = "appCIoC2AVqJ3axMG"
AIRTABLE_PENDING_TABLE = "tbl9XbFuVooVtBu2G"
AIRTABLE_JOBS_TABLE = "tblVXkcc3wFQCvQyv"
AIRTABLE_LEARNING_TABLE = "tblDO2k2wB3OSFBxa"
```

While these aren't secrets, they are environment-specific configuration that should be in settings, not hardcoded.

**Fix:**
Move to `settings.py` and source from environment variables.

---

### M7. Docker Container Runs as Root

**File:** `Dockerfile`

The Dockerfile does not create a non-root user. The gunicorn process runs as root inside the container.

**Fix:**
```dockerfile
RUN addgroup --system app && adduser --system --group app
USER app
```

---

### M8. No Content Security Policy (CSP) Header

**File:** `config/settings.py`

There is no Content Security Policy configured. CSP prevents XSS attacks by controlling which resources the browser can load.

**Fix:**
1. Install `django-csp`
2. Configure a strict CSP that allows only your own domain and trusted CDNs
3. Example: `CSP_DEFAULT_SRC = ("'self'",)`

---

### M9. `confirm_transaction` Parses Raw JSON Body Without Validation

**File:** `review/views.py:362-373`

```python
data = json.loads(request.body)
txn.confirmed_code = data.get("confirmed_code", "")
txn.confirmed_name = data.get("confirmed_name", "")
txn.confirmed_tax_type = data.get("confirmed_tax_type", "")
```

User-supplied JSON is written directly to the database without any validation of field lengths or content.

**Fix:**
1. Validate all inputs using Django forms or a serializer
2. Check that `confirmed_code` matches a valid account code from the chart of accounts
3. Check that `confirmed_tax_type` is one of the valid choices
4. Enforce max lengths

---

## LOW Findings

### L1. No Automated Security Testing

The project has `tests.py` files but they appear empty or minimal. For a financial platform, automated security tests are essential.

**Fix:**
1. Add authentication/authorization tests
2. Add IDOR test cases
3. Add input validation tests
4. Integrate OWASP ZAP or Bandit into CI/CD

---

### L2. Password Validation on Signup Form is Client-Side Only

**File:** `accounts/forms.py:117-118`

```python
if p1 and len(p1) < 12:
    self.add_error("password1", "Password must be at least 12 characters.")
```

This is good, but the form doesn't call Django's `AUTH_PASSWORD_VALIDATORS` (which check similarity, common passwords, and numeric-only). The settings have these validators configured, but `InvitationSignupForm` doesn't use `UserCreationForm` which would apply them automatically.

**Fix:**
1. Call `validate_password(p1, user=None)` in the form's `clean` method
2. Or convert `InvitationSignupForm` to inherit from `UserCreationForm`

---

### L3. Logging May Contain Sensitive Data

**Files:** `review/views.py`, `review/email_ingestion.py`

```python
logger.info(f"Processing file: {filename} ({len(content)} bytes)")
logger.info(f"Processing bank statement for {client_name} ...")
```

Log messages include client names, filenames, and transaction counts. Depending on log storage, this could leak PII.

**Fix:**
1. Audit all log statements for PII
2. Use structured logging with PII redaction
3. Ensure logs are stored securely with appropriate access controls

---

### L4. CSRF Trusted Origins Includes Wildcard Domain

**File:** `config/settings.py:134-138`

```python
CSRF_TRUSTED_ORIGINS = [
    "https://*.manus.computer",
    ...
]
```

The `*.manus.computer` wildcard is overly permissive and appears to be a development/staging domain.

**Fix:**
Remove development origins from production configuration. Use environment variables for `CSRF_TRUSTED_ORIGINS`.

---

### L5. Database Connection Pool Not Secured

**File:** `config/settings.py:78`

```python
DATABASES["default"]["CONN_MAX_AGE"] = int(os.environ.get("DB_CONN_MAX_AGE", 600))
```

The database connection uses no SSL/TLS. In production, PostgreSQL connections should use SSL.

**Fix:**
Add to database configuration:
```python
DATABASES["default"]["OPTIONS"] = {"sslmode": "require"}
```

---

## Commercialisation Readiness Checklist

For commercialisation, the following additional items are needed beyond the security fixes above:

| Item | Status | Priority |
|------|--------|----------|
| Encryption at rest for PII | Missing | Required |
| Multi-tenancy / data isolation | Partial (role-based, no tenant isolation) | Required |
| SOC 2 compliance preparation | Not started | Required for enterprise clients |
| Data retention and deletion policies | Not implemented | Required (Privacy Act) |
| Backup encryption | Not configured | Required |
| Penetration testing | Not done | Required before launch |
| Privacy policy and terms of service | Not present | Required |
| Data Processing Agreement template | Not present | Required for clients |
| Incident response plan | Not documented | Required |
| Vulnerability disclosure policy | Not present | Recommended |
| Security headers (CSP, HSTS, etc.) | Partially implemented | Required |
| API authentication framework | Not implemented | Required if exposing APIs |
| Rate limiting and DDoS protection | Not implemented | Required |
| Log monitoring and alerting | Not implemented | Required |
| Regular dependency updates/audit | No Dependabot/Snyk | Required |
| Database SSL connections | Not configured | Required |
| Container security scanning | Not configured | Recommended |
| Australian Privacy Principles (APPs) compliance | Not assessed | Required |
| TFN handling compliance (TAA 1953 Div 355) | Non-compliant | Required |

---

## Recommended Priority Order

1. **Immediately (before any production use):**
   - C1: Remove credentials from git
   - C2: Encrypt OAuth tokens
   - C3: Encrypt TOTP secrets
   - C4: Encrypt MYOB passwords
   - C5: Authenticate the webhook endpoint
   - H1: Encrypt TFNs / ensure compliance

2. **Before commercialisation:**
   - H2: Encryption at rest for sensitive fields
   - H3: Rate limiting
   - H4: Object-level authorization
   - H5: File upload validation
   - H6: Secure media file serving
   - H7: Generic error messages
   - M2: HSTS and security headers
   - M5: Mandatory 2FA
   - M7: Non-root Docker container
   - M8: Content Security Policy

3. **Ongoing improvements:**
   - All LOW findings
   - Automated security testing
   - Penetration testing
   - Compliance documentation
