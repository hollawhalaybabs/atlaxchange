# Technical Spec (Build Notes)

## Models
- compliance.kyb.review
- compliance.kyb.requirement.template
- compliance.kyb.requirement.line

## Checklist source of truth
- data/kyb_requirement_templates.xml is seeded from the Atlax partner onboarding requirements list.

## Public onboarding
- GET/POST /onboarding/<token>
- Upload field naming convention: file_line_<requirement_line_id>
- Files saved as ir.attachment linked to compliance.kyb.review + also related on requirement line

## Workflow
- Draft -> In Review -> Approved/Rejected
- Request More Info opens mail composer with template:
  compliance_kyb_onboarding.mail_template_kyb_request_more_info

## Security
- Compliance User: manage KYB reviews and lines
- Compliance Manager: manage templates + full access

## What is intentionally not included
- Updating BD status on approve/reject (phase 2)
