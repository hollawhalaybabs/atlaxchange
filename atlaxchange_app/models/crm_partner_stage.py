from odoo import models, fields, api
from collections import defaultdict
from datetime import datetime, timedelta
import logging

_logger = logging.getLogger(__name__)

class WebsiteVisitor(models.Model):
    _name = 'atlaxchange.website.visitor'
    _description = 'Website Visitor'

    name = fields.Char(string='Visitor Name')
    email = fields.Char(string='Email')
    visit_date = fields.Datetime(string='Visit Date', default=fields.Datetime.now)
    page_url = fields.Char(string='Page URL')


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    def send_reminder_emails(self):
        """Send reminder emails based on lead conditions."""
        # Fetch email templates
        verify_account_template = self.env.ref('atlaxchange_app.email_template_verify_account')
        credit_wallet_template = self.env.ref('atlaxchange_app.email_template_credit_wallet')
        start_transaction_template = self.env.ref('atlaxchange_app.email_template_start_transaction')
        resume_transaction_template = self.env.ref('atlaxchange_app.email_template_resume_transaction')

        # Fetch CRM stages
        new_stage = self.env['crm.stage'].search([('name', '=', 'New')], limit=1)
        qualified_stage = self.env['crm.stage'].search([('name', '=', 'Qualified')], limit=1)
        won_stage = self.env['crm.stage'].search([('name', '=', 'Won')], limit=1)

        # Leads in "New" stage with email not verified
        leads_verify_account = self.search([
            ('stage_id', '=', new_stage.id),
            ('partner_id.is_email_verified', '=', False)
        ])
        for lead in leads_verify_account:
            verify_account_template.send_mail(lead.id, force_send=True)

        # Leads in "New" stage with zero total balance across all currencies
        leads_credit_wallet = self.search([
            ('stage_id', '=', new_stage.id)
        ]).filtered(lambda lead: sum(ledger.balance for ledger in lead.partner_id.ledger_ids) == 0)
        for lead in leads_credit_wallet:
            credit_wallet_template.send_mail(lead.id, force_send=True)

        # Leads in "Qualified" stage
        leads_start_transaction = self.search([
            ('stage_id', '=', qualified_stage.id)
        ])
        for lead in leads_start_transaction:
            start_transaction_template.send_mail(lead.id, force_send=True)

        # Leads in "Won" stage with no transactions in the past week
        one_week_ago = datetime.now() - timedelta(days=7)
        leads_resume_transaction = self.search([
            ('stage_id', '=', won_stage.id),
            ('create_date', '<', one_week_ago)
        ]).filtered(lambda lead: not lead.partner_id.partner_ledger_ids)
        for lead in leads_resume_transaction:
            resume_transaction_template.send_mail(lead.id, force_send=True)

    def update_crm_stages(self):
        """Update CRM stages based on partner conditions and update related leads."""
        # Fetch CRM stages from the crm.stage model
        stages = {
            'new': self.env['crm.stage'].search([('name', '=', 'New')], limit=1),
            'qualified': self.env['crm.stage'].search([('name', '=', 'Qualified')], limit=1),
            'won': self.env['crm.stage'].search([('name', '=', 'Won')], limit=1),
        }

        # Helper function to calculate total balance across all currencies
        def get_total_balance(partner):
            return sum(ledger.balance for ledger in partner.ledger_ids)

        # Define partner conditions and corresponding stages
        partner_conditions = [
            {
                'condition': lambda partner: not partner.ledger_ids or not partner.partner_ledger_ids,
                'stage': stages['new'],
                'log_message': "Error updating lead to 'New' stage for partner %s: %s",
            },
            {
                'condition': lambda partner: get_total_balance(partner) > 0 and not partner.partner_ledger_ids,
                'stage': stages['qualified'],
                'log_message': "Error updating lead to 'Qualified' stage for partner %s: %s",
            },
            {
                'condition': lambda partner: get_total_balance(partner) > 0 and partner.partner_ledger_ids,
                'stage': stages['won'],
                'log_message': "Error updating lead to 'Won' stage for partner %s: %s",
            },
        ]

        # Process partners for each condition
        for condition in partner_conditions:
            partners = self.env['res.partner'].search([]).filtered(condition['condition'])
            for partner in partners:
                lead = self.search([('partner_id', '=', partner.id)], limit=1)
                if lead:
                    try:
                        lead.write({'stage_id': condition['stage'].id})
                    except Exception as e:
                        _logger.error(condition['log_message'], partner.id, e)
                else:
                    try:
                        self.create({
                            'partner_id': partner.id,
                            'name': f"Lead for {partner.name}",
                            'stage_id': condition['stage'].id,
                        })
                    except Exception as e:
                        _logger.error("Error creating lead for partner %s: %s", partner.id, e)

        # Handle partners with email not verified (specific case for 'New' stage)
        partners_email_not_verified = self.env['res.partner'].search([('is_email_verified', '=', False)])
        for partner in partners_email_not_verified:
            lead = self.search([('partner_id', '=', partner.id)], limit=1)
            if lead:
                try:
                    lead.write({'stage_id': stages['new'].id})
                except Exception as e:
                    _logger.error("Error updating lead to 'New' stage for email not verified for partner %s: %s", partner.id, e)
            else:
                try:
                    self.create({
                        'partner_id': partner.id,
                        'name': f"Lead for {partner.name}",
                        'stage_id': stages['new'].id,
                    })
                except Exception as e:
                    _logger.error("Error creating lead for partner %s: %s", partner.id, e)