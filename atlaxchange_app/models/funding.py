from odoo import models, fields, api, _
from odoo.exceptions import UserError

class Funding(models.Model):
    _name = 'atlaxchange.funding'
    _description = 'Funding Process'

    name = fields.Char(string="Reference", required=True, copy=False, readonly=True, default='New')
    funding_type = fields.Selection([
        ('atlax_wallet', 'Atlax Wallet'),
        ('customer_wallet', 'Customer Wallet')
    ], string="Funding Type", required=True)
    customer_name = fields.Many2one('res.partner', string="Customer", required=True)
    source_currency = fields.Many2one('res.currency', string="Source Currency", required=True)
    wallet_currency = fields.Many2one('res.currency', string="Wallet Currency", required=True)
    conversion_rate = fields.Float(string="Conversion Rate", required=True, default=1.0)
    amount = fields.Float(string="Amount", required=True)
    amount_credit = fields.Float(string="Amount to Credit", compute="_compute_amount_credit", store=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('approval', 'Awaiting Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('funded', 'Funded'),
    ], string="Status", default='draft', readonly=True)
    approver_id = fields.Many2one('res.users', string="Approver", readonly=True)
    approval_level = fields.Selection([
        ('hoo', 'HOO'),
        ('hot_t', 'HOT&T'),
        ('coo', 'COO'),
        ('ceo', 'CEO')
    ], string="Approval Level", readonly=True)
    is_approver = fields.Boolean(compute="_compute_is_approver")

    @api.depends('amount', 'conversion_rate')
    def _compute_amount_credit(self):
        """Compute the amount to credit based on the conversion rate."""
        for record in self:
            record.amount_credit = record.amount * record.conversion_rate

    @api.model
    def create(self, vals):
        if vals.get('name', 'New') == 'New':
            vals['name'] = self.env['ir.sequence'].next_by_code('atlaxchange.funding') or 'New'
        return super(Funding, self).create(vals)

    def action_submit_for_approval(self):
        """Submit the funding request for approval and send an email notification."""
        self.state = 'approval'
        self._set_approval_level()

        # Send email notification to the approver
        template = self.env.ref('atlaxchange_app.email_template_funding_request')
        if template:
            for record in self:
                template.send_mail(record.id, force_send=True)

    def _set_approval_level(self):
        """Set the approval level based on the amount to credit and notify the approver."""
        for record in self:
            if record.amount_credit < 5000000:
                record.approval_level = 'hoo'
            elif 5000000 <= record.amount_credit <= 50000000:
                record.approval_level = 'hot_t'
            elif record.amount_credit > 50000000:
                record.approval_level = 'coo'

            # Send email notification to the approver based on the approval level
            template = self.env.ref('atlaxchange_app.email_template_funding_request')
            if template and record.approval_level:
                approver_group = {
                    'hoo': 'atlaxchange_app.group_hoo',
                    'hot_t': 'atlaxchange_app.group_hot',
                    'coo': 'atlaxchange_app.group_coo',
                    'ceo': 'atlaxchange_app.group_ceo',
                }.get(record.approval_level)

                # Find users in the approver group
                approvers = self.env['res.users'].search([('groups_id', 'in', self.env.ref(approver_group).id)])
                for approver in approvers:
                    template.with_context(approver_email=approver.email).send_mail(record.id, force_send=True)

    def action_approve(self):
        """Approve the funding request and send an email notification."""
        self.state = 'approved'
        self.approver_id = self.env.user

        # Send approval email
        template = self.env.ref('atlaxchange_app.email_template_funding_approved')
        if template:
            for record in self:
                template.send_mail(record.id, force_send=True)

    def action_reject(self):
        """Reject the funding request and send an email notification."""
        self.state = 'rejected'
        # Send rejection email
        template = self.env.ref('atlaxchange_app.email_template_funding_rejected')
        if template:
            for record in self:
                template.send_mail(record.id, force_send=True)

    @api.depends('approval_level')
    def _compute_is_approver(self):
        for record in self:
            if record.approval_level == 'hoo':
                record.is_approver = self.env.user.has_group('atlaxchange_app.group_hoo')
            elif record.approval_level == 'hot_t':
                record.is_approver = self.env.user.has_group('atlaxchange_app.group_hot')
            elif record.approval_level == 'coo':
                record.is_approver = self.env.user.has_group('atlaxchange_app.group_coo')
            elif record.approval_level == 'ceo':
                record.is_approver = self.env.user.has_group('atlaxchange_app.group_ceo')
            else:
                record.is_approver = False

    def action_fund_wallet(self):
        """Fund the customer's wallet after approval and send an email notification."""
        if self.state != 'approved':
            raise UserError(_("You can only fund the wallet after the funding request is approved."))
        
        # Logic to fund the customer's wallet
        # Example: Add the amount_credit to the customer's ledger
        # self.customer_name.ledger_ids.create({
        #     'partner_id': self.customer_name.id,
        #     'currency_id': self.wallet_currency.id,
        #     'balance': self.amount_credit,
        #     'description': f"Funding from {self.name}",
        # })
        self.state = 'funded'  # Transition to the 'funded' state

        # Send funded email
        template = self.env.ref('atlaxchange_app.email_template_funding_funded')
        if template:
            for record in self:
                template.send_mail(record.id, force_send=True)
