odoo.define("atlaxchange_ledger.AtlaxchangeDashboard", function(require) {
    "use strict";

    var AbstractAction = require("web.AbstractAction");
    var core = require("web.core");
    var QWeb = core.qweb;
    var rpc = require("web.rpc");

    var AtlaxchangeDashboard = AbstractAction.extend({
        contentTemplate: "AtlaxchangeDashboard",

        init: function(parent, context) {
            this._super(parent, context);
            this.dashboard_templates = ["MainSection"];
        },

        start: function() {
            var self = this;
            this.set("title", "Dashboard");
            return this._super().then(function() {
                self.render_dashboards();
            });
        },

        render_dashboards: function() {
            var self = this;
            this.fetch_data().then(function(result) {
                self.$(".o_hr_dashboard").empty();
                _.each(self.dashboard_templates, function(template) {
                    self.$(".o_hr_dashboard").append(QWeb.render(template, { widget: self, data: result }));
                });
            });
        },

        fetch_data: function() {
            return rpc.query({
                model: "atlaxchange.ledger.dashboard",
                method: "get_dashboard_data",
            }).then(function(result) {
                if (!result || typeof result !== "object") {
                    console.error("Invalid data received from the backend:", result);
                    return {
                        total_transactions_count: 0,
                        total_successful_payouts_count: 0,
                        pending_payouts_count: 0,
                        failed_payouts_count: 0,
                    };
                }
                return result;
            }).catch(function(error) {
                console.error("Error fetching dashboard data:", error);
                return {
                    total_transactions_count: 0,
                    total_successful_payouts_count: 0,
                    pending_payouts_count: 0,
                    failed_payouts_count: 0,
                };
            });
        },
    });

    core.action_registry.add("atlax_dashboard", AtlaxchangeDashboard);

    return AtlaxchangeDashboard;
});