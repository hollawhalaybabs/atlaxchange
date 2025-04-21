odoo.define('atlaxchange_ledger.LedgerDashboard', function (require) {
    "use strict";

    const { Component, useState, onWillStart } = owl;
    const { registry } = require("@web/core/registry");
    const { loadTemplates } = require("@web/core/assets");
    const rpc = require('web.rpc');

    class LedgerDashboard extends Component {
        /**
         * Dynamically load the template for the component.
         */
        static async setup() {
            try {
                await loadTemplates(["LedgerDashboard"]);
                console.log("Template 'LedgerDashboard' loaded successfully.");
            } catch (error) {
                console.error("Error loading template 'LedgerDashboard':", error);
            }
        }

        /**
         * Component state initialization.
         */
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

        /**
         * Fetch dashboard data from the server.
         */
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

        /**
         * Lifecycle hook to fetch data before rendering.
         */
        setup() {
            onWillStart(() => this.fetchDashboardData());
        }
    }

    // Register the component in the action registry
    registry.category("actions").add("LedgerDashboard", LedgerDashboard);

    return LedgerDashboard;
});
