from odoo import http
from odoo.http import request

class AtlaxchangeDashboardController(http.Controller):
    @http.route('/atlaxchange/dashboard_data', type='json', auth='user')
    def get_dashboard_data(self):
        """
        Fetch and return dynamically computed dashboard data.
        """
        try:
            # Call the dynamic computation method from the model
            dashboard_data = request.env['atlaxchange.ledger.dashboard'].get_dashboard_data()
            return dashboard_data
        except Exception as e:
            return {"error": str(e)}