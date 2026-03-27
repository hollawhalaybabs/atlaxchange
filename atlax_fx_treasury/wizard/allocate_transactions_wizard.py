import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare


_logger = logging.getLogger(__name__)


class AllocateTransactionsWizard(models.TransientModel):
    _name = "allocate.transactions.wizard"
    _description = "Allocate Transactions to Treasury Stock"

    stock_id = fields.Many2one(
        "atlax.treasury.stock",
        string="Stock Batch",
        required=True,
    )
    batch_id = fields.Many2one(
        "atlax.treasury.daily.batch",
        string="Daily Batch",
        help="Optional: restrict allocation to a single pooled daily batch.",
    )

    allocation_date = fields.Date(default=fields.Date.context_today, required=True)
    allocation_mode = fields.Selection(
        [
            ("full", "Full"),
            ("proportional", "Proportional"),
            ("manual", "Manual"),
        ],
        default="manual",
        required=True,
    )

    line_ids = fields.One2many(
        "allocate.transactions.wizard.line",
        "wizard_id",
        string="Transaction Lines",
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)

        ctx = dict(self.env.context or {})
        stock_id = res.get("stock_id") or ctx.get("default_stock_id")
        if not stock_id and ctx.get("active_model") == "atlax.treasury.stock":
            stock_id = ctx.get("active_id")

        batch_id = res.get("batch_id") or ctx.get("default_batch_id")

        if stock_id and not res.get("stock_id") and "stock_id" in fields_list:
            res["stock_id"] = stock_id
        if batch_id and not res.get("batch_id") and "batch_id" in fields_list:
            res["batch_id"] = batch_id

        if not stock_id or "line_ids" not in fields_list:
            return res

        stock = self.env["atlax.treasury.stock"].browse(stock_id)
        if not stock.exists():
            return res

        domain = [
            ("allocation_state", "in", ["unallocated", "partially_allocated"]),
            ("source_currency_id", "=", stock.source_currency_id.id),
        ]
        if stock.destination_currency_id:
            domain.append(("destination_currency_id", "=", stock.destination_currency_id.id))

        if batch_id:
            batch = self.env["atlax.treasury.daily.batch"].browse(batch_id)
            if batch.exists() and batch.source_currency_id == stock.source_currency_id and (
                not stock.destination_currency_id or batch.destination_currency_id == stock.destination_currency_id
            ):
                domain.append(("daily_batch_id", "=", batch.id))
            else:
                res["batch_id"] = False

        tx_lines = self.env["atlax.treasury.transaction.line"].search(domain)
        res["line_ids"] = [
            (0, 0, {"transaction_line_id": l.id, "allocate_amount": l.unallocated_amount})
            for l in tx_lines
        ]
        return res

    def _get_transaction_domain(self):
        self.ensure_one()
        if not self.stock_id:
            return [("id", "=", 0)]

        domain = [
            ("allocation_state", "in", ["unallocated", "partially_allocated"]),
            ("source_currency_id", "=", self.stock_id.source_currency_id.id),
        ]

        if self.stock_id.destination_currency_id:
            domain.append(("destination_currency_id", "=", self.stock_id.destination_currency_id.id))

        if self.batch_id:
            domain.append(("daily_batch_id", "=", self.batch_id.id))

        return domain

    @api.onchange("stock_id", "batch_id")
    def _onchange_stock_or_batch(self):
        for wiz in self:
            if not wiz.stock_id:
                wiz.line_ids = [(5, 0, 0)]
                return

            if wiz.batch_id:
                # Safety: enforce batch pair matches stock selection.
                if wiz.batch_id.source_currency_id != wiz.stock_id.source_currency_id:
                    wiz.batch_id = False
                elif wiz.stock_id.destination_currency_id and (
                    wiz.batch_id.destination_currency_id != wiz.stock_id.destination_currency_id
                ):
                    wiz.batch_id = False

            tx_lines = wiz.env["atlax.treasury.transaction.line"].search(wiz._get_transaction_domain())
            wiz.line_ids = [
                (0, 0, {"transaction_line_id": l.id, "allocate_amount": l.unallocated_amount})
                for l in tx_lines
            ]

    @api.onchange("allocation_mode")
    def _onchange_allocation_mode(self):
        for wiz in self:
            if wiz.allocation_mode != "manual":
                continue
            # In manual mode, default allocate_amount to each line's current unallocated amount.
            for line in wiz.line_ids:
                if not line.allocate_amount:
                    line.allocate_amount = line.unallocated_amount

    def _create_allocations(self, allocations):
        """Create allocation records from a list of dicts.

        allocations: list of {transaction_line_id, allocated_amount}
        """
        self.ensure_one()
        Allocation = self.env["atlax.treasury.allocation"]
        values = []
        for alloc in allocations:
            values.append(
                {
                    "stock_id": self.stock_id.id,
                    "transaction_line_id": alloc["transaction_line_id"],
                    "allocated_amount": alloc["allocated_amount"],
                    "allocation_date": self.allocation_date,
                }
            )
        if values:
            Allocation.create(values)

    def action_allocate(self):
        self.ensure_one()

        if self.stock_id.state in ("draft", "cancelled"):
            raise UserError(_("Please confirm the stock batch before allocating."))
        if self.stock_id.state == "fully_allocated":
            raise UserError(_("This stock batch is already fully allocated."))

        precision = 6
        stock_remaining = float(self.stock_id.amount_remaining or 0.0)
        if float_compare(stock_remaining, 0.0, precision_digits=precision) <= 0:
            raise UserError(_("No remaining amount available on the selected stock batch."))

        # Resolve transaction lines
        tx_lines = self.line_ids.mapped("transaction_line_id")
        tx_lines = tx_lines.filtered(lambda l: l.allocation_state in ("unallocated", "partially_allocated"))
        tx_lines = tx_lines.filtered(lambda l: l.source_currency_id == self.stock_id.source_currency_id)
        if self.stock_id.destination_currency_id:
            tx_lines = tx_lines.filtered(lambda l: l.destination_currency_id == self.stock_id.destination_currency_id)
        if self.batch_id:
            tx_lines = tx_lines.filtered(lambda l: l.daily_batch_id == self.batch_id)

        if not tx_lines:
            raise UserError(_("No eligible transaction lines found for allocation."))

        allocations = []
        remaining = stock_remaining

        if self.allocation_mode == "manual":
            for wiz_line in self.line_ids:
                tx = wiz_line.transaction_line_id
                if not tx:
                    continue
                if tx not in tx_lines:
                    continue

                amount = float(wiz_line.allocate_amount or 0.0)
                if float_compare(amount, 0.0, precision_digits=precision) <= 0:
                    continue

                if float_compare(amount, tx.unallocated_amount or 0.0, precision_digits=precision) > 0:
                    raise UserError(
                        _(
                            "Allocation for %(ref)s exceeds unallocated amount. Unallocated: %(u)s, Requested: %(r)s"
                        )
                        % {"ref": tx.transaction_reference, "u": tx.unallocated_amount, "r": amount}
                    )

                if float_compare(amount, remaining, precision_digits=precision) > 0:
                    raise UserError(
                        _(
                            "Total requested allocations exceed stock remaining. Remaining: %(rem)s, Requested: %(req)s"
                        )
                        % {"rem": remaining, "req": amount}
                    )

                allocations.append({"transaction_line_id": tx.id, "allocated_amount": amount})
                remaining -= amount

        elif self.allocation_mode == "full":
            # Allocate sequentially by transaction time (oldest first)
            ordered = tx_lines.sorted(key=lambda l: (l.transaction_datetime or fields.Datetime.now(), l.id))
            for tx in ordered:
                if float_compare(remaining, 0.0, precision_digits=precision) <= 0:
                    break
                unalloc = float(tx.unallocated_amount or 0.0)
                if float_compare(unalloc, 0.0, precision_digits=precision) <= 0:
                    continue
                amount = min(unalloc, remaining)
                if float_compare(amount, 0.0, precision_digits=precision) <= 0:
                    continue
                allocations.append({"transaction_line_id": tx.id, "allocated_amount": amount})
                remaining -= amount

        else:  # proportional
            # Distribute across lines based on each line's unallocated share.
            shares = []
            total_unalloc = 0.0
            for tx in tx_lines:
                unalloc = float(tx.unallocated_amount or 0.0)
                if float_compare(unalloc, 0.0, precision_digits=precision) <= 0:
                    continue
                shares.append((tx, unalloc))
                total_unalloc += unalloc

            if float_compare(total_unalloc, 0.0, precision_digits=precision) <= 0:
                raise UserError(_("Selected lines have no unallocated balances."))

            for (tx, unalloc) in shares:
                if float_compare(remaining, 0.0, precision_digits=precision) <= 0:
                    break
                amount = remaining * (unalloc / total_unalloc)
                amount = min(amount, unalloc)
                if float_compare(amount, 0.0, precision_digits=precision) <= 0:
                    continue
                allocations.append({"transaction_line_id": tx.id, "allocated_amount": amount})

        self._create_allocations(allocations)
        return {"type": "ir.actions.act_window_close"}


class AllocateTransactionsWizardLine(models.TransientModel):
    _name = "allocate.transactions.wizard.line"
    _description = "Allocate Transactions Wizard Line"

    wizard_id = fields.Many2one("allocate.transactions.wizard", required=True, ondelete="cascade")
    transaction_line_id = fields.Many2one(
        "atlax.treasury.transaction.line",
        string="Transaction Line",
        required=True,
    )

    customer_id = fields.Many2one(
        "res.partner",
        related="transaction_line_id.customer_id",
        readonly=True,
        string="Customer",
    )
    transaction_reference = fields.Char(
        related="transaction_line_id.transaction_reference",
        readonly=True,
        string="Transaction Reference",
    )
    transaction_date = fields.Date(related="transaction_line_id.transaction_date", readonly=True, string="Date")

    source_amount = fields.Float(related="transaction_line_id.source_amount", readonly=True, string="Source Amount")
    allocated_amount = fields.Float(
        related="transaction_line_id.allocated_amount", readonly=True, string="Allocated Amount"
    )
    unallocated_amount = fields.Float(
        related="transaction_line_id.unallocated_amount", readonly=True, string="Unallocated Amount"
    )

    allocate_amount = fields.Float(string="Allocate Amount")
