# -*- coding: utf-8 -*-
import requests
import logging
import base64
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

JIRA_BASE_URL = "https://atlaxhub.atlassian.net"
JIRA_API_URL = f"{JIRA_BASE_URL}/rest/api/3"

# Replace with your Jira username and API token
JIRA_USERNAME = "tech@atlaxchange.com"
JIRA_API_TOKEN = "ATATT3xFfGF0TNxePHweHRtvNES8Ef3B-OpGKOWRvZjIPQnhhch3fYHJ8E3Z-_Vc8pGKwHalNuGhyRZyBV7N11ecpPfQs0b5MIo47edK5RUiw0MDZ2MYU_-mbQFN7vqnEaPB6rdT5029TANJvy-wMRtCWmNMfE2ba9m3WzpSvaeVf5ZN-Y6aOpc=F142CE28"

# Encode the username and API token in Base64 for Basic Authentication
auth_string = f"{JIRA_USERNAME}:{JIRA_API_TOKEN}"
auth_bytes = auth_string.encode("utf-8")
auth_base64 = base64.b64encode(auth_bytes).decode("utf-8")

JIRA_HEADERS = {
    "Authorization": f"Basic {auth_base64}",
    "Content-Type": "application/json"
}


class JiraIntegration(models.Model):
    _name = 'jira.integration'
    _description = 'Jira Integration Handler'

    @api.model
    def sync_jira_issues(self):
        """Fetch Jira issues and sync them with Odoo tasks."""
        # Define parameters for the GET request
        params = {
            "jql": "project = AT ORDER BY created DESC",  
            "startAt": 0,
            "maxResults": 50,
        }
        response = requests.get(f"{JIRA_API_URL}/search", headers=JIRA_HEADERS, params=params)
        if response.status_code != 200:
            raise UserError(_("Failed to fetch Jira issues: %s") % response.text)

        # Parse the response data
        issues = response.json().get('issues', [])
        if not issues:
            return

        # Get the default "Internal" project
        internal_project = self.env['project.project'].search([('name', '=', 'Atlaxchange')], limit=1)
        if not internal_project:
            raise UserError(_("The default 'Atlaxchange' project does not exist. Please create it in Odoo."))

        # Process each issue
        for issue in issues:
            issue_key = issue['key']
            fields = issue['fields']
            summary = fields.get('summary', 'No Summary')
            status = fields.get('status', {}).get('name', 'Unknown')
            description = fields.get('description', 'No Description')

            # Find the corresponding stage based on the status name
            stage = self.env['project.task.type'].search([('name', 'ilike', status)], limit=1)
            if not stage:
                stage = self.env['project.task.type'].search([], limit=1)  

            # Check if the issue already exists in Odoo
            task = self.env['project.task'].search([('jira_key', '=', issue_key)], limit=1)
            task_vals = {
                'name': f"{issue_key} - {summary or 'No Description'}",  
                'jira_key': issue_key,
                'description': summary,  # Set the description to the summary of the Jira issue
                'stage_id': stage.id,  
                'project_id': internal_project.id,  # Link to the "Atlaxchange" project
            }
            if not task:
                self.env['project.task'].create(task_vals)
            else:
                task.write(task_vals)

    # @api.model
    # def sync_odoo_tasks_to_jira(self):
    #     tasks = self.env['project.task'].search([('jira_key', '=', False)])
    #     for task in tasks:
    #         payload = {
    #             "fields": {
    #                 "project": { "key": "YOUR_PROJECT_KEY" },
    #                 "summary": task.name,
    #                 "description": task.description or "Created from Odoo",
    #                 "issuetype": { "name": "Task" }
    #             }
    #         }
    #         response = requests.post(f"{JIRA_API_URL}/issue", json=payload, headers=JIRA_HEADERS)
    #         if response.status_code == 201:
    #             task.jira_key = response.json().get("key")
    #         else:
    #             raise UserError(_("Failed to create Jira issue: %s") % response.text)


class ProjectTask(models.Model):
    _inherit = 'project.task'

    jira_key = fields.Char("Jira Issue Key", help="The unique key of the Jira issue.")
