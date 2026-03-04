# -*- coding: utf-8 -*-
import secrets
from odoo import api, fields, models, _
from odoo.exceptions import UserError

class ComplianceKYBReview(models.Model):
    _name = "compliance.kyb.review"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "KYB Review"
    _order = "create_date desc, id desc"

    name = fields.Char(default=lambda self: _("New"), copy=False, readonly=True)
    partner_id = fields.Many2one("res.partner", string="Company", tracking=True)
    company_name = fields.Char(string="Business Name", tracking=True)
    trade_name = fields.Char(string="Trade Name", tracking=True)
    type = fields.Selection(
        selection=[
            ("customer_imto", "Customer (IMTO)"),
            ("payout_provider", "Payout Provider"),
            ("liquidity_provider", "Liquidity Provider"),
            ("bank", "Bank"),
            ("crypto_provider", "Crypto Provider"),
            ("msb_provider", "MSB Provider"),
        ],
        string="Partnership Type",
        tracking=True,
    )

    risk_assessment = fields.Selection(
        selection=[
            ("high", "High"),
            ("medium", "Medium"),
            ("low", "Low"),
        ],
        string="Risk Assessment",
        required=True,
        default="low",
        tracking=True,
    )
    country_id = fields.Many2one(
        "res.country",
        string="Country of Location",
        tracking=True,
    )
    contact_email = fields.Char(string="Primary Email")
    contact_phone = fields.Char(string="Primary Phone")
    contact_name = fields.Char(string="Primary Contact Name")
    contact_role = fields.Char(string="Primary Contact Role")

    bd_model = fields.Char(string="BD Model", help="Technical model name of the Business Development record.")
    bd_res_id = fields.Integer(string="BD Record ID")
    bd_id = fields.Many2one(
        "atlax.bd.opportunity",
        string="BD Opportunity",
        tracking=True,
        ondelete="set null",
        help="Business Development opportunity this KYB review is linked to.",
    )
    bd_minute_url = fields.Char(string="BD Minute Link", compute="_compute_bd_minute_url", store=False)

    state = fields.Selection([
        ("draft", "Draft"),
        ("in_review", "In Review"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ], default="draft", tracking=True)

    assigned_to = fields.Many2one(
        "hr.employee",
        tracking=True,
        default=lambda self: self.env["hr.employee"].search([("user_id", "=", self.env.uid)], limit=1),
    )
    submitted_by_email = fields.Char()
    submitted_on = fields.Datetime()
    verified_by = fields.Many2one("hr.employee")
    verified_on = fields.Datetime()
    remarks = fields.Text()

    access_token = fields.Char(copy=False, index=True)
    onboarding_url = fields.Char(compute="_compute_onboarding_url", store=False)
    is_link_active = fields.Boolean(default=True)
    link_expiry = fields.Datetime()

    requirement_line_ids = fields.One2many("compliance.kyb.requirement.line", "review_id", string="Requirements")

    nda_document_ids = fields.One2many(
        "nda.document",
        "review_id",
        string="NDA Documents",
    )

    missing_requirement_count = fields.Integer(compute="_compute_missing_requirement_count", store=False)

    @api.depends("requirement_line_ids.provided", "requirement_line_ids.attachment_ids")
    def _compute_missing_requirement_count(self):
        for rec in self:
            missing = 0
            for line in rec.requirement_line_ids:
                if not line.provided and not line.attachment_ids:
                    missing += 1
            rec.missing_requirement_count = missing

    @api.depends("access_token")
    def _compute_onboarding_url(self):
        base = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "")
        for rec in self:
            if rec.access_token:
                rec.onboarding_url = f"{base}/onboarding/{rec.access_token}"
            else:
                rec.onboarding_url = False

    @api.depends("bd_id", "bd_model", "bd_res_id")
    def _compute_bd_minute_url(self):
        base = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "")
        for rec in self:
            if rec.bd_id:
                rec.bd_minute_url = f"{base}/web#id={rec.bd_id.id}&model={rec.bd_id._name}&view_type=form"
            elif rec.bd_model and rec.bd_res_id:
                rec.bd_minute_url = f"{base}/web#id={rec.bd_res_id}&model={rec.bd_model}&view_type=form"
            else:
                rec.bd_minute_url = False

    @api.onchange("bd_id")
    def _onchange_bd_id(self):
        for rec in self:
            if rec.bd_id:
                rec.bd_model = rec.bd_id._name
                rec.bd_res_id = rec.bd_id.id

    @api.model_create_multi
    def create(self, vals_list):
        new_label = _("New")
        for vals in vals_list:
            if vals.get("name", new_label) == new_label:
                vals["name"] = self.env["ir.sequence"].next_by_code("compliance.kyb.review") or new_label
            if not vals.get("access_token"):
                vals["access_token"] = secrets.token_urlsafe(24)

            if vals.get("bd_id"):
                vals["bd_model"] = "atlax.bd.opportunity"
                vals["bd_res_id"] = vals["bd_id"]
            elif vals.get("bd_model") == "atlax.bd.opportunity" and vals.get("bd_res_id") and not vals.get("bd_id"):
                vals["bd_id"] = vals["bd_res_id"]

        records = super().create(vals_list)

        for rec in records:
            if not rec.requirement_line_ids:
                rec._generate_requirement_lines()

        return records

    def _generate_requirement_lines(self):
        templates = self.env["compliance.kyb.requirement.template"].search([("active", "=", True)])
        lines = []
        for t in templates:
            lines.append((0, 0, {
                "template_id": t.id,
                "sequence": t.sequence,
            }))
        self.write({"requirement_line_ids": lines})

    
    # -------------------
    # Buttons / Workflow
    # -------------------
    def action_start_review(self):
        for rec in self:
            rec.state = "in_review"

    def action_approve(self):
        Employee = self.env["hr.employee"]
        current_employee = Employee.search([("user_id", "=", self.env.uid)], limit=1)
        for rec in self:
            rec.state = "approved"
            rec.verified_by = current_employee
            rec.verified_on = fields.Datetime.now()

    def action_reject(self):
        Employee = self.env["hr.employee"]
        current_employee = Employee.search([("user_id", "=", self.env.uid)], limit=1)
        for rec in self:
            rec.state = "rejected"
            rec.verified_by = current_employee
            rec.verified_on = fields.Datetime.now()

    def action_request_more_info(self):
        self.ensure_one()
        if not self.contact_email:
            raise UserError(_("Primary Email is required to request more information."))
        template = self.env.ref("compliance_kyb_onboarding.mail_template_kyb_request_more_info", raise_if_not_found=False)
        if not template:
            raise UserError(_("Email template not found."))
        ctx = {
            "default_model": "compliance.kyb.review",
            "default_res_id": self.id,
            "default_use_template": bool(template.id),
            "default_template_id": template.id,
            "default_composition_mode": "comment",
            "force_email": True,

            # Allow raw recipient typing (no partner required)
            "default_partner_ids": [],
            "default_email_to": (self.contact_email or ""),
        }
        return {
            "type": "ir.actions.act_window",
            "res_model": "mail.compose.message",
            "view_mode": "form",
            "target": "new",
            "context": ctx,
        }

    def action_copy_onboarding_link(self):
        self.ensure_one()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Onboarding Link"),
                "message": self.onboarding_url or "",
                "sticky": False,
            }
        }

    def action_download_all_kyb_documents(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": f"/compliance_kyb_onboarding/kyb/{self.id}/documents.zip",
            "target": "self",
        }
