from odoo import models, fields, api, _
import requests

class UpdateConversionFeeWizard(models.TransientModel):
    _name = 'update.conversion.fee.wizard'
    _description = 'Update Conversion Fee Wizard'
    _rec_name = 'partner_id'

    partner_id = fields.Many2one('res.partner', string='Partner', domain=[('is_atlax_customer', '=', True)])
    conversion_id = fields.Many2one('conversion.fee', string='Connersion Rate')
    rate_id = fields.Char(string='Rate ID', readonly=True)
    rate = fields.Float(string='Rate Amount', required=True)
    approver_id = fields.Many2one('res.users', string="Approver", required=True, domain=[('share', '=', False)])
    submitted_at = fields.Datetime(string='Submitted At', default=fields.Datetime.now, readonly=True)

    @api.onchange('partner_id', 'conversion_id')
    def _onchange_partner_or_conversion(self):
        # Priority: conversion_id, then partner_id
        if self.conversion_id:
            self.rate_id = self.conversion_id.rate_id
            self.rate = self.conversion_id.rate
            self.partner_id = self.conversion_id.partner_id
        elif self.partner_id and self.partner_id.rate_id:
            self.rate_id = self.partner_id.rate_id
            fee = self.env['conversion.fee'].search([('rate_id', '=', self.partner_id.rate_id)], limit=1)
            if fee:
                self.rate = fee.rate
            else:
                self.rate = 0.0
        else:
            self.rate_id = False
            self.rate = 0.0

    def action_submit_for_approval(self):
        """Send an email to the approver and set state to awaiting_approval in conversion.fee."""
        if not self.approver_id or not self.approver_id.partner_id.email:
            raise Exception(_("Approver must have a valid email address."))

        self.submitted_at = fields.Datetime.now()

        # Update the conversion.fee record with the new rate and set state to 'awaiting_approval'
        fee = self.env['conversion.fee'].search([('rate_id', '=', self.rate_id)], limit=1)
        if fee:
            fee.write({'rate': self.rate, 
                       'state': 'awaiting_approval',
                       'updated_at': self.submitted_at,
                       })

        template = self.env.ref('mail.email_template_data_notification_email', raise_if_not_found=False)
        mail_values = {
            'email_to': self.approver_id.partner_id.email,
            'subject': _("Conversion Fee Approval Required"),
            'body_html': _(
                "<p>Dear %s,</p>"
                "<p>A conversion fee update for partner <b>%s</b> (Rate ID: %s) is awaiting your approval.</p>"
                "<p>Proposed Rate: <b>%s</b></p>"
                "<p>Please review and approve in the system.</p>"
            ) % (
                self.approver_id.name,
                self.partner_id.display_name,
                self.rate_id or '',
                self.rate,
            ),
        }
        if template:
            template.sudo().send_mail(self.id, force_send=True, email_values=mail_values)
        else:
            self.env['mail.mail'].sudo().create(mail_values).send()

        return {'type': 'ir.actions.act_window_close'}