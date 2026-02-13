# StatementHub

A web-based financial statement preparation platform for **MC & S Pty Ltd**, built with Django, HTMX, and Bootstrap 5.

## Overview

**StatementHub** replaces the legacy Microsoft Access Ledger system with a modern, multi-user web application for preparing AASB-compliant financial statements for Australian SMEs.

### Key Features (Phase 1 — Core Engine)

- **Client & Entity Management** — Full CRUD for clients, entities (companies, trusts, partnerships, sole traders, SMSFs), and financial years
- **Trial Balance Import** — Upload Excel (.xlsx) trial balances with validation and error reporting
- **Account Mapping Engine** — Map client chart of accounts to standardised financial statement line items, with reusable mappings across years
- **Adjusting Journals** — Create and manage adjusting journal entries with automatic trial balance integration
- **Financial Statement Preview** — Real-time Income Statement and Balance Sheet preview with prior year comparatives
- **Roll Forward** — Carry closing balances forward to create new financial years automatically
- **Role-Based Access Control** — Administrator, Senior Accountant, Accountant, and View-Only roles
- **Audit Logging** — Full audit trail of all user actions
- **Status Workflow** — Draft → In Review → Reviewed → Finalised with permission-based transitions

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend | Python 3.11 / Django 5.2 |
| Frontend | HTMX + Bootstrap 5 + Bootstrap Icons |
| Database | SQLite (dev) / PostgreSQL 16 (production) |
| Forms | django-crispy-forms + crispy-bootstrap5 |
| Static Files | WhiteNoise |
| Containerisation | Docker + Docker Compose |

## Quick Start (Development)

```bash
# Clone the repository
git clone https://github.com/<your-username>/mcs-platform.git
cd mcs-platform

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set up environment
cp .env.example .env  # Edit as needed

# Run migrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Run development server
python manage.py runserver
```

## Quick Start (Docker)

```bash
docker compose up --build
```

The application will be available at `http://localhost:8000`.

## Default Test Users

| Username | Password | Role |
|----------|----------|------|
| elio | MCS-Admin-2026! | Administrator |
| harry | MCS-Senior-2026! | Senior Accountant |
| sarah | MCS-Acct-2026!! | Accountant |

## Project Structure

```
mcs-platform/
├── accounts/          # Custom user model, authentication, user management
├── config/            # Django project settings, URLs, WSGI
├── core/              # Main application: clients, entities, TB, mappings
│   ├── models.py      # Data models
│   ├── views.py       # View functions
│   ├── forms.py       # Form definitions
│   ├── urls.py        # URL routing
│   └── templatetags/  # Custom template filters
├── templates/         # HTML templates (base, accounts, core, partials)
├── static/            # CSS, JavaScript, sample files
├── media/             # Uploaded files and generated documents
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## Trial Balance Import Format

Upload a `.xlsx` file with the following columns (row 1 = header):

| Account Code | Account Name | Opening Balance | Debit | Credit |
|-------------|-------------|-----------------|-------|--------|
| 1000 | Cash at Bank - CBA | 45,230.00 | 125,000.00 | 98,500.00 |

A sample file is included at `static/sample_trial_balance.xlsx`.

## Development Phases

- [x] **Phase 1** — Core Engine (clients, entities, TB import, mapping, adjustments, preview)
- [ ] **Phase 2** — Document Generation (Word/PDF templates, conditional notes, disclosure engine)
- [ ] **Phase 3** — Intelligence Layer (AI-assisted mapping, anomaly detection, n8n AASB monitoring)
- [ ] **Phase 4** — Integration & Polish (XPM sync, Azure AD SSO, analytics dashboard)

## License

Proprietary — MC & S Pty Ltd. All rights reserved.
