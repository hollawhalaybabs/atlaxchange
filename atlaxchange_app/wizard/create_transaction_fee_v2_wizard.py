import logging

import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class CreateTransactionFeeV2Wizard(models.TransientModel):
    _name = "create.transaction.fee.v2.wizard"
    _description = "Create Transaction Fee (v2) Wizard"

    partner_id = fields.Many2one(
        "res.partner",
        string="Customer",
        domain=[("is_atlax_customer", "=", True)],
    )
    business_id = fields.Char(string="Business ID")

    source_currency_id = fields.Many2one("supported.currency", string="Source Currency", required=True)
    target_currency_id = fields.Many2one("supported.currency", string="Target Currency", required=True)

    transfer_direction = fields.Selection(
        [("debit", "Debit"), ("credit", "Credit")],
        string="Transfer Direction",
        required=True,
    )

    payment_method = fields.Selection(
        [
            # New API values
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
        default="fixed",
    )

    max_fee = fields.Float(string="Max Fee", required=True)
    fixed_fee = fields.Float(string="Fixed Fee")
    percentage_fee = fields.Float(string="Percentage Fee")
    percentage_cap = fields.Float(string="Percentage Cap")

    @api.onchange("partner_id")
    def _onchange_partner_id(self):
        for rec in self:
            rec.business_id = rec.partner_id.business_id if rec.partner_id else False

    def _normalize_payment_method(self, payment_method):
        """Ensure we always send V2 API payment method values."""
        payment_method = payment_method or ""
        if payment_method == "transfer":
            return "bank_transfer"
        if payment_method == "momo":
            return "mobile_transfer"
        return payment_method

    def _to_minor(self, value):
        try:
            return int(round(float(value or 0) * 100))
        except (TypeError, ValueError):
            raise UserError(_("Amount values must be numeric."))

    def action_create_fee_v2(self):
        self.ensure_one()

        if self.partner_id and not self.partner_id.is_atlax_customer:
            raise UserError(_("Only Atlax customers can have transaction fees."))

        source_code = self.source_currency_id.currency_code
        target_code = self.target_currency_id.currency_code
        if not source_code or not target_code:
            raise UserError(_("Selected currencies must have a currency_code."))

        name = f"{source_code}-{target_code}"

        payment_method = self._normalize_payment_method(self.payment_method)

        # If business_id is provided, create a customer-specific fee.
        # Otherwise, create a default fee (does not require business_id).
        is_customer_specific = bool(self.business_id)

        if self.partner_id and not self.partner_id.is_atlax_customer:
            raise UserError(_("Only Atlax customers can have transaction fees."))

        if self.partner_id and not self.business_id:
            raise UserError(_("Selected customer is missing a Business ID."))

        payload = {
            "name": name,
            "transfer_direction": self.transfer_direction,
            "max_fee": self._to_minor(self.max_fee),
            "payment_method": payment_method,
            "payment_method_type": self.payment_method_type or "",
            "amount_type": self.amount_type,
            "fixed_fee": self._to_minor(self.fixed_fee),
            "percentage_fee": float(self.percentage_fee or 0),
            "percentage_cap": self._to_minor(self.percentage_cap),
        }

        if is_customer_specific:
            payload["business_id"] = self.business_id or ""

        client = self.env["atlax.api.client"]
        endpoint = "/v2/admin/fees" if is_customer_specific else "/v2/admin/fees/default"
        url = client.url(endpoint)
        headers = client.build_headers()
        if not headers.get("X-API-KEY") or not headers.get("X-API-SECRET"):
            raise UserError(_("API key or secret is missing. Configure env or system parameters."))

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
        except requests.RequestException as e:
            _logger.exception("Error while calling Atlax /v2/admin/fees API: %s", e)
            raise UserError(_("Failed to create fee due to a network error. Please try again."))

        if response.status_code not in (200, 201):
            raise UserError(_("Failed to create fee: %s") % response.text)

        resp = response.json() or {}
        data = resp.get("data")
        recs = []
        if isinstance(data, dict):
            if isinstance(data.get("fees"), list):
                recs = data.get("fees")
            elif isinstance(data.get("fee"), dict):
                recs = [data.get("fee")]
            else:
                recs = [data]
        elif isinstance(data, list):
            recs = data

        for fee_rec in (recs or []):
            self.env["transaction.fee.v2"]._sync_single_fee_record(fee_rec)

        return {"type": "ir.actions.act_window_close"}
