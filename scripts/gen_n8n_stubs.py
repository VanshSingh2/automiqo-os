"""Generate missing n8n workflow stub JSON files."""
import json, os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def stub(name, description, webhook_path):
    return {
        "name": name,
        "nodes": [
            {
                "id": "webhook_trigger",
                "name": "Webhook",
                "type": "n8n-nodes-base.webhook",
                "parameters": {"path": webhook_path, "httpMethod": "POST"},
                "position": [250, 300]
            },
            {
                "id": "validate",
                "name": "Validate Input",
                "type": "n8n-nodes-base.code",
                "parameters": {"jsCode": f"// {description}\nconst {{ business_id, task_id, parameters }} = $input.first().json;\nif (!business_id) throw new Error('Missing business_id');\nreturn [{{ json: {{ business_id, task_id, parameters, validated: true }} }}];"},
                "position": [450, 300]
            },
            {
                "id": "respond",
                "name": "Respond",
                "type": "n8n-nodes-base.respondToWebhook",
                "parameters": {"respondWith": "json", "responseBody": "={{ { status: 'ok', workflow: '" + webhook_path + "' } }}"},
                "position": [650, 300]
            }
        ],
        "connections": {
            "Webhook": {"main": [[{"node": "Validate Input", "type": "main", "index": 0}]]},
            "Validate Input": {"main": [[{"node": "Respond", "type": "main", "index": 0}]]}
        },
        "active": False,
        "settings": {}
    }

workflows = [
    # Move assign_staff to operations (was in appointments)
    ("n8n/operations/assign_staff.json", "Assign Staff", "assign_staff to appointment based on availability", "assign_staff"),
    # Learning missing
    ("n8n/learning/run_ab_experiment.json", "Run A/B Experiment", "Start A/B test between two message variants", "run_ab_experiment"),
    ("n8n/learning/declare_experiment_winner.json", "Declare Experiment Winner", "Analyze A/B results and declare winning variant", "declare_experiment_winner"),
    ("n8n/learning/store_success_script.json", "Store Success Script", "Save winning call script to success_scripts table", "store_success_script"),
    ("n8n/learning/store_failure_pattern.json", "Store Failure Pattern", "Save failure pattern to failure_patterns table", "store_failure_pattern"),
    ("n8n/learning/update_agent_confidence.json", "Update Agent Confidence", "Record agent decision confidence score", "update_agent_confidence"),
    # Monitoring missing
    ("n8n/monitoring/monitor_calendar_sync.json", "Monitor Calendar Sync", "Check Cal.com sync status and alert on failures", "monitor_calendar_sync"),
    # New from doc
    ("n8n/marketing/simulate_campaign.json", "Simulate Campaign", "Pre-launch simulation: best/worst/risk scenarios", "simulate_campaign"),
    ("n8n/operations/track_vendor.json", "Track Vendor", "Log vendor activity and update vendor records", "track_vendor"),
    ("n8n/operations/log_equipment_maintenance.json", "Log Equipment Maintenance", "Record maintenance event for equipment", "log_equipment_maintenance"),
    ("n8n/operations/track_room_resource.json", "Track Room Resource", "Update room/resource availability status", "track_room_resource"),
    ("n8n/operations/sync_franchise_location.json", "Sync Franchise Location", "Sync KPIs and data across franchise locations", "sync_franchise_location"),
    ("n8n/cross_cutting/fire_event_notification.json", "Fire Event Notification", "Publish business event to all department listeners", "fire_event_notification"),
]

created = 0
for (rel_path, name, description, webhook_path) in workflows:
    full_path = os.path.join(BASE, rel_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "w", encoding="utf-8") as f:
        json.dump(stub(name, description, webhook_path), f, indent=2)
    print(f"  {rel_path}")
    created += 1

print(f"\nCreated {created} n8n workflow stubs")
