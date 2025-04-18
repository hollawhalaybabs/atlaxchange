from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class ResCurrency(models.Model):
    _inherit = 'res.currency'

    # Add custom fields if needed
    atlax_description = fields.Text(string="Atlax Description")
    name = fields.Char(string='Currency', size=4, required=True, help="Currency Code (ISO 4217)")

class AtlaxCurrencyRate(models.Model):
    _name = 'atlax.currency.rate'
    _description = 'Atlax Currency Rate'
    _inherit = ['mail.thread', 'mail.activity.mixin']  # Enable notifications and tracking

    source_currency_id = fields.Many2one(
        'res.currency', 
        string="Source Currency", 
        required=True, 
        help="The currency from which the rate is being set."
    )
    target_currency_id = fields.Many2one(
        'res.currency', 
        string="Target Currency", 
        required=True, 
        help="The currency to which the rate is being set."
    )
    rate = fields.Float(
        string="Exchange Rate", 
        required=True, 
        help="The exchange rate from the source currency to the target currency."
    )
    name = fields.Char(
        string="Description", 
        compute="_compute_name", 
        store=True, 
        help="A description of the exchange rate."
    )
    active = fields.Boolean(
        string="Active", 
        default=True, 
        help="Indicates whether the rate is active. Previous rates are archived."
    )

    @api.depends('source_currency_id', 'target_currency_id')
    def _compute_name(self):
        """Compute a descriptive name for the exchange rate."""
        for record in self:
            if record.source_currency_id and record.target_currency_id:
                record.name = f"{record.source_currency_id.name}/{record.target_currency_id.name}"

    @api.constrains('source_currency_id', 'target_currency_id')
    def _check_currency_ids(self):
        """Ensure that source and target currencies are not the same."""
        for record in self:
            if record.source_currency_id == record.target_currency_id:
                raise ValidationError(_("Source and target currencies must be different."))

    @api.model
    def create(self, vals):
        """Override create to validate and archive previous rates."""
        # Validate that the rate is positive
        if vals.get('rate') <= 0:
            raise ValidationError(_("The exchange rate must be greater than zero."))

        # Archive previous rates for the same currency pair
        existing_rates = self.search([
            ('source_currency_id', '=', vals.get('source_currency_id')),
            ('target_currency_id', '=', vals.get('target_currency_id')),
            ('active', '=', True)
        ])
        existing_rates.write({'active': False})

        # Notify followers about the new rate
        self._notify_followers(vals)

        return super(AtlaxCurrencyRate, self).create(vals)

    def _notify_followers(self, vals):
        """Send notifications to followers or subscribed users."""
        message = _(
            "A new exchange rate has been set: %(source)s/%(target)s = %(rate).2f",
            source=self.env['res.currency'].browse(vals.get('source_currency_id')).name,
            target=self.env['res.currency'].browse(vals.get('target_currency_id')).name,
            rate=vals.get('rate')
        )
        self.message_post(
            body=message,
            subject="New Exchange Rate Set",
            subtype_xmlid="mail.mt_note"
        )

    @api.model
    def get_rate(self, source_currency, target_currency):
        """Get the exchange rate between two currencies."""
        rate_record = self.search([
            ('source_currency_id', '=', source_currency.id),
            ('target_currency_id', '=', target_currency.id)
        ], limit=1)
        if not rate_record:
            raise ValueError(_("No exchange rate found for %s to %s.") % (source_currency.name, target_currency.name))
        return rate_record.rate