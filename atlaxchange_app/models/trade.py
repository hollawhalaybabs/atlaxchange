from odoo import models, fields, api

class Trade(models.Model):
    _name = 'atlaxchange.trade'
    _description = 'Trade Process'
    _rec_name = 'name'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string="Reference", required=True, copy=False, readonly=True, default='New')
    trade_type = fields.Selection([
        ('buy', 'Buy'),
        ('sell', 'Sell')
    ], string="Trade Type", required=True)
    amount = fields.Float(string="Amount", required=True)
    vendor_rate = fields.Float(string="Vendor Rate")
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled')
    ], string="Status", default='draft', readonly=True)

    @api.model
    def create(self, vals):
        if vals.get('name', 'New') == 'New':
            vals['name'] = self.env['ir.sequence'].next_by_code('atlaxchange.trade') or 'New'
        return super(Trade, self).create(vals)

    def action_submit(self):
        self.state = 'submitted'

    def action_complete(self):
        self.state = 'completed'

    def action_cancel(self):
        self.state = 'cancelled'
