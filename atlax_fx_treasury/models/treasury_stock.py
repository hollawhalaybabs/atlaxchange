import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_compare, float_is_zero


_logger = logging.getLogger(__name__)


class AtlaxTreasuryStock(models.Model):
    """Treasury liquidity stock batch.

    Phase 1 scope:
    - Store internal stock batches obtained from liquidity partners
    - Track allocations to treasury transaction lines
    - Compute remaining stock and basic realized margin via allocations

    This model is internal-only and does not affect wallet balances,
    customer funding, or transaction history models.
    """

    _name = "atlax.treasury.stock"
    _description = "Treasury Stock Batch"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date desc, id desc"
    _rec_name = "name"

    name = fields.Char(
        string="Reference",
        required=True,
        copy=False,
        default=lambda self: _("New"),
        tracking=True,
        index=True,
    )

    date = fields.Date(default=fields.Date.context_today, required=True, tracking=True)
    partner_id = fields.Many2one("res.partner", string="Liquidity Partner", tracking=True)

    source_currency_id = fields.Many2one(
        "supported.currency",
        string="Source Currency",
        required=True,
        tracking=True,
    )
    destination_currency_id = fields.Many2one(
        "supported.currency",
        string="Destination Currency",
        help="Optional: when set, allocations must match this destination currency.",
        tracking=True,
    )

    amount_total = fields.Float(string="Total Amount", required=True, tracking=True)
    amount_allocated = fields.Float(string="Allocated Amount", compute="_compute_amounts", store=True)
    amount_remaining = fields.Float(string="Remaining Amount", compute="_compute_amounts", store=True)

    purchase_rate = fields.Float(string="Purchase Rate", tracking=True)
    sale_rate = fields.Float(string="Sale Rate", tracking=True)

    bank_journal_id = fields.Many2one("account.journal", string="Bank Journal")
    bank_reference = fields.Char(string="Bank Reference")
    notes = fields.Text(string="Notes")

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("confirmed", "Confirmed"),
            ("partially_allocated", "Partially Allocated"),
            ("fully_allocated", "Fully Allocated"),
            ("cancelled", "Cancelled"),
        ],
        default="draft",
        tracking=True,
        required=True,
    )

    allocation_line_ids = fields.One2many(
        "atlax.treasury.allocation",
        "stock_id",
        string="Allocations",
        copy=False,
    )

    allocation_count = fields.Integer(string="Allocations", compute="_compute_allocation_count")

    active = fields.Boolean(default=True)

    @api.depends("allocation_line_ids")
    def _compute_allocation_count(self):
        for rec in self:
            rec.allocation_count = len(rec.allocation_line_ids)

    @api.depends("amount_total", "allocation_line_ids.allocated_amount")
    def _compute_amounts(self):
        Allocation = self.env["atlax.treasury.allocation"]
        sums = {}
        if self.ids:
            grouped = Allocation.read_group(
                [("stock_id", "in", self.ids)],
                ["allocated_amount:sum"],
                ["stock_id"],
            )
            sums = {g["stock_id"][0]: g["allocated_amount_sum"] for g in grouped if g.get("stock_id")}

        for rec in self:
            allocated = float(sums.get(rec.id, 0.0) or 0.0)
            total = float(rec.amount_total or 0.0)
            rec.amount_allocated = allocated
            rec.amount_remaining = total - allocated

    @api.constrains("amount_total")
    def _check_amount_total(self):
        for rec in self:
            if float_compare(rec.amount_total or 0.0, 0.0, precision_digits=6) <= 0:
                raise ValidationError(_("Total Amount must be greater than 0."))
            if float_compare(rec.amount_total or 0.0, rec.amount_allocated or 0.0, precision_digits=6) < 0:
                raise ValidationError(
                    _(
                        "Total Amount cannot be less than already allocated amount. Allocated: %(a)s, Total: %(t)s"
                    )
                    % {"a": rec.amount_allocated, "t": rec.amount_total}
                )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals.get("name") == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("atlax.treasury.stock") or _("New")
        recs = super().create(vals_list)
        return recs

    def write(self, vals):
        res = super().write(vals)
        if "amount_total" in vals:
            self._update_state_from_allocations()
        return res

    def action_confirm(self):
        for rec in self:
            if rec.state == "cancelled":
                continue
            rec.write({"state": "confirmed"})
        self._update_state_from_allocations()
        return True

    def action_set_draft(self):
        for rec in self:
            if rec.allocation_line_ids:
                raise ValidationError(_("You cannot set to Draft while allocations exist."))
            rec.write({"state": "draft"})
        return True

    def action_cancel(self):
        for rec in self:
            if rec.allocation_line_ids:
                raise ValidationError(_("You cannot cancel a stock batch with allocations."))
            rec.write({"state": "cancelled"})
        return True

    def _update_state_from_allocations(self):
        """Update stock allocation state based on totals.

        Called from allocation create/write/unlink and from confirm.
        Draft and cancelled states are treated as manual and won't be overridden.
        """

        Allocation = self.env["atlax.treasury.allocation"]
        precision = 6

        stocks = self.filtered(lambda s: s.state not in ("draft", "cancelled"))
        if not stocks:
            return

        grouped = Allocation.read_group(
            [("stock_id", "in", stocks.ids)],
            ["allocated_amount:sum"],
            ["stock_id"],
        )
        allocated_map = {g["stock_id"][0]: float(g["allocated_amount_sum"] or 0.0) for g in grouped if g.get("stock_id")}

        for stock in stocks:
            allocated = float(allocated_map.get(stock.id, 0.0) or 0.0)
            total = float(stock.amount_total or 0.0)

            if float_is_zero(allocated, precision_digits=precision):
                new_state = "confirmed"
            elif float_compare(allocated, total, precision_digits=precision) < 0:
                new_state = "partially_allocated"
            else:
                new_state = "fully_allocated"

            if stock.state != new_state:
                stock.write({"state": new_state})

    def action_open_allocations(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Allocations"),
            "res_model": "atlax.treasury.allocation",
            "view_mode": "tree,form",
            "domain": [("stock_id", "=", self.id)],
            "context": {
                "default_stock_id": self.id,
            },
        }
