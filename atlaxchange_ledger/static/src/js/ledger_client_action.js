odoo.define('atlaxchange_ledger.client_action', function (require) {
    "use strict";
    var AbstractAction = require('web.AbstractAction');
    var core = require('web.core');
    var rpc = require('web.rpc');
    var viewRegistry = require('web.view_registry');
    var QWeb = core.qweb;

    var LedgerClientAction = AbstractAction.extend({
        template: 'AtlaxchangeLedgerClientAction',
        events: {
            'click .btn-fetch-ledger': '_onFetchLedger',
        },
        start: function () {
            // Render the tree view inside this client action
            this._renderTree();
            return this._super.apply(this, arguments);
        },
        _renderTree: function () {
            var self = this;
            this.$('.o_ledger_tree_container').empty();
            this.do_action({
                type: 'ir.actions.act_window',
                res_model: 'atlaxchange.ledger',
                view_mode: 'tree,form',
                target: 'current',
                views: [[false, 'tree'], [false, 'form']],
                context: {},
            }, {
                on_close: function () {
                    // Optionally refresh after closing a record
                }
            });
        },
        _onFetchLedger: function () {
            var self = this;
            this.$('.btn-fetch-ledger').prop('disabled', true);
            rpc.query({
                model: 'atlaxchange.ledger',
                method: 'fetch_ledger_history',
                args: [],
            }).then(function () {
                self.do_notify('Success', 'Ledger history fetched!');
                self._renderTree();
            }).always(function () {
                self.$('.btn-fetch-ledger').prop('disabled', false);
            });
        },
    });

    core.action_registry.add('atlaxchange_ledger_client_action', LedgerClientAction);
    return LedgerClientAction;
});