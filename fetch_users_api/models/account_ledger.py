from odoo import models, fields

class AccountLedger(models.Model):
    _name = 'account.ledger'
    _description = 'Account Ledger'

    partner_id = fields.Many2one('res.partner', string='Partner', required=True)
    currency_id = fields.Many2one('res.currency', string='Currency', required=True)
    wallet_id = fields.Char(string='Wallet ID', required=True)
    balance = fields.Float(string='Balance', required=True)