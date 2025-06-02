from odoo import models, fields, api, _
import requests
import logging
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

class CreateConversionFee(models.Model):
    _name = 'create.conversion.fee'
    _description = 'Create Conversion Fee'
    _order = 'id desc'
    _rec_name = 'partner_id'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    partner_id = fields.Many2one('res.partner', string='Partner', required=True, domain=[('is_atlax_customer', '=', True)])
    business_id = fields.Char(string='Business ID', compute='_compute_business_id', store=True)
    source_currency = fields.Many2one('supported.currency', string='Source Currency', required=True)
    target_currency = fields.Many2one('supported.currency', string='Target Currency', required=True)
    rate = fields.Float(string='Rate Amount', required=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('awaiting_approval', 'Awaiting Approval'),
        ('done', 'Done'),
        ('rejected', 'Rejected')
    ], string='Status', default='draft', required=True)
    approver_id = fields.Many2one('res.users', string="Approver", required=True, domain=[('share', '=', False)])
    submitted_at = fields.Datetime(string='Submitted At', default=fields.Datetime.now, readonly=True)
    rejection_reason = fields.Text(string='Rejection Reason', readonly=True)

    @api.depends('partner_id')
    def _compute_business_id(self):
        for rec in self:
            rec.business_id = rec.partner_id.business_id

    def action_submit_for_approval(self):
        """Send an email to the approver and set state to awaiting_approval."""
        if not self.approver_id or not self.approver_id.partner_id.email:
            raise Exception(_("Approver must have a valid email address."))

        template = self.env.ref('mail.email_template_data_notification_email', raise_if_not_found=False)
        mail_values = {
            'email_to': self.approver_id.partner_id.email,
            'subject': _("Conversion Fee Approval Required"),
            'body_html': _(
                "<p>Dear %s,</p>"
                "<p>A conversion fee creation for partner <b>%s</b> is awaiting your approval.</p>"
                "<p>Proposed Rate: <b>%s</b></p>"
                "<p>Please review and approve in the system.</p>"
            ) % (
                self.approver_id.name,
                self.partner_id.display_name,
                self.rate,
            ),
        }
        if template:
            template.sudo().send_mail(self.id, force_send=True, email_values=mail_values)
        else:
            self.env['mail.mail'].sudo().create(mail_values).send()
        self.state = 'awaiting_approval'
        return True

    def action_approve_fee(self):
        """Approve the fee, call action_create_fee, and notify the initiator."""
        self.ensure_one()
        result = self.action_create_fee()
        # Send approval email to the initiator (the user who created the record)
        initiator = self.create_uid.partner_id
        if initiator and initiator.email:
            subject = _("Conversion Rate Approved")
            body_html = _(
                "<p>Dear %s,</p>"
                "<p>Your conversion fee request for partner <b>%s</b> has been approved.</p>"
                "<p>Rate: <b>%s</b></p>"
                "<p>Regards,<br/>%s</p>"
            ) % (
                initiator.name,
                self.partner_id.display_name,
                self.rate,
                self.approver_id.name,
            )
            mail_values = {
                'email_to': initiator.email,
                'subject': subject,
                'body_html': body_html,
            }
            self.env['mail.mail'].sudo().create(mail_values).send()
        self.state = 'done'
        return result

    def action_reject_fee(self):
        """Open the rejection wizard."""
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'conversion.fee.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_fee_id': self.id}
        }

    def action_create_fee(self):
        """Create a new conversion fee via external API."""
        if not self.business_id:
            raise Exception(_("Business ID is required."))

        api_key = self.env['ir.config_parameter'].sudo().get_param('fetch_users_api.api_key')
        api_secret = self.env['ir.config_parameter'].sudo().get_param('fetch_users_api.api_secret')
        if not api_key or not api_secret:
            raise Exception(_("API key or secret is missing. Set them in System Parameters."))

        url = f"https://api.atlaxchange.com/api/v1/currency-rates/{self.business_id}"
        headers = {
            "Content-Type": "application/json",
            "X-API-KEY": api_key,
            "X-API-SECRET": api_secret
        }
        payload = {
            "business_id": self.business_id,
            "from_currency_id": self.source_currency.currency_code,
            "rate": self.rate,
            "to_currency_id": self.target_currency.currency_code
        }
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code not in (200, 201):
            raise UserError(_("Failed to create conversion fee: %s") % response.text)
        
