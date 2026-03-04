# -*- coding: utf-8 -*-

from odoo import api, fields, models


class MailComposeMessage(models.TransientModel):
    _inherit = "mail.compose.message"

    email_to = fields.Char(
        string="To",
        help="Comma-separated recipient emails (e.g. a@x.com, b@y.com).",
    )

    def _prepare_mail_values(self, res_ids):
        """Inject raw email recipients into outgoing mail.mail values without needing res.partner."""
        values_by_res_id = super()._prepare_mail_values(res_ids)

        extra = (self.email_to or "").strip()
        if not extra:
            return values_by_res_id

        for res_id in res_ids:
            mail_vals = values_by_res_id.get(res_id)
            if not mail_vals:
                continue

            existing = (mail_vals.get("email_to") or "").strip()
            if existing:
                mail_vals["email_to"] = "%s, %s" % (existing, extra)
            else:
                mail_vals["email_to"] = extra

        return values_by_res_id