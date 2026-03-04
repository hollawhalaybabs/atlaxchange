import logging

import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


PAYMENT_METHOD_SELECTION = [
    # New API values
    ("bank_transfer", "Bank Transfer"),
    ("mobile_transfer", "Mobile Transfer"),
    ("card", "Card"),
    # Legacy values (kept for backward compatibility with existing DB rows)
    ("transfer", "Bank Transfer (legacy)"),
    ("momo", "MoMo (legacy)"),
]

PAYMENT_METHOD_TYPE_SELECTION = [
    ("ach", "ACH"),
    ("swift", "SWIFT"),
    ("wire_transfer", "Wire Transfer"),
]

AMOUNT_TYPE_SELECTION = [
    ("fixed", "Fixed"),
    ("percentage", "Percentage"),
    ("both", "Both"),
]


class TransactionFeeV2(models.Model):
    _name = "transaction.fee.v2"
    _description = "Transaction Fee (v2)"
    _order = "id desc"
    _rec_name = "display_name"

    display_name = fields.Char(compute="_compute_display_name", store=True)
    partner_id = fields.Many2one("res.partner", compute="_compute_partner_id", store=True)
    business_id = fields.Char(string="Business ID")

    fee_line_ids = fields.One2many(
        "transaction.fee.v2.line",
        "transaction_fee_id",
        string="Fee Lines",
    )

    @api.depends("partner_id", "business_id")
    def _compute_display_name(self):
        for rec in self:
            if rec.partner_id:
                rec.display_name = f"{rec.partner_id.display_name} - Transaction Fees"
            elif rec.business_id:
                rec.display_name = f"{rec.business_id} - Transaction Fees"
            else:
                rec.display_name = _("Default Transaction Fees")
                
    @api.depends("business_id")
    def _compute_partner_id(self):
        for rec in self:
            partner = False
            if rec.business_id:
                partner = self.env["res.partner"].search([("business_id", "=", rec.business_id)], limit=1)
            rec.partner_id = partner

    def _minor_to_major(self, value):
        return (value or 0) / 100

    def _to_minor(self, value):
        try:
            return int(round(float(value or 0) * 100))
        except (TypeError, ValueError):
            raise UserError(_("Amount values must be numeric."))

    def _normalize_selection(self, value, selection):
        allowed = {k for k, _ in selection}
        # Backward-compatible mapping for older API values.
        if value == "transfer":
            value = "bank_transfer"
        elif value == "momo":
            value = "mobile_transfer"
        return value if value in allowed else False

    def _extract_after_cursor(self, response, payload):
        """Extract the next-page cursor ("after") from common payload/header locations."""
        after_val = None

        if isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, dict):
                cur = data.get("cursor")
                if isinstance(cur, dict):
                    after_val = cur.get("after") or cur.get("next") or cur.get("next_cursor")
                after_val = after_val or data.get("next_cursor") or data.get("after")

            cur_top = payload.get("cursor")
            if isinstance(cur_top, dict):
                after_val = after_val or cur_top.get("after") or cur_top.get("next") or cur_top.get("next_cursor")

            after_val = after_val or payload.get("next_cursor") or payload.get("after")

        headers = getattr(response, "headers", {}) or {}
        after_val = after_val or headers.get("X-Next-Cursor") or headers.get("Next-Cursor") or headers.get("x-next-cursor")

        return str(after_val) if after_val else None

    def _get_or_create_parent(self, business_id):
        business_id = business_id or False
        existing = self.search([("business_id", "=", business_id)], limit=1)
        if existing:
            return existing
        return self.create({"business_id": business_id})

    def _sync_single_fee_record(self, fee_rec):
        fee_id = fee_rec.get("fee_id")
        if not fee_id:
            return

        parent = self._get_or_create_parent(fee_rec.get("business_id"))

        name = fee_rec.get("name")
        source_currency = False
        target_currency = False
        if name and "-" in name:
            source_code, target_code = [p.strip() for p in name.split("-", 1)]
            source_currency = self.env["supported.currency"].search(
                [("currency_code", "=", source_code)], limit=1
            )
            target_currency = self.env["supported.currency"].search(
                [("currency_code", "=", target_code)], limit=1
            )

        pair_name = False
        if source_currency and target_currency and source_currency.currency_code and target_currency.currency_code:
            pair_name = f"{source_currency.currency_code}-{target_currency.currency_code}"

        vals = {
            "transaction_fee_id": parent.id,
            "fee_id": fee_id,
            "name": pair_name or name,
            "business_id": fee_rec.get("business_id") or False,
            "source_currency_id": source_currency.id if source_currency else False,
            "target_currency_id": target_currency.id if target_currency else False,
            "transfer_direction": fee_rec.get("transfer_direction"),
            "payment_method": self._normalize_selection(fee_rec.get("payment_method"), PAYMENT_METHOD_SELECTION),
            "payment_method_type": self._normalize_selection(
                fee_rec.get("payment_method_type"), PAYMENT_METHOD_TYPE_SELECTION
            ),
            "amount_type": self._normalize_selection(fee_rec.get("amount_type"), AMOUNT_TYPE_SELECTION),
            "max_fee": self._minor_to_major(fee_rec.get("max_fee")),
            "fixed_fee": self._minor_to_major(fee_rec.get("fixed_fee") if fee_rec.get("fixed_fee") is not None else fee_rec.get("fee")),
            "percentage_fee": float(
                fee_rec.get("percentage_fee")
                if fee_rec.get("percentage_fee") is not None
                else (fee_rec.get("percentage") or 0)
            ),
            "percentage_cap": self._minor_to_major(fee_rec.get("percentage_cap")),
        }

        line = self.env["transaction.fee.v2.line"].search(
            [("transaction_fee_id", "=", parent.id), ("fee_id", "=", fee_id)], limit=1
        )
        if line:
            line.write(vals)
        else:
            self.env["transaction.fee.v2.line"].create(vals)

    @api.model
    def fetch_transaction_fees_v2(self):
        client = self.env["atlax.api.client"]
        url = client.url("/v2/admin/fees")
        headers = client.build_headers()
        if not headers.get("X-API-KEY") or not headers.get("X-API-SECRET"):
            raise UserError(_("API key or secret is missing. Configure env or system parameters."))

        next_after = None
        seen_cursors = set()
        pages = 0
        max_pages = 500

        while True:
            pages += 1
            if pages > max_pages:
                raise UserError(
                    _("Stopped after %s pages while fetching fees (cursor never ended).") % max_pages
                )

            params = {}
            if next_after:
                params["after"] = next_after

            try:
                response = requests.get(url, headers=headers, params=params, timeout=30)
            except requests.RequestException as e:
                _logger.exception("Error while calling Atlax /v2/admin/fees API (after=%s): %s", next_after, e)
                raise UserError(_("Failed to fetch transaction fees due to a network error. Please try again."))

            if response.status_code != 200:
                raise UserError(_("Failed to fetch transaction fees: %s") % response.text)

            try:
                payload = response.json() or {}
            except Exception:
                raise UserError(_("Failed to fetch transaction fees: invalid JSON response."))

            data = payload.get("data") or {}
            fees = []
            if isinstance(data, dict):
                fees = data.get("fees") or []
            elif isinstance(data, list):
                fees = data

            for fee_rec in (fees or []):
                self.env["transaction.fee.v2"]._sync_single_fee_record(fee_rec)

            new_after = self._extract_after_cursor(response, payload)
            if not new_after:
                break
            if new_after in seen_cursors:
                _logger.warning("Fee v2 fetch: repeated cursor encountered (%s); stopping to avoid infinite loop.", new_after)
                break

            seen_cursors.add(new_after)
            next_after = new_after

        return True

    def action_open_create_fee_wizard_v2(self):
        return {
            "type": "ir.actions.act_window",
            "res_model": "create.transaction.fee.v2.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_business_id": self.business_id,
                "default_partner_id": self.partner_id.id if self.partner_id else False,
            },
        }

    def action_open_update_fee_wizard_v2(self):
        self.ensure_one()
        fee_line_id = self.fee_line_ids[:1].id if len(self.fee_line_ids) == 1 else False
        return {
            "type": "ir.actions.act_window",
            "res_model": "update.transaction.fee.v2.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_fee_line_id": fee_line_id,
            },
        }

    def action_open_delete_fee_wizard_v2(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "delete.transaction.fee.v2.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_fee_line_ids": [(6, 0, self.fee_line_ids.ids)],
            },
        }


