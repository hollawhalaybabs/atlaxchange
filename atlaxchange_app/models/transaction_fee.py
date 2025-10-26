from odoo import models, fields, api, _
from odoo.exceptions import UserError
import requests
import logging

_logger = logging.getLogger(__name__)

class TransactionFee(models.Model):
    _name = 'transaction.fee'
    _description = 'Transaction Fee'
    _order = 'id desc'
    _rec_name = 'display_name'

    display_name = fields.Char(string='Display Name', compute='_compute_display_name', store=True)
    partner_id = fields.Many2one('res.partner', string='Partner', compute='_compute_partner_id', store=True)
    business_id = fields.Char(string='Business ID')
    user_id = fields.Char(string='User UUID')
    fee_line_ids = fields.One2many('transaction.fee.line', 'transaction_fee_id', string='Fee Lines')
    
    @api.depends('partner_id')
    def _compute_display_name(self):
        for rec in self:
            if rec.partner_id:
                rec.display_name = f"{rec.partner_id.display_name} Customer Fee"
            else:
                rec.display_name = "Default Fee"

    @api.depends('business_id', 'user_id')
    def _compute_partner_id(self):
        for rec in self:
            partner = False
            if rec.business_id:
                partner = self.env['res.partner'].search([('business_id', '=', rec.business_id)], limit=1)
            elif rec.user_id:
                partner = self.env['res.partner'].search([('user_id', '=', rec.user_id)], limit=1)
            rec.partner_id = partner

    def fetch_transaction_fees(self):
        """Fetch transaction fees from external API and update/create fee lines."""
        url = "https://api.atlaxchange.com/api/v1/admin/fees"
        api_key = self.env['ir.config_parameter'].sudo().get_param('fetch_users_api.api_key')
        api_secret = self.env['ir.config_parameter'].sudo().get_param('fetch_users_api.api_secret')

        if not api_key or not api_secret:
            _logger.error("API key or secret is missing. Set them in System Parameters.")
            raise UserError(_("API key or secret is missing. Set them in System Parameters."))

        headers = {
            "Content-Type": "application/json",
            "X-API-KEY": api_key,
            "X-API-SECRET": api_secret
        }

        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            raise UserError(_("Failed to fetch transaction fees: %s") % response.text)

        data = response.json().get('data', [])
        for rec in data:
            currency = self.env['supported.currency'].search([('currency_code', '=', rec.get('currency_code'))], limit=1)
            if not currency:
                _logger.warning(f"Currency code {rec.get('currency_code')} not found. Skipping fee_id {rec.get('fee_id')}.")
                continue  # Skip this record if currency not found

            # Find or create the parent transaction.fee record by partner/business/user
            partner = None
            if rec.get('business_id'):
                partner = self.env['res.partner'].search([('business_id', '=', rec.get('business_id'))], limit=1)
            elif rec.get('user_id'):
                partner = self.env['res.partner'].search([('user_id', '=', rec.get('user_id'))], limit=1)

            fee_parent = self.search([
                ('partner_id', '=', partner.id if partner else False),
                ('business_id', '=', rec.get('business_id')),
                ('user_id', '=', rec.get('user_id')),
            ], limit=1)
            if not fee_parent:
                fee_parent = self.create({
                    'partner_id': partner.id if partner else False,
                    'business_id': rec.get('business_id'),
                    'user_id': rec.get('user_id'),
                })

            line_vals = {
                'currency_id': rec.get('currency_id'),
                'currency_code': currency.id,
                'transfer_direction': rec.get('transfer_direction'),
                'fee_id': rec.get('fee_id'),
                'fee': rec.get('fee', 0) / 100 if rec.get('fee') is not None else 0,
                'percentage': rec.get('percentage', 0),
                'max_fee': rec.get('max_fee', 0),
                'type': rec.get('type') if rec.get('type') in ['fixed', 'percent'] else False,
                'transaction_fee_id': fee_parent.id,
            }
            # Update or create the fee line
            fee_line = self.env['transaction.fee.line'].search([
                ('transaction_fee_id', '=', fee_parent.id),
                ('fee_id', '=', rec.get('fee_id'))
            ], limit=1)
            if fee_line:
                fee_line.write(line_vals)
            else:
                self.env['transaction.fee.line'].create(line_vals)

    def action_open_update_fee_wizard(self):
        """Open the wizard to update a specific transaction fee line."""
        self.ensure_one()
        # If only one fee line, preselect it; otherwise, let user choose
        fee_line_id = self.fee_line_ids[:1].id if len(self.fee_line_ids) == 1 else False
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'update.transaction.fee.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_partner_id': self.partner_id.id,
                'default_fee_line_id': fee_line_id,
            }
        }
    
class TransactionFeeLine(models.Model):
    _name = 'transaction.fee.line'
    _description = 'Transaction Fee Line'
    _order = 'id desc'
    _rec_name = 'fee_id'

    transaction_fee_id = fields.Many2one('transaction.fee', string='Transaction Fee', ondelete='cascade', required=True)
    currency_id = fields.Char(string='Currency UUID')
    currency_code = fields.Many2one('supported.currency', string='Currency', required=True)
    transfer_direction = fields.Selection([
        ('debit', 'Debit'),
        ('credit', 'Credit')
    ], string='Transfer Direction', required=True)
    fee_id = fields.Char(string='Fee UUID', required=True)
    fee = fields.Float(string='Fee')
    percentage = fields.Float(string='Percentage')
    max_fee = fields.Float(string='Max Fee')
    type = fields.Selection([
        ('fixed', 'Fixed'),
        ('percent', 'Percent')
    ], string='Fee Type')

