odoo.define("atlaxchange_ledger.AtlaxchangeDashboard", function(require) {
    "use strict";

    var AbstractAction = require("web.AbstractAction");
    var core = require("web.core");
    var QWeb = core.qweb;
    var rpc = require("web.rpc");

    var AtlaxchangeDashboard = AbstractAction.extend({
        contentTemplate: "AtlaxchangeDashboard",

        start: function() {
            var self = this;
            return this._super().then(function() {
                self.render_dashboards();
            });
        },

        render_dashboards: function() {
            var self = this;
            this.fetch_data().then(function(result) {
                self.$(".o_hr_dashboard").empty();
                self.$(".o_hr_dashboard").append(QWeb.render("AtlaxchangeDashboard", { data: result }));
            });
        },

        fetch_data: function() {
            return rpc.query({
                model: "atlaxchange.ledger.dashboard",
                method: "get_dashboard_data",
            }).then(function(result) {
                return {
                    total_transactions_count: result.total_transactions_count || 0,
                    sections: [
                        { title: "Successful Payouts", value: result.total_successful_payouts_count || 0 },
                        { title: "Pending Payouts", value: result.pending_payouts_count || 0 },
                        { title: "Failed Payouts", value: result.failed_payouts_count || 0 },
                    ],
                };
            }).catch(function(error) {
                console.error("Error fetching dashboard data:", error);
                return {
                    total_transactions_count: 0,
                    sections: [
                        { title: "Successful Payouts", value: 0 },
                        { title: "Pending Payouts", value: 0 },
                        { title: "Failed Payouts", value: 0 },
                    ],
                };
            });
        },
    });

    core.action_registry.add("atlax_dashboard", AtlaxchangeDashboard);

    return AtlaxchangeDashboard;
});