class TransactionFeeV2Line(models.Model):
    _name = "transaction.fee.v2.line"
    _description = "Transaction Fee Line (v2)"
    _order = "id desc"
    _rec_name = "fee_id"

    transaction_fee_id = fields.Many2one(
        "transaction.fee.v2",
        string="Transaction Fee (v2)",
        ondelete="cascade",
        required=True,
    )

    fee_id = fields.Char(string="Fee ID", required=True, index=True)
    name = fields.Char(string="Name")
    business_id = fields.Char(string="Business ID")

    source_currency_id = fields.Many2one("supported.currency", string="Source Currency")
    target_currency_id = fields.Many2one("supported.currency", string="Target Currency")

    transfer_direction = fields.Selection(
        [("debit", "Debit"), ("credit", "Credit")],
        string="Transfer Direction",
        required=True,
    )

    payment_method = fields.Selection(PAYMENT_METHOD_SELECTION, string="Payment Method")
    payment_method_type = fields.Selection(PAYMENT_METHOD_TYPE_SELECTION, string="Payment Method Type")
    amount_type = fields.Selection(AMOUNT_TYPE_SELECTION, string="Amount Type")

    max_fee = fields.Float(string="Max Fee")
    fixed_fee = fields.Float(string="Fixed Fee")
    percentage_fee = fields.Float(string="Percentage Fee")
    percentage_cap = fields.Float(string="Percentage Cap")
