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
                const changeBtn = $('<button type="button" class="btn btn-danger o_ledger_change_status_btn">Change Status</button>');
                changeBtn.css('margin-right', '8px');

                changeBtn.on('click', () => {
                    let selectedIds = [];
                    if (typeof this.getSelectedIds === 'function') {
                        selectedIds = this.getSelectedIds();
                    } else if (this.renderer && typeof this.renderer.getSelectedIds === 'function') {
                        selectedIds = this.renderer.getSelectedIds();
                    } else if (this.model && this.handle) {
                        const localData = this.model.get(this.handle) || {};
                        selectedIds = localData.selectedIDs || [];
                    }

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

                // Quick sync
                const refreshBtn = $('<button type="button" class="btn btn-primary o_ledger_refresh_btn">Refresh</button>');
                refreshBtn.on('click', () => {
                    this._rpc({
                        model: 'atlaxchange.ledger',
                        method: 'fetch_ledger_history_enqueue',
                        args: [],
                        kwargs: { sync: true, popup: false, target_count: 500, max_seconds: 8, direction: 'auto', page_size: 1000, page_size_param: 'limit' },
                    }).then((stats) => {
                        const processed = stats && stats.processed || 0;
                        const created = stats && stats.created || 0;
                        const updated = stats && stats.updated || 0;
                        const pages = stats && stats.pages || 0;
                        const partial = stats && stats.partial ? ` (partial: ${stats.reason || 'time budget'})` : '';
                        this.trigger_up('do_notify', {
                            title: "Ledger refreshed",
                            message: `Processed: ${processed}, Created: ${created}, Updated: ${updated}, Pages: ${pages}${partial}`,
                        });
                        // allow user to see the toast before reload
                        setTimeout(() => this.do_action({type: 'ir.actions.client', tag: 'reload'}), 1500);
                    }).catch(err => {
                        // If server raised ValidationError/UserError, show that message
                        const message = (err && err.data && err.data.message) ? err.data.message : String(err || 'Unknown error');
                        this.trigger_up('do_notify', {
                            title: "Fetch failed",
                            message: message,
                            sticky: true,
                        });
                    });
                });

                // Full Sync in background (~5 minutes, commits per page)
                const fullSyncBtn = $('<button type="button" class="btn btn-secondary o_ledger_fullsync_btn">Full Sync (BG)</button>');
                fullSyncBtn.css('margin-left', '8px');
                fullSyncBtn.on('click', () => {
                    this._rpc({
                        model: 'atlaxchange.ledger',
                        method: 'fetch_ledger_history_enqueue',
                        args: [],
                        kwargs: {
                            sync: false,
                            target_count: 100000,    // effectively unlimited for 20k backlog
                            max_seconds: 300,        // 5 minutes window
                            direction: 'auto',
                            commit_each_page: true,  // background-friendly
                            page_size: 1000,
                            page_size_param: 'limit',
                        },
                    }).then((result) => {
                        this.trigger_up('do_notify', {
                            title: "Full sync scheduled",
                            message: "Background sync started. This may take a few minutes.",
                        });
                    }).catch(err => {
                        const message = (err && err.data && err.data.message) ? err.data.message : String(err || 'Unknown error');
                        this.trigger_up('do_notify', { title: "Full sync failed", message, sticky: true });
                    });
                });

                // Optional larger manual sync
                const refreshBtn1000 = $('<button type="button" class="btn btn-secondary o_ledger_refresh_btn_1000">Refresh 1000</button>');
                refreshBtn1000.css('margin-left', '8px');
                refreshBtn1000.on('click', () => {
                    this._rpc({
                        model: 'atlaxchange.ledger',
                        method: 'fetch_ledger_history_enqueue',
                        args: [],
                        // kwargs override for a test run
                        kwargs: {
                          sync: true,
                          popup: false,
                          target_count: 1000,
                          max_seconds: 12,
                          direction: 'auto',
                          page_size: 1000,
                          page_size_param: 'limit',
                          after_param: 'cursor',     // ← try this
                          before_param: 'cursor'     // ← and this
                        }
                    }).then((stats) => {
                        const processed = stats && stats.processed || 0;
                        const created = stats && stats.created || 0;
                        const updated = stats && stats.updated || 0;
                        const pages = stats && stats.pages || 0;
                        const partial = stats && stats.partial ? ` (partial: ${stats.reason || 'time budget'})` : '';
                        this.trigger_up('do_notify', {
                            title: "Ledger refreshed (1000)",
                            message: `Processed: ${processed}, Created: ${created}, Updated: ${updated}, Pages: ${pages}${partial}`,
                        });
                        setTimeout(() => this.do_action({type: 'ir.actions.client', tag: 'reload'}), 1500);
                    }).catch(err => {
                        const message = (err && err.data && err.data.message) ? err.data.message : String(err || 'Unknown error');
                        this.trigger_up('do_notify', { title: "Fetch failed", message, sticky: true });
                    });
                });

                this.$buttons.prepend(fullSyncBtn);
                this.$buttons.prepend(refreshBtn1000);
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