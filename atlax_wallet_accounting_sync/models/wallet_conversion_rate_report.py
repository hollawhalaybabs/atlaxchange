import base64
from io import BytesIO

from odoo import _, fields, models, tools
from odoo.exceptions import UserError


class WalletConversionRateReport(models.Model):
    _name = "wallet.conversion.rate.report"
    _description = "Wallet Conversion Rate Report"
    _auto = False
    _order = "period_type, period_start desc, pair_name, partner_id"
    _rec_name = "pair_name"

    period_type = fields.Selection(
        [
            ("day", "Daily"),
            ("week", "Weekly"),
            ("month", "Monthly"),
        ],
        string="Period Type",
        readonly=True,
    )
    period_start = fields.Date(string="Period Start", readonly=True)
    period_end = fields.Date(string="Period End", readonly=True)
    partner_id = fields.Many2one("res.partner", string="Customer", readonly=True)
    source_currency_id = fields.Many2one("supported.currency", string="Source Currency", readonly=True)
    destination_currency_id = fields.Many2one("supported.currency", string="Destination Currency", readonly=True)
    pair_name = fields.Char(string="Currency Pair", readonly=True)
    average_conversion_rate = fields.Integer(string="Average Conversion Rate", readonly=True, digits=(16, 0))
    transaction_count = fields.Integer(string="Transactions", readonly=True)
    source_amount_total = fields.Float(string="Source Amount Total", readonly=True, digits=(16, 2))
    destination_amount_total = fields.Float(string="Destination Amount Total", readonly=True, digits=(16, 2))

    def _export_xlsx_filename(self):
        today = fields.Date.context_today(self)
        return f"wallet_conversion_rate_report_{today}.xlsx"

    def action_export_xlsx(self):
        records = self.sorted(lambda rec: (rec.period_start or fields.Date.today(), rec.partner_id.id, rec.pair_name or ""))
        if not records:
            raise UserError(_("Select at least one conversion rate row to export."))

        try:
            import xlsxwriter
        except ImportError as exc:
            raise UserError(_("xlsxwriter is required to export this report.")) from exc

        output = BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        worksheet = workbook.add_worksheet("Conversion Rates")

        header_format = workbook.add_format({"bold": True, "bg_color": "#D9EAF7", "border": 1})
        text_format = workbook.add_format({"border": 1})
        integer_format = workbook.add_format({"border": 1, "num_format": "0"})
        amount_format = workbook.add_format({"border": 1, "num_format": "#,##0.00"})
        date_format = workbook.add_format({"border": 1, "num_format": "yyyy-mm-dd"})

        headers = [
            _("Period Type"),
            _("Period Start"),
            _("Period End"),
            _("Customer"),
            _("Currency Pair"),
            _("Source Currency"),
            _("Destination Currency"),
            _("Average Conversion Rate"),
            _("Transactions"),
            _("Source Amount Total"),
            _("Destination Amount Total"),
        ]
        for column, header in enumerate(headers):
            worksheet.write(0, column, header, header_format)

        period_labels = dict(self._fields["period_type"].selection)
        for row_index, record in enumerate(records, start=1):
            worksheet.write(row_index, 0, period_labels.get(record.period_type, record.period_type or ""), text_format)
            worksheet.write_datetime(row_index, 1, fields.Date.to_date(record.period_start), date_format)
            worksheet.write_datetime(row_index, 2, fields.Date.to_date(record.period_end), date_format)
            worksheet.write(row_index, 3, record.partner_id.display_name or "", text_format)
            worksheet.write(row_index, 4, record.pair_name or "", text_format)
            worksheet.write(row_index, 5, record.source_currency_id.currency_code or "", text_format)
            worksheet.write(row_index, 6, record.destination_currency_id.currency_code or "", text_format)
            worksheet.write_number(row_index, 7, int(record.average_conversion_rate or 0), integer_format)
            worksheet.write_number(row_index, 8, int(record.transaction_count or 0), integer_format)
            worksheet.write_number(row_index, 9, record.source_amount_total or 0.0, amount_format)
            worksheet.write_number(row_index, 10, record.destination_amount_total or 0.0, amount_format)

        worksheet.set_column(0, 0, 14)
        worksheet.set_column(1, 2, 14)
        worksheet.set_column(3, 4, 28)
        worksheet.set_column(5, 6, 18)
        worksheet.set_column(7, 8, 18)
        worksheet.set_column(9, 10, 20)
        workbook.close()

        attachment = self.env["ir.attachment"].create(
            {
                "name": self._export_xlsx_filename(),
                "type": "binary",
                "datas": base64.b64encode(output.getvalue()),
                "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            }
        )
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
            "target": "self",
        }

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(
            f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                WITH customer_partners AS (
                    SELECT DISTINCT ON (LOWER(BTRIM(name)))
                        id,
                        LOWER(BTRIM(name)) AS normalized_name
                    FROM res_partner
                    WHERE is_atlax_customer = TRUE
                      AND COALESCE(parent_id, 0) = 0
                      AND name IS NOT NULL
                    ORDER BY LOWER(BTRIM(name)), create_date ASC NULLS LAST, id ASC
                ),
                base AS (
                    SELECT
                        ledger.id,
                        COALESCE(ledger.partner_id, customer_partners.id) AS partner_id,
                        ledger.wallet AS source_currency_id,
                        ledger.destination_currency AS destination_currency_id,
                        ledger.datetime,
                        ledger.amount,
                        ledger.total_amount,
                        ledger.conversion_rate
                    FROM atlaxchange_ledger ledger
                    LEFT JOIN customer_partners
                        ON customer_partners.normalized_name = LOWER(BTRIM(ledger.customer_name))
                    JOIN res_partner partner
                        ON partner.id = COALESCE(ledger.partner_id, customer_partners.id)
                    WHERE ledger.status = 'success'
                      AND ledger.transfer_direction = 'debit'
                      AND partner.is_atlax_customer = TRUE
                      AND ledger.wallet IS NOT NULL
                      AND ledger.destination_currency IS NOT NULL
                      AND COALESCE(ledger.conversion_rate, 0) > 0
                ),
                periods AS (
                    SELECT 'day' AS period_type
                    UNION ALL SELECT 'week'
                    UNION ALL SELECT 'month'
                ),
                expanded AS (
                    SELECT
                        periods.period_type,
                        base.partner_id,
                        base.source_currency_id,
                        base.destination_currency_id,
                        CASE
                            WHEN periods.period_type = 'day' THEN date_trunc('day', base.datetime)
                            WHEN periods.period_type = 'week' THEN date_trunc('week', base.datetime)
                            ELSE date_trunc('month', base.datetime)
                        END AS period_start,
                        base.amount,
                        base.total_amount,
                        base.conversion_rate
                    FROM base
                    CROSS JOIN periods
                )
                SELECT
                    row_number() OVER (
                        ORDER BY expanded.period_type, expanded.period_start DESC, expanded.partner_id, expanded.source_currency_id, expanded.destination_currency_id
                    ) AS id,
                    expanded.period_type,
                    expanded.period_start::date AS period_start,
                    CASE
                        WHEN expanded.period_type = 'day' THEN expanded.period_start::date
                        WHEN expanded.period_type = 'week' THEN (expanded.period_start + interval '6 day')::date
                        ELSE (expanded.period_start + interval '1 month - 1 day')::date
                    END AS period_end,
                    expanded.partner_id,
                    expanded.source_currency_id,
                    expanded.destination_currency_id,
                    CONCAT(source_currency.currency_code, '-', destination_currency.currency_code) AS pair_name,
                    ROUND(AVG(expanded.conversion_rate))::integer AS average_conversion_rate,
                    COUNT(*) AS transaction_count,
                    COALESCE(SUM(expanded.amount), 0.0) AS source_amount_total,
                    COALESCE(SUM(expanded.total_amount), 0.0) AS destination_amount_total
                FROM expanded
                JOIN supported_currency source_currency
                    ON source_currency.id = expanded.source_currency_id
                JOIN supported_currency destination_currency
                    ON destination_currency.id = expanded.destination_currency_id
                GROUP BY
                    expanded.period_type,
                    expanded.period_start,
                    expanded.partner_id,
                    expanded.source_currency_id,
                    expanded.destination_currency_id,
                    source_currency.currency_code,
                    destination_currency.currency_code
            )
            """
        )