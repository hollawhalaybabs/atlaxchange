from odoo import models, fields, api, _
from odoo.exceptions import UserError
import requests
import logging

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
    # Change approver_id to approver_ids (many2many)
    approver_ids = fields.Many2many(
        'res.users',
        'conversion_fee_approver_rel',
        'conversion_fee_id',
        'user_id',
        string="Approvers",
        required=True,
        domain=[('share', '=', False)]
    )
    submitted_at = fields.Datetime(string='Submitted At', default=fields.Datetime.now, readonly=True)
    rejection_reason = fields.Text(string='Rejection Reason', readonly=True)

    @api.depends('partner_id')
    def _compute_business_id(self):
        for rec in self:
            rec.business_id = rec.partner_id.business_id

    def action_submit_for_approval(self):
        """Send an email to all approvers and set state to awaiting_approval."""
        if not self.approver_ids:
            raise UserError(_("At least one approver must be set."))
        for approver in self.approver_ids:
            if not approver.partner_id.email:
                raise UserError(_("Approver %s must have a valid email address.") % approver.name)

        for approver in self.approver_ids:
            template = self.env.ref('mail.email_template_data_notification_email', raise_if_not_found=False)
            mail_values = {
                'email_to': approver.partner_id.email,
                'subject': _("Conversion Fee Approval Required"),
                'body_html': _(
                    "<p>Dear %s,</p>"
                    "<p>A conversion fee creation for partner <b>%s</b> is awaiting your approval.</p>"
                    "<p>Proposed Rate: <b>%s</b></p>"
                    "<p>Please review and approve in the system.</p>"
                ) % (
                    approver.name,
                    self.partner_id.display_name,
                    self.rate,
                ),
            }
            if template:
                template.sudo().send_mail(self.id, force_send=True, email_values=mail_values)
            else:
                try:
                    self.env['mail.mail'].sudo().create(mail_values).send()
                except Exception as e:
                    _logger.error(f"Mail send failed: {e}")
        self.state = 'awaiting_approval'
        return True

    def action_approve_fee(self):
        """Approve the fee, call action_create_fee, and notify the initiator."""
        self.ensure_one()
        # Check if the current user is one of the approvers
        if self.env.user not in self.approver_ids:
            raise UserError(_("Only an assigned approver can approve this fee."))

        result = self.action_create_fee()
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
                self.env.user.name,
            )
            mail_values = {
                'email_to': initiator.email,
                'subject': subject,
                'body_html': body_html,
            }
            try:
                self.env['mail.mail'].sudo().create(mail_values).send()
            except Exception as e:
                _logger.error(f"Mail send failed: {e}")
        self.state = 'done'
        return result

    def action_reject_fee(self):
        """Open the rejection wizard. Only an assigned approver can reject."""
        self.ensure_one()
        if self.env.user not in self.approver_ids:
            raise UserError(_("Only an assigned approver can reject this fee."))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'conversion.fee.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_fee_id': self.id}
        }

    def action_create_fee(self):
        """Create a new conversion fee via external API."""
        api_key = self.env['ir.config_parameter'].sudo().get_param('fetch_users_api.api_key')
        api_secret = self.env['ir.config_parameter'].sudo().get_param('fetch_users_api.api_secret')
        if not api_key or not api_secret:
            raise Exception(_("API key or secret is missing. Set them in System Parameters."))

        if not self.business_id or not self.source_currency or not self.target_currency or not self.rate:
            raise UserError(_("All fields are required to create a conversion fee."))

        url = "https://api.atlaxchange.com/api/v1/currency-rates"
        headers = {
            "Content-Type": "application/json",
            "X-API-KEY": api_key,
            "X-API-SECRET": api_secret
        }
        payload = {
            "business_id": self.business_id,
            "from_currency_code": self.source_currency.currency_code,
            "to_currency_code": self.target_currency.currency_code,
            "rate": int(self.rate)
        }
        _logger.info(f"Payload sent to API: {payload}")
        response = requests.post(url, headers=headers, json=payload)
        _logger.info(f"API response: {response.status_code} {response.text}")
        if response.status_code not in (200, 201):
            raise UserError(_("Failed to create conversion fee: %s") % response.text)
        
class ConversionFee(models.Model):
    _name = 'conversion.fee'
    _description = 'Currency Conversion Fee'
    _order = 'id desc'
    _rec_name = 'display_name'

    partner_id = fields.Many2one('res.partner', string='Partner', readonly=True, store=True)
    business_id = fields.Char(string='Business ID', compute='_compute_business_id', store=True)
    rate_line_ids = fields.One2many('conversion.fee.rate.line', 'conversion_fee_id', string='Rates')
    display_name = fields.Char(string='Display Name', compute='_compute_display_name', store=True)

    @api.depends('partner_id')
    def _compute_business_id(self):
        for rec in self:
            rec.business_id = rec.partner_id.business_id if rec.partner_id else False

    @api.depends('partner_id')
    def _compute_display_name(self):
        for rec in self:
            if rec.partner_id:
                rec.display_name = f"{rec.partner_id.display_name} Conversion Rate"
            else:
                rec.display_name = "Default Conversion Rate"

    def fetch_conversion_fees(self):
        """Fetch conversion fees from external API and update/create records."""
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
                'rate_name': rec.get('rate_name'),  # <-- Add this line
                'source_currency': src_currency.id if src_currency else False,
                'target_currency': tgt_currency.id if tgt_currency else False,
                'rate': rec.get('rate', 0),
            }
            fee = self.search([('partner_id', '=', partner.id if partner else False)], limit=1)
            if not fee:
                fee = self.create({'partner_id': partner.id if partner else False})
            # Update or create rate line
            line = self.env['conversion.fee.rate.line'].search([
                ('conversion_fee_id', '=', fee.id),
                ('rate_id', '=', rec.get('rate_id'))
            ], limit=1)
            if line:
                line.write(vals)
            else:
                vals['conversion_fee_id'] = fee.id
                self.env['conversion.fee.rate.line'].create(vals)

            # Optionally update res.partner's rate_id
            if partner:
                partner.write({'rate_id': rec.get('rate_id')})

    def action_open_update_fee_wizard(self):
        """Open the wizard to update a specific conversion fee rate line."""
        self.ensure_one()
        # If only one rate line, preselect it; otherwise, let user choose
        rate_line_id = self.rate_line_ids[:1].id if len(self.rate_line_ids) == 1 else False
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'update.conversion.fee.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_conversion_id': self.id,
                'default_partner_id': self.partner_id.id,
                'default_rate_line_id': rate_line_id,
            }
        }

class ConversionFeeRateLine(models.Model):
    _name = 'conversion.fee.rate.line'
    _description = 'Conversion Fee Rate Line'
    _order = 'id desc'
    _rec_name = 'rate_id'

    conversion_fee_id = fields.Many2one('conversion.fee', string='Conversion Fee', ondelete='cascade')
    rate_id = fields.Char(string='Rate ID', readonly=True, store=True)
    rate_name = fields.Char(string='Rate Name', store=True)  # <-- Added field
    source_currency = fields.Many2one('supported.currency', string='Source Currency', readonly=True, store=True)
    target_currency = fields.Many2one('supported.currency', string='Target Currency', readonly=True, store=True)
    rate = fields.Float(string='Rate Amount', readonly=True, store=True)
    updated_at = fields.Datetime(string='Updated At', readonly=True)



