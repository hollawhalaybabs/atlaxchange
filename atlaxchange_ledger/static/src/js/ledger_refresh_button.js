/** Add Refresh and "Change Status" buttons to the ledger list view toolbar **/
odoo.define('atlaxchange_ledger.ledger_refresh_button', function (require) {
    "use strict";
    const ListController = require('web.ListController');
    const viewRegistry = require('web.view_registry');
    const ListView = require('web.ListView');

    const LedgerListController = ListController.extend({
        renderButtons() {
            this._super.apply(this, arguments);
            if (this.$buttons) {
                // Change Status button (opens wizard for selected records)
                const changeBtn = $('<button type="button" class="btn btn-danger o_ledger_change_status_btn">Change Status</button>');
                // add right margin to create space between buttons
                changeBtn.css('margin-right', '8px');

                changeBtn.on('click', () => {
                    // try to get selected ids (with a couple of fallbacks)
                    let selectedIds = [];
                    if (typeof this.getSelectedIds === 'function') {
                        selectedIds = this.getSelectedIds();
                    } else if (this.renderer && typeof this.renderer.getSelectedIds === 'function') {
                        selectedIds = this.renderer.getSelectedIds();
                    } else if (this.model && this.handle) {
                        const localData = this.model.get(this.handle) || {};
                        selectedIds = localData.selectedIDs || [];
                    }

                    // open wizard action, pass active_ids and active_model in context
                    this.do_action({
                        name: 'Change Ledger Status',
                        type: 'ir.actions.act_window',
                        res_model: 'atlaxchange.ledger.status.wizard',
                        view_mode: 'form',
                        views: [[false, 'form']],
                        target: 'new',
                        context: {
                            active_model: 'atlaxchange.ledger',
                            active_ids: selectedIds,
                        },
                    });
                });

                // Refresh button (existing)
                const refreshBtn = $('<button type="button" class="btn btn-primary o_ledger_refresh_btn">Refresh</button>');
                refreshBtn.on('click', () => {
                    this._rpc({
                        model: 'atlaxchange.ledger',
                        method: 'fetch_ledger_history_enqueue',
                        args: [],
                    }).then((result) => {
                        // If backend confirms scheduling, reload the client automatically.
                        if (result && result.scheduled) {
                            // reload the web client
                            this.do_action({type: 'ir.actions.client', tag: 'reload'});
                        } else {
                            // fallback notify
                            this.trigger_up('do_notify', {
                                title: "Ledger",
                                message: "Ledger fetch scheduled. Data will appear when available.",
                            });
                        }
                        
                    }).catch(err => {
                        const message = (err && err.data && err.data.message) ? err.data.message : String(err || 'Unknown error');
                        this.trigger_up('do_notify', {
                            title: "Fetch failed",
                            message: message,
                            sticky: true,
                        });
                    });
                });

                // place buttons beside each other (Change Status first, then Refresh)
                this.$buttons.prepend(refreshBtn);
                this.$buttons.prepend(changeBtn);
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