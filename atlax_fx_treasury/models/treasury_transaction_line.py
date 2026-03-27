import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_compare, float_is_zero


_logger = logging.getLogger(__name__)


class AtlaxTreasuryTransactionLine(models.Model):
    """Treasury-eligible transaction layer.

    This is a separate allocation layer derived from (or linked to) existing
    transaction history records. It does not modify the original ledger/history
    model and is safe to run alongside the current system.
    """

    _name = "atlax.treasury.transaction.line"
    _description = "Treasury Transaction Line"
    _order = "transaction_datetime desc, id desc"
    _rec_name = "transaction_reference"

    name = fields.Char(string="Internal Reference", copy=False)

    transaction_reference = fields.Char(string="Transaction Reference", required=True, index=True)
    transaction_datetime = fields.Datetime(string="Transaction Datetime")
    transaction_date = fields.Date(
        string="Transaction Date",
        compute="_compute_transaction_date",
        store=True,
        index=True,
    )

    customer_id = fields.Many2one("res.partner", string="Customer", index=True)

    source_currency_id = fields.Many2one("supported.currency", string="Source Currency", required=True, index=True)
    destination_currency_id = fields.Many2one(
        "supported.currency", string="Destination Currency", required=True, index=True
    )

    source_amount = fields.Float(string="Source Amount")
    destination_amount = fields.Float(string="Destination Amount")
    transaction_rate = fields.Float(string="Transaction Rate")
    fee_amount = fields.Float(string="Fee Amount")

    status = fields.Selection(
        [
            ("pending", "Pending"),
            ("processing", "Processing"),
            ("success", "Success"),
            ("failed", "Failed"),
            ("reversed", "Reversed"),
        ],
        default="pending",
        required=True,
        index=True,
    )

    original_ledger_ref = fields.Char(string="Original Ledger Ref")

    allocation_line_ids = fields.One2many(
        "atlax.treasury.allocation",
        "transaction_line_id",
        string="Allocations",
        copy=False,
    )

    allocated_amount = fields.Float(string="Allocated Amount", compute="_compute_allocation_balances", store=True)
    unallocated_amount = fields.Float(string="Unallocated Amount", compute="_compute_allocation_balances", store=True)
    allocation_state = fields.Selection(
        [
            ("unallocated", "Unallocated"),
            ("partially_allocated", "Partially Allocated"),
            ("allocated", "Allocated"),
        ],
        string="Allocation State",
        compute="_compute_allocation_balances",
        store=True,
        index=True,
    )

    daily_batch_id = fields.Many2one("atlax.treasury.daily.batch", string="Daily Batch", index=True)
    notes = fields.Text(string="Notes")

    _sql_constraints = [
        (
            "transaction_reference_unique",
            "unique(transaction_reference)",
            "Transaction Reference must be unique in Treasury Transaction Lines.",
        )
    ]

    @api.depends("transaction_datetime")
    def _compute_transaction_date(self):
        for rec in self:
            if rec.transaction_datetime:
                rec.transaction_date = fields.Date.to_date(rec.transaction_datetime)
            else:
                rec.transaction_date = False

    @api.depends("source_amount", "allocation_line_ids.allocated_amount")
    def _compute_allocation_balances(self):
        Allocation = self.env["atlax.treasury.allocation"]
        precision = 6

        sums = {}
        if self.ids:
            grouped = Allocation.read_group(
                [("transaction_line_id", "in", self.ids)],
                ["allocated_amount:sum"],
                ["transaction_line_id"],
            )
            sums = {
                g["transaction_line_id"][0]: float(g["allocated_amount_sum"] or 0.0)
                for g in grouped
                if g.get("transaction_line_id")
            }

        for rec in self:
            total = float(rec.source_amount or 0.0)
            allocated = float(sums.get(rec.id, 0.0) or 0.0)
            unallocated = total - allocated

            if unallocated < 0 and float_compare(unallocated, 0.0, precision_digits=precision) < 0:
                # keep negative value for debugging, but state should still be allocated
                pass

            rec.allocated_amount = allocated
            rec.unallocated_amount = unallocated

            if float_is_zero(total, precision_digits=precision):
                rec.allocation_state = "unallocated"
            elif float_is_zero(allocated, precision_digits=precision):
                rec.allocation_state = "unallocated"
            elif float_compare(allocated, total, precision_digits=precision) >= 0:
                rec.allocation_state = "allocated"
            else:
                rec.allocation_state = "partially_allocated"

    @api.constrains("source_amount")
    def _check_source_amount(self):
        for rec in self:
            if rec.source_amount is None:
                continue
            if float_compare(rec.source_amount or 0.0, 0.0, precision_digits=6) < 0:
                raise ValidationError(_("Source Amount cannot be negative."))

    @api.constrains(
        "daily_batch_id",
        "transaction_date",
        "source_currency_id",
        "destination_currency_id",
    )
    def _check_daily_batch_consistency(self):
        for rec in self:
            if not rec.daily_batch_id:
                continue

            batch = rec.daily_batch_id
            if batch.source_currency_id and rec.source_currency_id and batch.source_currency_id != rec.source_currency_id:
                raise ValidationError(_("Daily batch source currency must match the transaction line source currency."))
            if (
                batch.destination_currency_id
                and rec.destination_currency_id
                and batch.destination_currency_id != rec.destination_currency_id
            ):
                raise ValidationError(
                    _("Daily batch destination currency must match the transaction line destination currency.")
                )
            if batch.batch_date and rec.transaction_date and batch.batch_date != rec.transaction_date:
                raise ValidationError(_("Daily batch date must match the transaction date."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name"):
                ref = vals.get("transaction_reference")
                vals["name"] = ref and f"TX/{ref}" or _("New")
        return super().create(vals_list)
