odoo.define('atlaxchange_ledger.LedgerDashboard', function (require) {
    "use strict";

    const { Component, useState, onWillStart } = owl;
    const { registry } = require("@web/core/registry");
    const { loadTemplates } = require("@web/core/assets");
    const rpc = require('web.rpc');

    class LedgerDashboard extends Component {
        static template = 'LedgerDashboard'; // Set the template statically

        state = useState({
            credit: 0,
            debit: 0,
            statusCounts: {
                pending: 0,
                success: 0,
                failed: 0,
                reversed: 0,
            },
            customers: [],
            loading: true,
            error: null,
        });

        async fetchDashboardData() {
            try {
                const result = await rpc.query({
                    model: "atlaxchange.ledger",
                    method: "get_dashboard_data",
                });
                this.state.credit = result.credit || 0;
                this.state.debit = result.debit || 0;
                this.state.statusCounts = result.status_counts || {};
                this.state.customers = result.customers || [];
                this.state.loading = false;
            } catch (error) {
                console.error("Error fetching dashboard data:", error);
                this.state.error = "Failed to load dashboard data.";
                this.state.loading = false;
            }
        }

        setup() {
            onWillStart(() => this.fetchDashboardData());
        }
    }

    registry.category("actions").add("LedgerDashboard", LedgerDashboard);

    return LedgerDashboard;
});