/** Add a global Refresh button to the ledger list view **/
odoo.define('atlaxchange_ledger.ledger_refresh_button', function (require) {
    "use strict";
    const ListController = require('web.ListController');
    const viewRegistry = require('web.view_registry');
    const ListView = require('web.ListView');

    const LedgerListController = ListController.extend({
        renderButtons() {
            this._super.apply(this, arguments);
            if (this.$buttons) {
                const refreshBtn = $('<button type="button" class="btn btn-primary o_ledger_refresh_btn">Refresh</button>');
                refreshBtn.on('click', () => {
                    this._rpc({
                        model: 'atlaxchange.ledger',
                        method: 'fetch_ledger_history',
                        args: [],
                    }).then(() => {
                        this.reload();
                    });
                });
                this.$buttons.prepend(refreshBtn);
            }
        },
    });

    const LedgerListView = ListView.extend({
        config: _.extend({}, ListView.prototype.config, {
            Controller: LedgerListController,
        }),
    });

    viewRegistry.add('ledger_list_with_refresh', LedgerListView);
});