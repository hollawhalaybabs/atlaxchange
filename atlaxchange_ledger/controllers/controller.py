from odoo import http
from odoo.http import request

class LedgerDashboardController(http.Controller):

    @http.route('/atlaxchange/ledger_dashboard/data', type='json', auth='user')
    def ledger_dashboard_data(self, filters=None):
        domain = []
        if filters:
            if filters.get('status'):
                domain.append(('status', '=', filters['status']))
            if filters.get('type'):
                domain.append(('type', '=', filters['type']))
            if filters.get('date_from'):
                domain.append(('datetime', '>=', filters['date_from']))
            if filters.get('date_to'):
                domain.append(('datetime', '<=', filters['date_to']))
        ledgers = request.env['atlaxchange.ledger'].sudo().search(domain)
        data = []
        for rec in ledgers:
            data.append({
                'customer': rec.partner_id.display_name,
                'currency': rec.wallet.name if rec.wallet else '',
                'amount': rec.amount,
                'fee': rec.fee,
                'status': rec.status,
                'date': rec.datetime.strftime('%Y-%m-%d %H:%M:%S') if rec.datetime else '',
                'type': rec.type,
            })
        return {'records': data}