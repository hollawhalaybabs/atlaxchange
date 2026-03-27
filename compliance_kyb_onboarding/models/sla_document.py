# -*- coding: utf-8 -*-

from odoo import fields, models, _
from odoo.exceptions import UserError


class SLADocument(models.Model):
    _name = "sla.document"
    _description = "SLA Document"
    _order = "create_date desc, id desc"

    review_id = fields.Many2one(
        "compliance.kyb.review",
        string="KYB Review",
        required=True,
        ondelete="cascade",
        index=True,
    )

    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("approved", "Approved"),
        ],
        default="draft",
        tracking=True,
    )

    sla_sent_received_attachment_ids = fields.Many2many(
        "ir.attachment",
        "sla_doc_sent_received_attachment_rel",
        "sla_doc_id",
        "attachment_id",
        string="SLA Sent/Received Document",
    )

    sla_approved_attachment_ids = fields.Many2many(
        "ir.attachment",
        "sla_doc_approved_attachment_rel",
        "sla_doc_id",
        "attachment_id",
        string="SLA Approved Document",
    )

    approved_by = fields.Many2one("hr.employee", string="Approved By", readonly=True)
    approved_on = fields.Datetime(string="Approved On", readonly=True)

    def action_approve(self):
        employee_model = self.env["hr.employee"]
        current_employee = employee_model.search([("user_id", "=", self.env.uid)], limit=1)
        if not current_employee:
            raise UserError(_("No Employee is linked to your user. Please contact an administrator."))

        for record in self:
            record.state = "approved"
            record.approved_by = current_employee
            record.approved_on = fields.Datetime.now()

        return True