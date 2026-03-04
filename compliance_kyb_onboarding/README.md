# Compliance KYB Onboarding (Odoo 16)

## What this module provides
- Internal KYB review record with checklist + attachments.
- Public onboarding URL: `/onboarding/<token>` for customers to submit KYB requirements & uploads.
- Request More Info email action (includes missing items list + onboarding link).
- Hook method `compliance.kyb.review.create_from_bd(bd_model, bd_res_id, ...)` to be called from your existing BD button.

## Install
1. Copy `compliance_kyb_onboarding` into your Odoo addons path.
2. Update apps list, install module.
3. Ensure `website` is installed and `web.base.url` is properly set.

## BD integration (example)
From your BD model button:
```python
return self.env['compliance.kyb.review'].create_from_bd(
    bd_model=self._name,
    bd_res_id=self.id,
    partner_id=self.partner_id.id if self.partner_id else None,
    company_name=self.name,
    contact_email=self.email,
)
```

## Notes
- Risk-based section is hidden on public form by default; enable in Settings > KYB Onboarding.
