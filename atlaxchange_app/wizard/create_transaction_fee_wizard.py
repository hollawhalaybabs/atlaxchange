from odoo import models, fields, api, _
from odoo.exceptions import UserError

class CreateTransactionFeeWizard(models.TransientModel):
    _name = 'create.transaction.fee.wizard'
    _description = 'Create Transaction Fee Wizard'
    _description = 'Wizard to create transaction fees for a customer.'

    partner_id = fields.Many2one('res.partner', string='Customer', required=True, readonly=True)
    business_id = fields.Char(string='Business ID', readonly=True)
    currency_code = fields.Many2one('supported.currency', string='Currency', required=True)
    fee = fields.Float(string='Fee', required=True)
    transfer_direction = fields.Selection(
        [('debit', 'Debit'), ('credit', 'Credit')],
        string='Transfer Direction',
        required=True,
    )
    type = fields.Selection(
        [('fixed', 'Fixed'), ('percent', 'Percent')],
        string='Fee Type',
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        partner_id = res.get('partner_id')
        if partner_id and 'business_id' in fields_list:
            partner = self.env['res.partner'].browse(partner_id)
            res['business_id'] = partner.business_id or False
        return res

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        if self.partner_id:
            self.business_id = self.partner_id.business_id or False
        else:
            self.business_id = False

    def action_create_fee(self):
        self.ensure_one()
        if not self.partner_id.is_atlax_customer:
            raise UserError(_("Only Atlax customers can have transaction fees."))

        if not self.business_id:
            raise UserError(_("This customer does not have a Business ID set."))

        currency_code = self.currency_code.currency_code
        if not currency_code:
            raise UserError(_("Selected currency must have a currency_code."))

        self.env['transaction.fee'].create_transaction_fee_for_business(
            business_id=self.business_id,
            currency_code=currency_code,
            fee=self.fee,
            transfer_direction=self.transfer_direction,
            fee_type=self.type,
        )
        return {'type': 'ir.actions.act_window_close'}