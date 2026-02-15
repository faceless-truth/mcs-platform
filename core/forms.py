"""MCS Platform - Core Forms"""
from django import forms
from .models import (
    Client, Entity, FinancialYear, AccountMapping,
    AdjustingJournal, JournalLine, ClientAccountMapping,
    EntityOfficer,
)


class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ("name", "contact_email", "contact_phone", "assigned_accountant", "xpm_client_id", "is_active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = "form-check-input"
            else:
                field.widget.attrs["class"] = "form-control"


class EntityForm(forms.ModelForm):
    class Meta:
        model = Entity
        fields = (
            "entity_name", "entity_type", "abn", "acn",
            "registration_date", "financial_year_end",
            "reporting_framework", "company_size",
        )
        widgets = {
            "registration_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"


class FinancialYearForm(forms.ModelForm):
    class Meta:
        model = FinancialYear
        fields = ("year_label", "start_date", "end_date")
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"


class TrialBalanceUploadForm(forms.Form):
    file = forms.FileField(
        help_text="Upload a .xlsx file with columns: Account Code, Account Name, Opening Balance, Debit, Credit",
        widget=forms.FileInput(attrs={"class": "form-control", "accept": ".xlsx"}),
    )


class AccountMappingForm(forms.ModelForm):
    class Meta:
        model = AccountMapping
        fields = (
            "standard_code", "line_item_label", "financial_statement",
            "statement_section", "display_order", "applicable_entities",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"


class ClientAccountMappingForm(forms.Form):
    """Form for mapping a single client account to a standard line item."""
    mapped_line_item = forms.ModelChoiceField(
        queryset=AccountMapping.objects.all(),
        required=False,
        empty_label="-- Select mapping --",
        widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
    )


class AdjustingJournalForm(forms.ModelForm):
    class Meta:
        model = AdjustingJournal
        fields = ("journal_date", "description")
        widgets = {
            "journal_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"


class JournalLineForm(forms.ModelForm):
    class Meta:
        model = JournalLine
        fields = ("account_code", "account_name", "debit", "credit")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control form-control-sm"


JournalLineFormSet = forms.inlineformset_factory(
    AdjustingJournal,
    JournalLine,
    form=JournalLineForm,
    extra=4,
    can_delete=True,
)


# ---------------------------------------------------------------------------
# Entity Officer Forms
# ---------------------------------------------------------------------------
class EntityOfficerForm(forms.ModelForm):
    class Meta:
        model = EntityOfficer
        fields = (
            "full_name", "role", "title", "date_appointed", "date_ceased",
            "is_signatory", "display_order", "profit_share_percentage",
            "distribution_percentage",
        )
        widgets = {
            "date_appointed": forms.DateInput(attrs={"type": "date"}),
            "date_ceased": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, entity_type=None, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = "form-check-input"
            else:
                field.widget.attrs["class"] = "form-control"

        # Filter role choices based on entity type
        if entity_type:
            role_map = {
                "company": [
                    EntityOfficer.OfficerRole.DIRECTOR,
                    EntityOfficer.OfficerRole.SECRETARY,
                    EntityOfficer.OfficerRole.PUBLIC_OFFICER,
                ],
                "trust": [
                    EntityOfficer.OfficerRole.TRUSTEE,
                    EntityOfficer.OfficerRole.BENEFICIARY,
                    EntityOfficer.OfficerRole.DIRECTOR,  # directors of trustee company
                ],
                "partnership": [
                    EntityOfficer.OfficerRole.PARTNER,
                ],
                "sole_trader": [
                    EntityOfficer.OfficerRole.SOLE_TRADER,
                ],
                "smsf": [
                    EntityOfficer.OfficerRole.TRUSTEE,
                    EntityOfficer.OfficerRole.DIRECTOR,  # corporate trustee directors
                ],
            }
            allowed_roles = role_map.get(entity_type, EntityOfficer.OfficerRole.choices)
            self.fields["role"].choices = [
                (r.value, r.label) for r in allowed_roles
            ]

        # Show/hide partnership and trust specific fields
        if entity_type != "partnership":
            self.fields["profit_share_percentage"].widget = forms.HiddenInput()
        if entity_type != "trust":
            self.fields["distribution_percentage"].widget = forms.HiddenInput()
