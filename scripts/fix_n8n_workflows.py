"""
fix_n8n_workflows.py
Applies 5 targeted fixes to n8n workflow JSON files under n8n/.
Run from project root: python scripts/fix_n8n_workflows.py
"""

import json
import os
import copy

# ── helpers ──────────────────────────────────────────────────────────────────

def load(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)

def save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def rel(path):
    """Return path relative to cwd for readable output."""
    try:
        return os.path.relpath(path)
    except ValueError:
        return path

# ── change log ────────────────────────────────────────────────────────────────

changes = []  # list of (file, description)

def log(path, msg):
    changes.append((rel(path), msg))
    print(f"  [CHANGED] {msg}")

# ── FIX 1: Wrong table names ──────────────────────────────────────────────────

TABLE_FIXES = {
    # finance
    "n8n/finance/create_purchase_order.json":    ("invoices",        "purchase_orders"),
    "n8n/finance/generate_invoice.json":         ("invoices",        "purchase_orders"),
    "n8n/finance/process_deposit_refund.json":   ("invoices",        "purchase_orders"),
    # hr
    "n8n/hr/alert_certification_expiry.json":    ("hr_tasks",        "internal_tasks"),
    "n8n/hr/schedule_interview.json":            ("hr_tasks",        "internal_tasks"),
    "n8n/hr/screen_resume.json":                 ("hr_tasks",        "internal_tasks"),
    "n8n/hr/send_onboarding_checklist.json":     ("hr_tasks",        "internal_tasks"),
    # platform
    "n8n/platform/rollback_workflow_version.json": ("platform_tasks","tasks"),
    "n8n/platform/run_daily_backup.json":          ("platform_tasks","tasks"),
    "n8n/platform/track_ai_costs.json":            ("platform_tasks","ai_costs"),
}

def fix_table_names(path, data):
    """Fix wrong tableId values in nodes."""
    rel_path = path.replace("\\", "/")
    # normalise to forward-slash key to match TABLE_FIXES
    for key in TABLE_FIXES:
        if rel_path.endswith(key.lstrip("/")):
            wrong, correct = TABLE_FIXES[key]
            for node in data.get("nodes", []):
                params = node.get("parameters", {})
                if params.get("tableId") == wrong:
                    params["tableId"] = correct
                    log(path, f"Node '{node.get('name')}': tableId {wrong!r} -> {correct!r}")
                # also fix table name embedded in a url string
                url = params.get("url", "")
                if wrong in url:
                    params["url"] = url.replace(wrong, correct)
                    log(path, f"Node '{node.get('name')}': url table {wrong!r} -> {correct!r}")
            break

# ── FIX 2: Add business_id filter to Mark Complete / Write Result nodes ───────

BUSINESS_ID_FILTER = {
    "keyName":  "business_id",
    "keyValue": "={{ $('Extract Params').item.json.business_id }}",
    "condition": "eq",
}

def _has_business_id_filter(conditions):
    return any(c.get("keyName") == "business_id" for c in conditions)

def fix_mark_complete(path, data):
    """Add business_id filter to Mark Complete / Write Result to Tasks nodes."""
    for node in data.get("nodes", []):
        name = node.get("name", "")
        if name not in ("Mark Complete", "Write Result to Tasks"):
            continue
        params = node.get("parameters", {})
        if params.get("tableId") != "tasks":
            continue
        if params.get("operation") != "update":
            continue
        filters = params.setdefault("filters", {})
        conditions = filters.setdefault("conditions", [])
        if _has_business_id_filter(conditions):
            continue
        conditions.append(copy.deepcopy(BUSINESS_ID_FILTER))
        log(path, f"Node '{name}': added business_id filter condition")

# ── FIX 3: Replace generic SMS bodies ────────────────────────────────────────

