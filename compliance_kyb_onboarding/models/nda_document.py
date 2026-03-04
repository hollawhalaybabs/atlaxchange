# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class NDADocument(models.Model):
    _name = "nda.document"
    _description = "NDA Document"
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

    nda_sent_received_attachment_ids = fields.Many2many(
        "ir.attachment",
        "nda_doc_sent_received_attachment_rel",
        "nda_doc_id",
        "attachment_id",
        string="NDA Sent/Received Document",
    )

    nda_approved_attachment_ids = fields.Many2many(
        "ir.attachment",
        "nda_doc_approved_attachment_rel",
        "nda_doc_id",
        "attachment_id",
        string="NDA Approved Document",
    )

    approved_by = fields.Many2one("hr.employee", string="Approved By", readonly=True)
    approved_on = fields.Datetime(string="Approved On", readonly=True)

    def action_approve(self):
        Employee = self.env["hr.employee"]
        current_employee = Employee.search([("user_id", "=", self.env.uid)], limit=1)
        if not current_employee:
            raise UserError(_("No Employee is linked to your user. Please contact an administrator."))

        for rec in self:
            rec.state = "approved"
            rec.approved_by = current_employee
            rec.approved_on = fields.Datetime.now()

        return True
