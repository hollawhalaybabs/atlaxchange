{
    "name": "Jira Integration",
    "version": "1.0",
    "category": "Project",
    "summary": "Sync tasks between Jira and Odoo",
    'author': 'Novus Solutions',
    'website': 'https://www.novussolutionsltd.com',
    "depends": ["project"],
    "data": [
        "data/ir_cron.xml",
        "security/ir.model.access.csv",
        "views/project_task_views.xml",
        ],
    "installable": True,
    "application": False
}