SMS_BODIES = {
    "recover_failed_payment":   "Hi {{ $('Get Customer').item.json.name || 'there' }}, your payment didn't go through. Please update your payment info to keep your booking. Reply HELP for assistance.",
    "send_payment_link":        "Hi {{ $('Get Customer').item.json.name || 'there' }}, you have an outstanding balance. Pay securely here: {{ $json.payment_url || 'contact us' }}. Reply STOP to opt out.",
    "send_upsell_offer":        "Hi {{ $('Get Customer').item.json.name || 'there' }}, thank you for your visit! We have a special offer: {{ $json.offer_details || 'exclusive deal' }}. Book: {{ $json.booking_url || '' }}. Reply STOP to opt out.",
    "handle_complaint":         "Hi {{ $('Get Customer').item.json.name || 'there' }}, we're sorry about your experience. Our team will follow up within 24 hours. Thank you for your patience.",
    "send_loyalty_reward":      "Hi {{ $('Get Customer').item.json.name || 'there' }}, congrats on your loyalty! Here's your reward: {{ $json.reward_details || 'special offer' }}. Book: {{ $json.booking_url || '' }}",
    "send_rebooking_reminder":  "Hi {{ $('Get Customer').item.json.name || 'there' }}, we miss you! Time for your next visit? Book here: {{ $json.booking_url || '' }}. Reply STOP to opt out.",
    "send_satisfaction_survey": "Hi {{ $('Get Customer').item.json.name || 'there' }}, how was your recent visit? Share feedback: {{ $json.survey_url || '' }}. Thank you!",
}

GENERIC_MARKERS = ("Message from Automiqo OS", "Hello from Automiqo OS", "Message from Automiqo")

def fix_sms_bodies(path, data):
    """Replace generic SMS/message bodies with personalised ones."""
    workflow_name = data.get("name", "")
    if workflow_name not in SMS_BODIES:
        return
    new_body = SMS_BODIES[workflow_name]
    for node in data.get("nodes", []):
        params = node.get("parameters", {})
        for field in ("body", "text", "message"):
            val = params.get(field, "")
            if isinstance(val, str) and any(m in val for m in GENERIC_MARKERS):
                params[field] = new_body
                log(path, f"Node '{node.get('name')}': replaced generic {field!r} with personalised SMS")

# ── FIX 4: cancel_appointment → trigger fill_waitlist ────────────────────────

WAITLIST_NODE = {
    "id": "trigger-waitlist-001",
    "name": "Trigger Fill Waitlist",
    "type": "n8n-nodes-base.httpRequest",
    "typeVersion": 4,
    "position": [1340, 220],
    "parameters": {
        "method": "POST",
        "url": "={{ $env.N8N_WEBHOOK_BASE_URL }}/fill_waitlist_slot",
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify({ business_id: $('Webhook').first().json.business_id, task_id: $('Webhook').first().json.task_id, parameters: { appointment_id: $('Webhook').first().json.parameters.appointment_id } }) }}"
    }
}

def fix_cancel_appointment(path, data):
    """Insert Trigger Fill Waitlist node between Mark Complete and Respond."""
    if data.get("name") != "cancel_appointment":
        return

    nodes = data.get("nodes", [])
    connections = data.get("connections", {})

    # check not already added
    if any(n.get("id") == "trigger-waitlist-001" for n in nodes):
        return

    # find the "Respond" node name (respondToWebhook after Mark Complete)
    # In cancel_appointment the respond node is named "Respond OK"
    # We need to find what Mark Complete connects to
    mc_conns = connections.get("Mark Complete", {}).get("main", [[]])
    if not mc_conns or not mc_conns[0]:
        print(f"  [SKIP] cancel_appointment: could not find Mark Complete connections")
        return
    respond_node_name = mc_conns[0][0]["node"]

    # Move Mark Complete's outgoing connection to the new waitlist node
    connections["Mark Complete"]["main"] = [[{"node": "Trigger Fill Waitlist", "type": "main", "index": 0}]]
    # New node connects to old Respond target
    connections["Trigger Fill Waitlist"] = {
        "main": [[{"node": respond_node_name, "type": "main", "index": 0}]]
    }

    # Shift Respond node rightward to avoid overlap (update position if present)
    for node in nodes:
        if node.get("name") == respond_node_name:
            node["position"] = [1560, 220]

    # Move Mark Complete slightly up so waitlist node can sit at same x
    for node in nodes:
        if node.get("name") == "Mark Complete":
            node["position"] = [1120, 220]

    nodes.append(copy.deepcopy(WAITLIST_NODE))
    log(path, "Added 'Trigger Fill Waitlist' node and wired it between 'Mark Complete' and 'Respond OK'")

