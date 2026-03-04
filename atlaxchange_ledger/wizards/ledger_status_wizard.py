from odoo import api, fields, models, _
from odoo.exceptions import UserError
import logging
import requests
import json

_logger = logging.getLogger(__name__)

class AtlaxchangeLedgerStatusWizard(models.TransientModel):
    _name = 'atlaxchange.ledger.status.wizard'
    _description = 'Wizard to change ledger transactions status (bulk)'

    ledger_ids = fields.Many2many('atlaxchange.ledger', string='Ledgers')
    target_status = fields.Selection([
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('success', 'Success'),
        ('failed', 'Failed'),
    ], string='Target Status', required=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_model = self.env.context.get('active_model')
        active_ids = self.env.context.get('active_ids') or []
        if active_model == 'atlaxchange.ledger' and active_ids:
            res.update({'ledger_ids': [(6, 0, active_ids)]})
        return res

    def action_apply_status(self):
        if not self.ledger_ids:
            raise UserError(_("No ledger records selected."))

        # Prevent changing from 'reversed' to 'success'
        if self.target_status == 'success':
            reversed_recs = self.ledger_ids.filtered(lambda l: l.status == 'reversed')
            if reversed_recs:
                refs = ', '.join(reversed_recs.mapped('transaction_reference') or ['(no ref)'])
                raise UserError(_("Cannot change status from 'Reversed' to 'Success' for selected records: %s") % refs)

        references = [l.transaction_reference for l in self.ledger_ids if l.transaction_reference]
        if not references:
            raise UserError(_("Selected ledgers do not contain transaction references."))

        # Headers and URL via centralized client
        client = self.env['atlax.api.client']
        headers = client.build_headers()
        if not headers.get('X-API-KEY') or not headers.get('X-API-SECRET'):
            raise UserError(_("API key or secret is missing. Configure env or system parameters."))

        api_url = client.url('/v1/admin/ledger/transactions')
        payload = {"references": references, "target_status": self.target_status}
        # show payload as valid JSON (items quoted)
        # raise UserError(json.dumps(payload))

        try:
            response = requests.patch(api_url, headers=headers, json=payload, timeout=30)
            # raise UserError(response.text or response.content)
            if response.status_code in (200, 201):
                # update local records
                self.ledger_ids.write({'status': self.target_status})
                # post a message on each ledger
                for l in self.ledger_ids:
                    l.message_post(body=_("Status set to %s via bulk update") % dict(self._fields['target_status'].selection).get(self.target_status))
                return {'type': 'ir.actions.client', 'tag': 'reload'}
            else:
                # include status and content for debugging
                raise UserError(_("Update failed: Status %s - %s") % (response.status_code, (response.text or response.content)))
        except requests.RequestException as e:
            raise UserError(_("Error sending request: %s") % str(e))