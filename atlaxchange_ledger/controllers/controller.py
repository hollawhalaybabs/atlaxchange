from odoo import http
from odoo.http import request
import math

class LedgerDashboardController(http.Controller):

    @http.route('/atlaxchange/ledger_dashboard/data', type='json', auth='user')
    def ledger_dashboard_data(self, filters=None, page=1, page_size=100):
        # Unpack {filters, page, page_size} payload
        if isinstance(filters, dict) and 'filters' in filters and ('page' in filters or 'page_size' in filters):
            payload = filters
            filters = payload.get('filters') or {}
            try: page = int(payload.get('page', page))
            except Exception: pass
            try: page_size = int(payload.get('page_size', page_size))
            except Exception: pass
        else:
            filters = filters or {}

        status = filters.get('status') or None
        wallet_code = filters.get('wallet') or None
        tx_ref = filters.get('reference') or None
        customer_id = filters.get('customer_id') or None
        customer_name = filters.get('customer_name') or None
        date_from = filters.get('date_from') or None
        date_to = filters.get('date_to') or None
        tx_type = filters.get('type') or None

        # Domain for list + metrics
        domain = []
        if status:
            domain.append(('status', '=', status))
        if tx_type:
            domain.append(('type', '=', tx_type))
        if date_from:
            domain.append(('datetime', '>=', date_from))
        if date_to:
            domain.append(('datetime', '<=', date_to))
        if tx_ref:
            domain.append(('transaction_reference', 'ilike', tx_ref))
        if customer_id:
            try:
                domain.append(('partner_id', '=', int(customer_id)))
            except Exception:
                pass
        elif customer_name:
            domain.append(('customer_name', 'ilike', customer_name))
        if wallet_code:
            domain.append(('wallet.currency_code', '=', wallet_code))

        Ledger = request.env['atlaxchange.ledger'].sudo()

        # Robust counts per type
        debit_domain = domain + [('type', '=', 'debit')]
        credit_domain = domain + [('type', '=', 'credit')]
        debit_count = Ledger.search_count(debit_domain)
        credit_count = Ledger.search_count(credit_domain)
        total_count = debit_count + credit_count

        # Primary aggregation via read_group
        debit_totals = Ledger.read_group(debit_domain, ['amount:sum', 'fee:sum'], [])
        credit_totals = Ledger.read_group(credit_domain, ['amount:sum', 'fee:sum'], [])
        debit_amount = float(debit_totals and debit_totals[0].get('amount_sum') or 0.0)
        debit_fee = float(debit_totals and debit_totals[0].get('fee_sum') or 0.0)
        credit_amount = float(credit_totals and credit_totals[0].get('amount_sum') or 0.0)
        credit_fee = float(credit_totals and credit_totals[0].get('fee_sum') or 0.0)

        # Fallback: if sums are implausibly zero while counts > 0, compute via SQL (handles tricky domains)
        if (debit_count + credit_count) > 0 and (debit_amount == 0 and credit_amount == 0 and debit_fee == 0 and credit_fee == 0):
            cr = request.env.cr
            where = ["TRUE"]
            params = []

            if status:
                where.append("l.status = %s"); params.append(status)
            if tx_type:
                where.append("l.type = %s"); params.append(tx_type)
            if date_from:
                where.append("l.datetime >= %s"); params.append(date_from)
            if date_to:
                where.append("l.datetime <= %s"); params.append(date_to)
            if tx_ref:
                where.append("l.transaction_reference ILIKE %s"); params.append(f"%{tx_ref}%")
            if customer_id:
                where.append("l.partner_id = %s"); params.append(int(customer_id))
            elif customer_name:
                where.append("l.customer_name ILIKE %s"); params.append(f"%{customer_name}%")
            if wallet_code:
                where.append("w.currency_code = %s"); params.append(wallet_code)

            sql = f"""
                SELECT
                    COALESCE(SUM(CASE WHEN l.type='debit' THEN l.amount END),0) AS debit_amount,
                    COALESCE(SUM(CASE WHEN l.type='credit' THEN l.amount END),0) AS credit_amount,
                    COALESCE(SUM(CASE WHEN l.type='debit' THEN l.fee END),0)    AS debit_fee,
                    COALESCE(SUM(CASE WHEN l.type='credit' THEN l.fee END),0)   AS credit_fee
                FROM atlaxchange_ledger l
                LEFT JOIN supported_currency w ON w.id = l.wallet
                WHERE {" AND ".join(where)}
            """
            cr.execute(sql, params)
            row = cr.fetchone() or (0, 0, 0, 0)
            debit_amount, credit_amount, debit_fee, credit_fee = [float(x or 0.0) for x in row]

        # Distinct customers (prefer partner_id; fallback to customer_name)
        grp_customers = Ledger.read_group(domain, ['partner_id'], ['partner_id'])
        cust_ids = [g['partner_id'][0] for g in (grp_customers or []) if g.get('partner_id')]
        customers_distinct = len(set(cust_ids)) if cust_ids else 0
        if customers_distinct == 0:
            grp_names = Ledger.read_group(domain, ['customer_name'], ['customer_name'])
            customers_distinct = len([g for g in (grp_names or []) if g.get('customer_name')])

        # Wallet + customer dropdowns
        cur_model = request.env['supported.currency'].sudo()
        wallet_recs = cur_model.search([])
        wallet_options = [{'code': c.currency_code, 'name': f"{c.currency_code} - {c.name}"} for c in wallet_recs]

        # Partner-backed options (prefer this)
        grp_all_customers = Ledger.read_group([('partner_id', '!=', False)], ['partner_id'], ['partner_id'], limit=1000)
        customer_options = []
        for g in (grp_all_customers or []):
            if g.get('partner_id'):
                pid, pname = g['partner_id']
                if pid:
                    customer_options.append({'id': pid, 'name': pname})

        # Fallback: distinct customer_name options (strings)
        customer_name_options = []
        if not customer_options:
            grp_names = Ledger.read_group([], ['customer_name'], ['customer_name'], limit=1000)
            customer_name_options = [{'name': g['customer_name']} for g in (grp_names or []) if g.get('customer_name')]

        # Pagination on filtered domain
        try: page = int(page) if page else 1
        except Exception: page = 1
        try: page_size = int(page_size) if page_size else 100
        except Exception: page_size = 100
        page = max(1, page); page_size = max(1, min(500, page_size))
        # Use ORM count (consistent with domain)
        filtered_total = Ledger.search_count(domain)
        pages = max(1, math.ceil((filtered_total or 0) / page_size))
        offset = (page - 1) * page_size

        # Records (paginated)
        ledgers = Ledger.search(domain, limit=page_size, offset=offset, order='datetime desc')
        data = [{
            'id': rec.id,
            'customer': rec.customer_name,
            'reference': rec.transaction_reference,
            'beneficiary': rec.beneficiary or '',
            'currency': rec.wallet.currency_code if rec.wallet else '',
            'dest_currency': rec.destination_currency.currency_code if rec.destination_currency else '',
            'amount': rec.amount,
            'total_amount': rec.total_amount,
            'conversion_rate': rec.conversion_rate,
            'bank': rec.bank or '',
            'fee': rec.fee,
            'status': rec.status,
            'date': rec.datetime.strftime('%Y-%m-%d %H:%M:%S') if rec.datetime else '',
            'type': rec.type,
        } for rec in ledgers]

        metrics = {
            'transactions': {
                'count': {'debit': debit_count, 'credit': credit_count, 'total': debit_count + credit_count},
                'amount': {'debit': debit_amount, 'credit': credit_amount, 'total': debit_amount + credit_amount},
            },
            'customers': customers_distinct,
            'fees': {
                'count': {'debit': debit_count, 'credit': credit_count, 'total': debit_count + credit_count},
                'amount': {'debit': debit_fee, 'credit': credit_fee, 'total': debit_fee + credit_fee},
            },
        }

        return {
            'records': data,
            'metrics': metrics,
            'wallet_options': wallet_options,
            'customer_options': customer_options,
            'customer_name_options': customer_name_options,  # NEW
            'paging': {'page': page, 'page_size': page_size, 'total': filtered_total, 'pages': pages},
        }