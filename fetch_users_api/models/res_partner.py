from odoo import models, fields, api

class ResPartner(models.Model):
    _inherit = 'res.partner'

    business_id = fields.Char(string='Business ID', help="Unique identifier for the business")
    rate_id = fields.Char(string='Rate ID', readonly=True, store=True, help="Rate ID for the partner")
    is_atlax_customer = fields.Boolean(string='Customer', default=False)
    is_email_verified = fields.Boolean(string='Is Email Verified', default=False)
    external_user_id = fields.Char(string='External User ID', help="Unique identifier for the user from the external system")
    ledger_ids = fields.One2many('account.ledger', 'partner_id', string='Ledgers')
    partner_ledger_ids = fields.One2many(
        'atlaxchange.ledger', 
        compute='_compute_partner_ledger_ids', 
        string='Partner Ledgers',
        search='_search_partner_ledger_ids'  # Add a custom search method
    )
    partner_ledger_count = fields.Integer(
        string='Ledger Count', 
        compute='_compute_partner_ledger_count'
    )

    @api.depends('name', 'company_name')
    def _compute_partner_ledger_ids(self):
        for partner in self:
            # Search for related ledger records
            ledger_records = self.env['atlaxchange.ledger'].search([
                '|',
                ('customer_name', '=', partner.name),
                ('customer_name', '=', partner.company_name)
            ])
            # Assign the IDs of the related records using the (6, 0, [ids]) format
            partner.partner_ledger_ids = [(6, 0, ledger_records.ids)]

    @api.depends('partner_ledger_ids')
    def _compute_partner_ledger_count(self):
        for partner in self:
            partner.partner_ledger_count = len(partner.partner_ledger_ids)

    @api.model
    def _search_partner_ledger_ids(self, operator, value):
        # Search for partners based on related ledger records
        ledger_partners = self.env['atlaxchange.ledger'].search([('id', operator, value)]).mapped('partner_id.id')
        return [('id', 'in', ledger_partners)]

    def action_open_partner_ledgers(self):
        """Open the ledger records for this partner."""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Partner Ledgers',
            'res_model': 'atlaxchange.ledger',
            'view_mode': 'tree,form',
            'domain': [
                '|',
                ('customer_name', '=', self.name),
                ('customer_name', '=', self.company_name)
            ],
            'context': {'default_customer_name': self.name},
        }