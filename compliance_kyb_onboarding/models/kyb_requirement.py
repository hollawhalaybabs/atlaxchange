# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError

class ComplianceKYBRequirementTemplate(models.Model):
    _name = "compliance.kyb.requirement.template"
    _description = "KYB Requirement Template"
    _order = "sequence, id"

    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    section = fields.Selection([
        ("corporate", "Corporate"),
        ("ownership", "Ownership"),
        ("kyc", "KYC (Directors/Shareholders/UBO)"),
        ("signatory", "Authorized Signatories/Contacts"),
        ("compliance", "Compliance"),
        ("tax", "Tax"),
        ("financial", "Financial"),
        ("legal", "Legal"),
        ("risk", "Risk-based (If Applicable)"),
    ], required=True, default="corporate")
    name = fields.Char(string="Requirement", required=True)
    description = fields.Text()
    is_optional = fields.Boolean(default=False, help="If checked, this requirement is optional / conditional.")
    show_on_public_form = fields.Boolean(default=True, help="If unchecked, this requirement won't appear on /onboarding.")
    internal_only = fields.Boolean(default=False)

class ComplianceKYBRequirementLine(models.Model):
    _name = "compliance.kyb.requirement.line"
    _description = "KYB Requirement Line"
    _order = "sequence, id"

    review_id = fields.Many2one("compliance.kyb.review", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    section = fields.Selection(related="template_id.section", store=True, readonly=True)
    requirement_name = fields.Char(related="template_id.name", store=True, readonly=True)
    template_id = fields.Many2one("compliance.kyb.requirement.template", required=True)
    provided = fields.Boolean(string="Provided", help="Marked true when a document is uploaded or item is provided.")
    verified_by = fields.Many2one("hr.employee")
    date = fields.Date()
    remarks = fields.Char()
    attachment_ids = fields.Many2many(
        "ir.attachment",
        "compliance_kyb_req_line_attachment_rel",
        "line_id",
        "attachment_id",
        string="Attachments",
    )

    attachment_count = fields.Integer(compute="_compute_attachment_count", store=False)

    @api.depends("attachment_ids")
    def _compute_attachment_count(self):
        for rec in self:
            rec.attachment_count = len(rec.attachment_ids)

    def action_mark_verified(self):
        Employee = self.env["hr.employee"]
        current_employee = Employee.search([("user_id", "=", self.env.uid)], limit=1)
        if not current_employee:
            raise UserError(_("No Employee is linked to your user. Please contact an administrator."))
        for rec in self:
            rec.verified_by = current_employee
            rec.date = fields.Date.today()

    @api.constrains("template_id")
    def _check_unique_template(self):
        for rec in self:
            dup = self.search_count([
                ("review_id", "=", rec.review_id.id),
                ("template_id", "=", rec.template_id.id),
                ("id", "!=", rec.id),
            ])
            if dup:
                raise ValidationError(_("Duplicate requirement line for the same template is not allowed."))
