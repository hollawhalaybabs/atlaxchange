from odoo import models, api

class AtlaxchangeLedgerDashboard(models.Model):
    _name = 'atlaxchange.ledger.dashboard'
    _description = 'Atlaxchange Ledger Dashboard'

    @api.model
    def get_dashboard_data(self):
        Ledger = self.env['atlaxchange.ledger']
        transactions = Ledger.search([])

        # Compute metrics
        total_transactions_count = len(transactions)
        successful_payouts = transactions.filtered(lambda t: t.status == 'success')
        pending_payouts = transactions.filtered(lambda t: t.status == 'pending')
        failed_payouts = transactions.filtered(lambda t: t.status == 'failed')

        return {
            'total_transactions_count': total_transactions_count,
            'total_successful_payouts_count': len(successful_payouts),
            'pending_payouts_count': len(pending_payouts),
            'failed_payouts_count': len(failed_payouts),
        }