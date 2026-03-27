import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_compare


_logger = logging.getLogger(__name__)


class AtlaxTreasuryDailyBatch(models.Model):
    """Pooled operational bucket for treasury work per day and currency pair."""

    _name = "atlax.treasury.daily.batch"
    _description = "Treasury Daily Batch"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "batch_date desc, id desc"
    _rec_name = "name"

    name = fields.Char(
        string="Reference",
        required=True,
        copy=False,
        default=lambda self: _("New"),
        tracking=True,
        index=True,
    )

    batch_date = fields.Date(string="Batch Date", required=True, default=fields.Date.context_today, tracking=True)
    source_currency_id = fields.Many2one(
        "supported.currency",
        string="Source Currency",
        required=True,
        tracking=True,
    )
    destination_currency_id = fields.Many2one(
        "supported.currency",
        string="Destination Currency",
        required=True,
        tracking=True,
    )

    transaction_line_ids = fields.One2many(
        "atlax.treasury.transaction.line",
        "daily_batch_id",
        string="Transaction Lines",
        copy=False,
    )

    total_transaction_amount = fields.Float(string="Total Transaction Amount", compute="_compute_totals", store=True)
    total_allocated_amount = fields.Float(string="Total Allocated Amount", compute="_compute_totals", store=True)
    total_unallocated_amount = fields.Float(string="Total Unallocated Amount", compute="_compute_totals", store=True)

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("open", "Open"),
            ("allocated", "Allocated"),
            ("closed", "Closed"),
        ],
        default="draft",
        required=True,
        tracking=True,
    )

    notes = fields.Text(string="Notes")

    transaction_count = fields.Integer(string="Transactions", compute="_compute_transaction_count")

    @api.depends("transaction_line_ids")
    def _compute_transaction_count(self):
        for rec in self:
            rec.transaction_count = len(rec.transaction_line_ids)

    @api.depends(
        "transaction_line_ids.source_amount",
        "transaction_line_ids.allocated_amount",
        "transaction_line_ids.unallocated_amount",
    )
    def _compute_totals(self):
        for rec in self:
            rec.total_transaction_amount = sum(rec.transaction_line_ids.mapped("source_amount") or [0.0])
            rec.total_allocated_amount = sum(rec.transaction_line_ids.mapped("allocated_amount") or [0.0])
            rec.total_unallocated_amount = sum(rec.transaction_line_ids.mapped("unallocated_amount") or [0.0])

    @api.constrains("batch_date")
    def _check_batch_date(self):
        for rec in self:
            if not rec.batch_date:
                raise ValidationError(_("Batch Date is required."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals.get("name") == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("atlax.treasury.daily.batch") or _("New")
        return super().create(vals_list)

    def action_open_transactions(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Transaction Lines"),
            "res_model": "atlax.treasury.transaction.line",
            "view_mode": "tree,form",
            "domain": [("daily_batch_id", "=", self.id)],
            "context": {
                "default_daily_batch_id": self.id,
                "default_source_currency_id": self.source_currency_id.id,
                "default_destination_currency_id": self.destination_currency_id.id,
            },
        }

    def action_set_open(self):
        self.write({"state": "open"})
        return True

    def action_set_allocated(self):
        self.write({"state": "allocated"})
        return True

    def action_close(self):
        self.write({"state": "closed"})
        return True
