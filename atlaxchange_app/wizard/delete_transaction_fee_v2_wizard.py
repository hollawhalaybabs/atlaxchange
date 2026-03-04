import logging

import requests

from odoo import fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class DeleteTransactionFeeV2Wizard(models.TransientModel):
    _name = "delete.transaction.fee.v2.wizard"
    _description = "Delete Transaction Fee (v2) Wizard"

    fee_line_ids = fields.Many2many(
        "transaction.fee.v2.line",
        string="Fee Lines",
        required=True,
    )

    def action_delete_fee_v2(self):
        self.ensure_one()

        fee_ids = [fid for fid in self.fee_line_ids.mapped("fee_id") if fid]
        if not fee_ids:
            raise UserError(_("Please select at least one fee to delete."))

        client = self.env["atlax.api.client"]
        url = client.url("/v2/admin/fees")
        headers = client.build_headers()
        if not headers.get("X-API-KEY") or not headers.get("X-API-SECRET"):
            raise UserError(_("API key or secret is missing. Configure env or system parameters."))

        payload = {"fee_ids": fee_ids}

        try:
            response = requests.delete(url, json=payload, headers=headers, timeout=30)
        except requests.RequestException as e:
            _logger.exception("Error while calling Atlax /v2/admin/fees DELETE: %s", e)
            raise UserError(_("Failed to delete fee(s) due to a network error. Please try again."))

        if response.status_code not in (200, 204):
            raise UserError(_("Failed to delete fee(s): %s") % response.text)

        # Remove the selected lines locally to reflect the API deletion.
        self.fee_line_ids.unlink()

        return {"type": "ir.actions.act_window_close"}
