from odoo import models, fields, api, _

class ConversionFeeRejectWizard(models.TransientModel):
    _name = 'conversion.fee.reject.wizard'
    _description = 'Reject Conversion Fee Wizard'

    fee_id = fields.Many2one('create.conversion.fee', string='Conversion Fee', required=True)
    reason = fields.Text(string='Reason', required=True)

    def action_reject(self):
        self.ensure_one()
        fee = self.fee_id
        fee.state = 'rejected'
        fee.rejection_reason = self.reason
        # Notify the initiator
        initiator = fee.create_uid.partner_id
        if initiator and initiator.email:
            subject = _("Conversion Rate Rejected")
            body_html = _(
                "<p>Dear %s,</p>"
                "<p>Your conversion rate request for partner <b>%s</b> has been rejected.</p>"
                "<p>Reason: <b>%s</b></p>"
                "<p>Regards,<br/>%s</p>"
            ) % (
                initiator.name,
                fee.partner_id.display_name,
                self.reason,
                fee.approver_id.name,
            )
            mail_values = {
                'email_to': initiator.email,
                'subject': subject,
                'body_html': body_html,
            }
            fee.env['mail.mail'].sudo().create(mail_values).send()
        return {'type': 'ir.actions.act_window_close'}