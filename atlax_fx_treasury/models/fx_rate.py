from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class AtlaxFxRate(models.Model):
    _name = 'atlax.fx.rate'
    _description = 'FX Business Rate Computation'
    _order = 'date desc, id desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']   # chatter / activities

    name = fields.Char(string='Reference', required=True, copy=False,
                       default=lambda self: _('New'))
    date = fields.Date(default=fields.Date.context_today, tracking=True)
    currency_id = fields.Many2one(
        'supported.currency', required=True, tracking=True,
        help='Currency for which rates are being computed'
    )

    liquidity_source_ids = fields.One2many(
        'atlax.liquidity.source.rate', 'computation_id',
        string='Liquidity Sources', copy=True
    )

    average_rate = fields.Float(
        compute='_compute_average_rate', store=True, digits=(16, 2),
        help='Arithmetic mean of linked liquidity rates'
    )
    margin = fields.Integer(
        default=3.0, tracking=True,
        help='Margin (₦) subtracted from average to form business rate; must be between 3 and 10'
    )
    business_rate = fields.Float(
        compute='_compute_business_rate', store=True, digits=(16, 2),
        help='Rate offered by Atlax to partners (avg – margin)'
    )

    state = fields.Selection([
        ('draft', 'Draft'),
        ('review', 'Review'),
        ('done',   'Done')
    ], default='draft', tracking=True)

    # --------------------------------------------
    # Computations & constraints
    # --------------------------------------------
    @api.depends('liquidity_source_ids.rate')
    def _compute_average_rate(self):
        for rec in self:
            rates = rec.liquidity_source_ids.mapped('rate')
            rec.average_rate = sum(rates) / len(rates) if rates else 0.0

    @api.depends('average_rate', 'margin')
    def _compute_business_rate(self):
        for rec in self:
            rec.business_rate = rec.average_rate - rec.margin if rec.average_rate else 0.0

    @api.constrains('margin')
    def _check_margin(self):
        for rec in self:
            if rec.margin < 3 or rec.margin > 10:
                raise ValidationError(_('Margin must be between 3 and 10.'))

    # --------------------------------------------
    # State transitions
    # --------------------------------------------
    def action_submit(self):
        self.write({'state': 'review'})

    def action_approve(self):
        self.write({'state': 'done'})

    def action_set_draft(self):
        self.write({'state': 'draft'})

    # --------------------------------------------
    # Create / sequence
    # --------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env['ir.sequence'].next_by_code('atlax.fx.rate')
        for vals in vals_list:
            vals.setdefault('name', seq)
        return super().create(vals_list)


class AtlaxLiquiditySourceRate(models.Model):
    _name = 'atlax.liquidity.source.rate'
    _description = 'Liquidity Source Rate'
    _order = 'rate desc'

    computation_id = fields.Many2one(
        'atlax.fx.rate', required=True, ondelete='cascade')
    source_partner_id = fields.Many2one(
        'res.partner', required=True, string='Liquidity Partner')
    rate = fields.Float(required=True, digits=(16, 2))
