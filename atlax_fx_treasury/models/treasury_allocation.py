import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_compare


_logger = logging.getLogger(__name__)


class AtlaxTreasuryAllocation(models.Model):
    """Allocation linking a stock batch to a treasury transaction line."""

    _name = "atlax.treasury.allocation"
    _description = "Treasury Allocation"
    _order = "allocation_date desc, id desc"

    stock_id = fields.Many2one(
        "atlax.treasury.stock",
        string="Stock Batch",
        required=True,
        ondelete="cascade",
        index=True,
    )
    transaction_line_id = fields.Many2one(
        "atlax.treasury.transaction.line",
        string="Transaction Line",
        required=True,
        ondelete="cascade",
        index=True,
    )

    allocation_date = fields.Date(default=fields.Date.context_today, string="Allocation Date", required=True)

    source_currency_id = fields.Many2one(
        "supported.currency",
        related="stock_id.source_currency_id",
        store=True,
        readonly=True,
        string="Source Currency",
    )
    destination_currency_id = fields.Many2one(
        "supported.currency",
        related="transaction_line_id.destination_currency_id",
        store=True,
        readonly=True,
        string="Destination Currency",
    )

    allocated_amount = fields.Float(string="Allocated Amount", required=True)

    stock_rate = fields.Float(string="Stock Rate", compute="_compute_stock_rate", store=True)
    transaction_rate = fields.Float(
        string="Transaction Rate",
        related="transaction_line_id.transaction_rate",
        store=True,
        readonly=True,
    )

    rate_difference = fields.Float(string="Rate Difference", compute="_compute_margin", store=True)
    realized_margin = fields.Float(string="Realized Margin", compute="_compute_margin", store=True)

    notes = fields.Text(string="Notes")

    @api.depends("stock_id.purchase_rate", "stock_id.sale_rate")
    def _compute_stock_rate(self):
        for rec in self:
            rec.stock_rate = rec.stock_id.purchase_rate or rec.stock_id.sale_rate or 0.0

    @api.depends("allocated_amount", "transaction_rate", "stock_rate")
    def _compute_margin(self):
        for rec in self:
            rec.rate_difference = float(rec.transaction_rate or 0.0) - float(rec.stock_rate or 0.0)
            rec.realized_margin = float(rec.allocated_amount or 0.0) * float(rec.rate_difference or 0.0)

    @api.constrains("allocated_amount", "stock_id", "transaction_line_id")
    def _check_allocation(self):
        precision = 6
        Allocation = self.env["atlax.treasury.allocation"]

        stock_ids = self.mapped("stock_id").ids
        txn_ids = self.mapped("transaction_line_id").ids

        stock_sum = {}
        if stock_ids:
            grouped = Allocation.read_group(
                [("stock_id", "in", stock_ids)],
                ["allocated_amount:sum"],
                ["stock_id"],
            )
            stock_sum = {
                g["stock_id"][0]: float(g["allocated_amount_sum"] or 0.0) for g in grouped if g.get("stock_id")
            }

        txn_sum = {}
        if txn_ids:
            grouped = Allocation.read_group(
                [("transaction_line_id", "in", txn_ids)],
                ["allocated_amount:sum"],
                ["transaction_line_id"],
            )
            txn_sum = {
                g["transaction_line_id"][0]: float(g["allocated_amount_sum"] or 0.0)
                for g in grouped
                if g.get("transaction_line_id")
            }

        for rec in self:
            if not rec.stock_id or not rec.transaction_line_id:
                continue

            if float_compare(rec.allocated_amount or 0.0, 0.0, precision_digits=precision) <= 0:
                raise ValidationError(_("Allocated amount must be greater than 0."))

            if rec.stock_id.source_currency_id != rec.transaction_line_id.source_currency_id:
                raise ValidationError(
                    _("Stock source currency must match transaction source currency.")
                )

            if rec.stock_id.destination_currency_id and (
                rec.stock_id.destination_currency_id != rec.transaction_line_id.destination_currency_id
            ):
                raise ValidationError(
                    _("Stock destination currency must match transaction destination currency.")
                )

            if rec.stock_id.state in ("draft", "cancelled"):
                raise ValidationError(_("You can only allocate from a confirmed stock batch."))

            # Validate totals against stock and transaction.
            total_alloc_stock = float(stock_sum.get(rec.stock_id.id, 0.0) or 0.0)
            total_stock = float(rec.stock_id.amount_total or 0.0)
            if float_compare(total_alloc_stock, total_stock, precision_digits=precision) > 0:
                raise ValidationError(
                    _(
                        "Allocated amounts exceed the stock total. Total allocated: %(a)s, Stock total: %(t)s"
                    )
                    % {"a": total_alloc_stock, "t": total_stock}
                )

            total_alloc_txn = float(txn_sum.get(rec.transaction_line_id.id, 0.0) or 0.0)
            total_txn = float(rec.transaction_line_id.source_amount or 0.0)
            if float_compare(total_alloc_txn, total_txn, precision_digits=precision) > 0:
                raise ValidationError(
                    _(
                        "Allocated amounts exceed the transaction total. Total allocated: %(a)s, Transaction total: %(t)s"
                    )
                    % {"a": total_alloc_txn, "t": total_txn}
                )

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        recs.mapped("stock_id")._update_state_from_allocations()
        return recs

    def write(self, vals):
        stocks_before = self.mapped("stock_id")
        res = super().write(vals)
        (stocks_before | self.mapped("stock_id"))._update_state_from_allocations()
        return res

    def unlink(self):
        stocks = self.mapped("stock_id")
        res = super().unlink()
        stocks._update_state_from_allocations()
        return res
