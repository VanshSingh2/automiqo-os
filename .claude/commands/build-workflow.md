Build a new n8n workflow JSON for this project.

Workflow name: $ARGUMENTS

Requirements:
1. Save to /n8n/{category}/{workflow_name}.json
2. Webhook trigger (POST), path = workflow_name
3. Node 2: validate business_id in Supabase businesses table
4. Execute workflow logic (Supabase/Twilio/etc)
5. Final node: update tasks table status=completed, completed_at=NOW()
6. All credentials via named references: Supabase_Main, Twilio_Production
7. Error branch: respond with {success: false, message: 'Business not found'}, 404

Input contract: {"business_id": "uuid", "task_id": "uuid", "parameters": {}}
Output contract: {"success": true, "data": {}, "message": "what happened"}

Reference: /n8n/revenue/recover_missed_call.json as gold standard.
