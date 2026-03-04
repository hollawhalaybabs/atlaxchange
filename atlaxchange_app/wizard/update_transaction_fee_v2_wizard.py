import logging

import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class UpdateTransactionFeeV2Wizard(models.TransientModel):
    _name = "update.transaction.fee.v2.wizard"
    _description = "Update Transaction Fee (v2) Wizard"
    _rec_name = "name"

    fee_line_id = fields.Many2one(
        "transaction.fee.v2.line",
        string="Fee Line",
        required=True,
    )

    fee_id = fields.Char(related="fee_line_id.fee_id", string="Fee ID", readonly=True)
    name = fields.Char(string="Name", compute="_compute_name", store=False, readonly=True)
    business_id = fields.Char(related="fee_line_id.business_id", string="Business ID", readonly=True)

    source_currency_id = fields.Many2one(
        "supported.currency",
        related="fee_line_id.source_currency_id",
        string="Source Currency",
        readonly=True,
    )
    target_currency_id = fields.Many2one(
        "supported.currency",
        related="fee_line_id.target_currency_id",
        string="Target Currency",
        readonly=True,
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        fee_line_id = res.get("fee_line_id") or self.env.context.get("default_fee_line_id")
        if not fee_line_id:
            return res

        line = self.env["transaction.fee.v2.line"].browse(fee_line_id)
        if not line.exists():
            return res

        allowed = {k for k, _ in (self._fields["payment_method"].selection or [])}
        method = line.payment_method
        if method == "transfer":
            method = "bank_transfer"
        elif method == "momo":
            method = "mobile_transfer"
        if method not in allowed:
            if method == "bank_transfer" and "transfer" in allowed:
                method = "transfer"
            elif method == "mobile_transfer" and "momo" in allowed:
                method = "momo"
            else:
                method = False

        res.setdefault("transfer_direction", line.transfer_direction)
        res.setdefault("payment_method", method)
        res.setdefault("payment_method_type", line.payment_method_type)
        res.setdefault("amount_type", line.amount_type)
        res.setdefault("max_fee", line.max_fee)
        res.setdefault("fixed_fee", line.fixed_fee)
        res.setdefault("percentage_fee", line.percentage_fee)
        res.setdefault("percentage_cap", line.percentage_cap)
        return res

    @api.depends("source_currency_id.currency_code", "target_currency_id.currency_code", "fee_line_id.name")
    def _compute_name(self):
        for rec in self:
            if rec.source_currency_id and rec.target_currency_id:
                src = rec.source_currency_id.currency_code
                tgt = rec.target_currency_id.currency_code
                if src and tgt:
                    rec.name = f"{src}-{tgt}"
                    continue
            rec.name = rec.fee_line_id.name if rec.fee_line_id else False

    transfer_direction = fields.Selection(
        [("debit", "Debit"), ("credit", "Credit")],
        string="Transfer Direction",
        required=True,
    )

    payment_method = fields.Selection(
        [
            ("bank_transfer", "Bank Transfer"),
            ("mobile_transfer", "Mobile Transfer"),
            ("card", "Card"),
            # Legacy values (kept for backward compatibility with existing DB rows)
            ("transfer", "Bank Transfer (legacy)"),
            ("momo", "MoMo (legacy)"),
        ],
        string="Payment Method",
        required=True,
    )
    payment_method_type = fields.Selection(
        [
            ("ach", "ACH"),
            ("swift", "SWIFT"),
            ("wire_transfer", "Wire Transfer"),
        ],
        string="Payment Method Type",
    )

    amount_type = fields.Selection(
        [("fixed", "Fixed"), ("percentage", "Percentage"), ("both", "Both")],
        string="Amount Type",
        required=True,
    )

    max_fee = fields.Float(string="Max Fee", required=True)
    fixed_fee = fields.Float(string="Fixed Fee")
    percentage_fee = fields.Float(string="Percentage Fee")
    percentage_cap = fields.Float(string="Percentage Cap")

    @api.onchange("fee_line_id")
    def _onchange_fee_line_id(self):
        for rec in self:
            if not rec.fee_line_id:
                continue
            line = rec.fee_line_id
            rec.transfer_direction = line.transfer_direction

            # Be defensive: if the selection values in the running registry differ
            # from what is stored on the fee line, map into an allowed value.
            allowed = {k for k, _ in (rec._fields["payment_method"].selection or [])}
            method = line.payment_method
            if method == "transfer":
                method = "bank_transfer"
            elif method == "momo":
                method = "mobile_transfer"
            if method not in allowed:
                # Fall back to legacy values if only legacy options are available.
                if method == "bank_transfer" and "transfer" in allowed:
                    method = "transfer"
                elif method == "mobile_transfer" and "momo" in allowed:
                    method = "momo"
                else:
                    method = False
            rec.payment_method = method

            rec.payment_method_type = line.payment_method_type
            rec.amount_type = line.amount_type
            rec.max_fee = line.max_fee
            rec.fixed_fee = line.fixed_fee
            rec.percentage_fee = line.percentage_fee
            rec.percentage_cap = line.percentage_cap

    def _to_minor(self, value):
        try:
            return int(round(float(value or 0) * 100))
        except (TypeError, ValueError):
            raise UserError(_("Amount values must be numeric."))

    def action_update_fee_v2(self):
        self.ensure_one()
        if not self.fee_line_id:
            raise UserError(_("Please select a Fee Line to update."))

        fee_id = self.fee_line_id.fee_id
        if not fee_id:
            raise UserError(_("Fee ID is missing on the selected Fee Line."))

        # Always normalize to the new API values.
        payment_method = self.payment_method
        if payment_method == "transfer":
            payment_method = "bank_transfer"
        elif payment_method == "momo":
            payment_method = "mobile_transfer"

        payload = {
            "name": self.name or "",
            "transfer_direction": self.transfer_direction,
            "max_fee": self._to_minor(self.max_fee),
            "payment_method": payment_method,
            "payment_method_type": self.payment_method_type or "",
            "amount_type": self.amount_type,
            "fixed_fee": self._to_minor(self.fixed_fee),
            "percentage_fee": float(self.percentage_fee or 0),
            "percentage_cap": self._to_minor(self.percentage_cap),
        }

        # Only include business_id for customer-specific fees.
        if self.business_id:
            payload["business_id"] = self.business_id

        client = self.env["atlax.api.client"]
        url = client.url(f"/v2/admin/fees/{fee_id}")
        headers = client.build_headers()
        if not headers.get("X-API-KEY") or not headers.get("X-API-SECRET"):
            raise UserError(_("API key or secret is missing. Configure env or system parameters."))

        try:
            response = requests.patch(url, json=payload, headers=headers, timeout=30)
        except requests.RequestException as e:
            _logger.exception("Error while calling Atlax /v2/admin/fees PATCH: %s", e)
            raise UserError(_("Failed to update fee due to a network error. Please try again."))

        if response.status_code not in (200, 201):
            raise UserError(_("Failed to update fee: %s") % response.text)

        line = self.env["transaction.fee.v2.line"].search([("fee_id", "=", fee_id)], limit=1)
        if line:
            line.write({
                "transfer_direction": self.transfer_direction,
                "payment_method": self.payment_method,
                "payment_method_type": self.payment_method_type,
                "amount_type": self.amount_type,
                "max_fee": self.max_fee,
                "fixed_fee": self.fixed_fee,
                "percentage_fee": self.percentage_fee,
                "percentage_cap": self.percentage_cap,
            })

        return {"type": "ir.actions.act_window_close"}