class ConversionFee(models.Model):
    _name = 'conversion.fee'
    _description = 'Currency Conversion Fee'
    _order = 'id desc'
    _rec_name = 'name'

    name = fields.Char(string='Name', readonly=True, store=True)
    rate_id = fields.Char(string='Rate ID', readonly=True, store=True)
    partner_id = fields.Many2one('res.partner', string='Partner', readonly=True, store=True)
    business_id = fields.Char(
        string='Business ID',
        compute='_get_partner_id',
        help="Unique identifier for the business",
        store=True
    )
    source_currency = fields.Many2one('supported.currency', string='Source Currency', readonly=True, store=True)
    target_currency = fields.Many2one('supported.currency', string='Target Currency', readonly=True, store=True)
    rate = fields.Float(string='Rate Amount', readonly=True, store=True)
    updated_at = fields.Datetime(string='Updated At', readonly=True)

    @api.depends('partner_id')
    def _get_partner_id(self):
        for rec in self:
            if rec.partner_id:
                rec.business_id = rec.partner_id.business_id or False
            else:
                rec.business_id = False
        

    def fetch_conversion_fees(self):
        """Fetch conversion fees from external API and update/create records.
        Also, update res.partner's rate_id where business_id matches,
        and map the partner to partner_id in conversion.fee.
        """
        url = "https://api.atlaxchange.com/api/v1/admin/currency-rates"
        api_key = self.env['ir.config_parameter'].sudo().get_param('fetch_users_api.api_key')
        api_secret = self.env['ir.config_parameter'].sudo().get_param('fetch_users_api.api_secret')

        if not api_key or not api_secret:
            _logger.error("API key or secret is missing. Set them in System Parameters.")
            return

        headers = {
            "Content-Type": "application/json",
            "X-API-KEY": api_key,
            "X-API-SECRET": api_secret
        }

        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            raise UserError(_("Failed to fetch conversion fees: %s") % response.text)
            _logger.info("Fetched conversion fees successfully.")
            
        data = response.json().get('data', [])
        for rec in data:
            # Split rate_name to get source and target currency codes
            if '-' in rec.get('rate_name', ''):
                src_code, tgt_code = rec['rate_name'].split('-', 1)
                src_currency = self.env['supported.currency'].search([('currency_code', '=', src_code)], limit=1)
                tgt_currency = self.env['supported.currency'].search([('currency_code', '=', tgt_code)], limit=1)
            else:
                src_currency = tgt_currency = False

            business_id = rec.get('business_id', '')
            partner = self.env['res.partner'].search([('business_id', '=', business_id)], limit=1) if business_id else False

            vals = {
                'rate_id': rec.get('rate_id'),
                'source_currency': src_currency.id if src_currency else False,
                'target_currency': tgt_currency.id if tgt_currency else False,
                'rate': rec.get('rate', 0),
                'name': rec.get('rate_name', ''),
                'partner_id': partner.id if partner else False
            }
            fee = self.search([('rate_id', '=', rec.get('rate_id'))], limit=1)
            if fee:
                pass
                # fee.write(vals)
            else:
                fee = self.create(vals)

            # Update res.partner's rate_id where business_id matches
            if partner:
                partner.write({'rate_id': rec.get('rate_id')})

    def action_open_update_fee_wizard(self):
        """Open the wizard to update conversion fee."""
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'update.conversion.fee.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_conversion_id': self.id,
                'default_partner_id': self.partner_id.id,
                'default_rate_id': self.rate_id,
                'default_rate': self.rate,
            }
        }