# ── FIX 5: morning_cron_trigger → loop all businesses ────────────────────────

MORNING_BRIEFING_NODE = {
    "id": "briefing-all-biz",
    "name": "Trigger Morning Briefing All Businesses",
    "type": "n8n-nodes-base.httpRequest",
    "typeVersion": 4,
    "position": [460, 300],
    "parameters": {
        "method": "POST",
        "url": "={{ $env.BACKEND_URL }}/cron/morning-briefing",
        "sendHeaders": True,
        "headerParameters": {
            "parameters": [
                {
                    "name": "x-cron-secret",
                    "value": "={{ $env.CRON_SECRET }}"
                }
            ]
        }
    }
}

def fix_morning_cron(path, data):
    """Replace the hardcoded single-business Monitor node with a multi-business briefing call."""
    if data.get("name") != "morning_cron_trigger":
        return

    nodes = data.get("nodes", [])
    connections = data.get("connections", {})

    # Check if already fixed
    if any(n.get("id") == "briefing-all-biz" for n in nodes):
        return

    # Identify the node that fires the single-business briefing (the Monitor node)
    monitor_node = None
    for node in nodes:
        if node.get("name") == "Monitor" and node.get("type") == "n8n-nodes-base.httpRequest":
            monitor_node = node
            break

    if monitor_node is None:
        print(f"  [SKIP] morning_cron_trigger: Monitor httpRequest node not found")
        return

    old_name = monitor_node["name"]
    old_id   = monitor_node["id"]

    # Replace in-place: update the node fields to new spec
    monitor_node.update(copy.deepcopy(MORNING_BRIEFING_NODE))

    # Fix connections: rename key from old name to new name
    new_name = MORNING_BRIEFING_NODE["name"]
    if old_name != new_name:
        if old_name in connections:
            connections[new_name] = connections.pop(old_name)
        # Fix any incoming connections pointing at old_name
        for src, conn_data in connections.items():
            for output_list in conn_data.get("main", []):
                for conn in output_list:
                    if conn.get("node") == old_name:
                        conn["node"] = new_name

    log(path, f"Replaced '{old_name}' with multi-business morning briefing node (POST to $env.BACKEND_URL/cron/morning-briefing)")

# ── main ──────────────────────────────────────────────────────────────────────

def all_json_files(root):
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            if fn.endswith(".json"):
                yield os.path.join(dirpath, fn)

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    n8n_root = os.path.join(project_root, "n8n")

    if not os.path.isdir(n8n_root):
        print(f"ERROR: n8n directory not found at {n8n_root}")
        return

    print(f"Scanning {n8n_root} ...\n")

    for path in sorted(all_json_files(n8n_root)):
        try:
            data = load(path)
        except Exception as e:
            print(f"  [SKIP] {rel(path)}: parse error – {e}")
            continue

        original = json.dumps(data, ensure_ascii=False)

        print(f"Processing {rel(path)}")
        fix_table_names(path, data)
        fix_mark_complete(path, data)
        fix_sms_bodies(path, data)
        fix_cancel_appointment(path, data)
        fix_morning_cron(path, data)

        if json.dumps(data, ensure_ascii=False) != original:
            save(path, data)

    print("\n" + "="*60)
    print(f"SUMMARY: {len(changes)} change(s) made across {len(set(f for f,_ in changes))} file(s)")
    print("="*60)
    if changes:
        current_file = None
        for f, msg in changes:
            if f != current_file:
                print(f"\n{f}")
                current_file = f
            print(f"  - {msg}")
    else:
        print("No changes needed (everything already correct).")

if __name__ == "__main__":
    main()
