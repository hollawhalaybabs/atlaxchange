from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class AtlaxBDTag(models.Model):
    _name = "atlax.bd.tag"
    _description = "BD Tag"
    _order = "name"

    name = fields.Char(required=True)
    color = fields.Integer(string="Color")


class HelpdeskTicket(models.Model):
    _inherit = "helpdesk.ticket"

    bd_opportunity_id = fields.Many2one(
        "atlax.bd.opportunity",
        string="BD Opportunity",
        index=True,
        ondelete="set null",
    )


class AtlaxBusinessOpportunity(models.Model):
    _name = "atlax.bd.opportunity"
    _description = "Business Development Opportunity"
    _order = "name, datetime desc"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(string="Name", required=True, tracking=True)
    type = fields.Selection(
            selection=[
            ("customer_imto", "Customer (IMTO)"),
            ("vendor", "Vendor"),
        ],
        string="Type",
        required=True,
        tracking=True,
    )
    vendor_type = fields.Selection(
        selection=[
            ("payout", "Payout"),
            ("collection", "Collection"),
            ("payout_collection", "Payout and Collection"),
        ],
        string="Vendor Type",
        tracking=True,
    )

    email = fields.Char(string="Email", required=True, tracking=True)
    website = fields.Char(string="Website")
    datetime = fields.Datetime(
        string="Datetime",
        default=fields.Datetime.now,
        readonly=True,
    )

    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("proposal_sent", "Proposal Sent"),
            ("initial_discussion", "Initial Discussion"),
            ("nda_signoff", "NDA Signoff"),
            ("commercial_discussion", "Commercial Discussion"),
            ("kyb_review", "KYB Review"),
            ("contract_signoff", "Contract Signoff"),
            ("integration", "Integration"),
            ("onhold", "On Hold"),
            ("done", "Done"),
        ],
        string="Status",
        default="draft",
        tracking=True,
    )

    settlement_currency_id = fields.Many2one(
        "supported.currency",
        string="Settlement Currency",
    )

    proposal_document = fields.Binary(string="Proposal Document")
    proposal_filename = fields.Char(string="Proposal Filename")

    nda_document = fields.Binary(string="NDA Document")
    nda_filename = fields.Char(string="NDA Filename")

    kyb_status = fields.Selection(
        selection=[
            ("in_process", "In-process"),
            ("completed", "Completed"),
        ],
        string="KYB Status",
    )

    funding_type = fields.Selection(
        selection=[
            ("pre_funding", "Pre-funding"),
            ("post_funding", "Post funding"),
        ],
        string="Funding Type"
    )

    remark = fields.Text(string="Remark/Note")

    fee_ids = fields.One2many(
        "atlax.bd.fee",
        "bd_id",
        string="Fees",
    )

    assign_staff_id = fields.Many2one(
        "res.users",
        string="Assign Staff",
        required=True,
        default=lambda self: self.env.user,
    )

    helpdesk_ticket_count = fields.Integer(
        string="Helpdesk Tickets",
        compute="_compute_helpdesk_ticket_count",
    )

    tag_ids = fields.Many2many(
        "atlax.bd.tag",
        "atlax_bd_opportunity_tag_rel",
        "bd_opportunity_id",
        "tag_id",
        string="Tags",
        tracking=True,
    )

    @api.constrains("type", "vendor_type")
    def _check_vendor_type(self):
        for rec in self:
            if rec.type == "vendor" and not rec.vendor_type:
                raise ValidationError(_("Vendor Type is required when Type is Vendor."))

    @api.constrains("state", "proposal_document", "nda_document", "kyb_status", "settlement_currency_id", "fee_ids")
    def _check_state_requirements(self):
        for rec in self:
            if rec.state == "proposal_sent" and not rec.proposal_document:
                raise ValidationError(_("Upload Proposal document is required at Proposal Sent state."))
            if rec.state == "nda_signoff" and not rec.nda_document:
                raise ValidationError(_("Upload NDA document is required at NDA Signoff state."))
            if rec.state == "kyb_review" and not rec.kyb_status:
                raise ValidationError(_("KYB Status is required at KYB Review state."))
            if rec.state == "commercial_discussion":
                if not rec.settlement_currency_id:
                    raise ValidationError(_("Settlement Currency is required at Commercial Discussion state."))
                if not rec.fee_ids:
                    raise ValidationError(_("At least one Fee line is required at Commercial Discussion state."))

    # State transition helpers

    def action_set_draft(self):
        for rec in self:
            rec.state = "draft"

    def action_set_initial_discussion(self):
        for rec in self:
            rec.state = "initial_discussion"        

    def action_set_proposal_sent(self):
        for rec in self:
            rec.state = "proposal_sent"

    def action_set_nda_signoff(self):
        for rec in self:
            rec.state = "nda_signoff"

    def action_set_commercial_discussion(self):
        for rec in self:
            rec.state = "commercial_discussion"

    def action_set_kyb_review(self):
        for rec in self:
            rec.state = "kyb_review"

    def action_set_contract_signoff(self):
        for rec in self:
            rec.state = "contract_signoff"

    def action_set_integration(self):
        for rec in self:
            rec.state = "integration"

    def action_set_onhold(self):
        for rec in self:
            rec.state = "onhold"

    def action_set_done(self):
        for rec in self:
            rec.state = "done"

    def _action_open_email_composer(self, template_xmlid):
        """Open a compose popup (review/edit) prefilled with the given template."""
        self.ensure_one()
        template = self.env.ref(template_xmlid, raise_if_not_found=False)
        if not template:
            raise ValidationError(_("Email template not found: %s") % template_xmlid)

        ctx = dict(
            self.env.context,
            default_model=self._name,
            default_res_id=self.id,
            default_use_template=True,
            default_template_id=template.id,
            default_composition_mode="comment",  # logs in chatter + keeps full thread
            force_email=True,                   # ensure it's an email, not only an internal note
            mail_post_autofollow=True,          # recipients get subscribed automatically
            default_notify=True,
        )

        return {
            "type": "ir.actions.act_window",
            "name": _("Compose Email"),
            "res_model": "mail.compose.message",
            "view_mode": "form",
            "target": "new",
            "context": ctx,
        }

    def action_send_reminder_email(self):
        for rec in self:
            return rec._action_open_email_composer(
                "atlax_business_development.email_template_bd_reminder"
            )

    def action_send_proposal_email(self):
        for rec in self:
            xmlid = "atlax_business_development.email_template_bd_proposal_vendor"
            if rec.type == "customer_imto":
                xmlid = "atlax_business_development.email_template_bd_proposal_customer"
            return rec._action_open_email_composer(xmlid)

    def action_send_nda_email(self):
        for rec in self:
            return rec._action_open_email_composer(
                "atlax_business_development.email_template_bd_nda"
            )

    def _compute_helpdesk_ticket_count(self):
        Ticket = self.env["helpdesk.ticket"]
        for rec in self:
            rec.helpdesk_ticket_count = Ticket.search_count([("bd_opportunity_id", "=", rec.id)])

    def action_open_helpdesk_tickets(self):
        self.ensure_one()
        action = self.env.ref("helpdesk.helpdesk_ticket_action_main_tree", raise_if_not_found=False)
        if action:
            action = action.read()[0]
        else:
            action = {
                "type": "ir.actions.act_window",
                "name": _("Helpdesk Tickets"),
                "res_model": "helpdesk.ticket",
                "view_mode": "tree,form",
            }

        action["domain"] = [("bd_opportunity_id", "=", self.id)]
        action["context"] = dict(self.env.context, default_bd_opportunity_id=self.id)
        return action


class AtlaxBusinessFee(models.Model):
    _name = "atlax.bd.fee"
    _description = "Business Development Fee"

    bd_id = fields.Many2one(
        "atlax.bd.opportunity",
        string="Opportunity",
        ondelete="cascade",
    )
    source_currency_id = fields.Many2one(
        "supported.currency",
        string="Source Currency",
        required=True,
    )
    target_currency_id = fields.Many2one(
        "supported.currency",
        string="Target Currency",
        required=True,
    )
    corridor = fields.Char(
        string="Corridor",
        compute="_compute_corridor",
        store=True,
    )
    fee_amount = fields.Float(string="Fee Amount")

    @api.depends("source_currency_id", "target_currency_id")
    def _compute_corridor(self):
        for rec in self:
            if rec.source_currency_id and rec.target_currency_id:
                rec.corridor = "%s/%s" % (
                    rec.source_currency_id.currency_code,
                    rec.target_currency_id.currency_code,
                )
            else:
                rec.corridor = False
