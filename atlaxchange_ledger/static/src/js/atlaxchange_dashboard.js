/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { rpc } from "web.rpc";

export class AtlaxchangeDashboard extends Component {
    static template = "atlaxchange_ledger.AtlaxchangeDashboard";

    state = useState({
        totalTransactions: 0,
        successfulPayouts: 0,
        pendingPayouts: 0,
        failedPayouts: 0,
        loading: true,
        error: null,
    });

    async fetchDashboardData() {
        try {
            const result = await rpc.query({
                model: "atlaxchange.ledger.dashboard",
                method: "get_dashboard_data",
            });
            this.state.totalTransactions = result.total_transactions_count || 0;
            this.state.successfulPayouts = result.total_successful_payouts_count || 0;
            this.state.pendingPayouts = result.pending_payouts_count || 0;
            this.state.failedPayouts = result.failed_payouts_count || 0;
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