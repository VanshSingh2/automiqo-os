"""Generate lead scraping n8n workflow stubs."""
import json, os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def workflow(name, webhook, description, extra_nodes=None):
    nodes = [
        {"id": "1", "name": "Webhook", "type": "n8n-nodes-base.webhook",
         "parameters": {"path": webhook, "httpMethod": "POST"}, "position": [250, 300]},
        {"id": "2", "name": "Validate", "type": "n8n-nodes-base.code",
         "parameters": {"jsCode": f"// {description}\nconst d = $input.first().json;\nif (!d.business_id) throw new Error('Missing business_id');\nreturn [$input.first()];"},
         "position": [450, 300]},
    ]
    if extra_nodes:
        nodes.extend(extra_nodes)
    nodes.append({"id": str(len(nodes)+1), "name": "Respond", "type": "n8n-nodes-base.respondToWebhook",
                  "parameters": {"respondWith": "json", "responseBody": f"={{{{ {{ status: 'ok', workflow: '{webhook}' }} }}}}"},
                  "position": [250 + len(nodes)*200, 300]})
    conns = {}
    for i in range(len(nodes)-1):
        conns[nodes[i]["name"]] = {"main": [[{"node": nodes[i+1]["name"], "type": "main", "index": 0}]]}
    return {"name": name, "nodes": nodes, "connections": conns, "active": False, "settings": {}}

workflows = [
    ("n8n/marketing/scrape_google_maps_leads.json", "Scrape Google Maps Leads", "scrape_google_maps_leads",
     "Search Google Maps via Serper.dev for businesses matching query+location. Store results in Supabase leads table.",
     [{"id": "3", "name": "Serper Search", "type": "n8n-nodes-base.httpRequest",
       "parameters": {
           "url": "https://google.serper.dev/maps",
           "method": "POST",
           "authentication": "genericCredentialType",
           "genericAuthType": "httpHeaderAuth",
           "sendBody": True,
           "bodyParameters": {"parameters": [
               {"name": "q", "value": "={{ $json.parameters.query + ' ' + $json.parameters.location }}"},
               {"name": "num", "value": "={{ $json.parameters.count || 20 }}"}
           ]}
       }, "position": [650, 300]},
      {"id": "4", "name": "Store in Supabase", "type": "n8n-nodes-base.httpRequest",
       "parameters": {
           "url": "={{ $env.SUPABASE_URL }}/rest/v1/leads",
           "method": "POST",
           "sendHeaders": True,
           "headerParameters": {"parameters": [
               {"name": "apikey", "value": "={{ $env.SUPABASE_SERVICE_KEY }}"},
               {"name": "Authorization", "value": "Bearer {{ $env.SUPABASE_SERVICE_KEY }}"},
               {"name": "Prefer", "value": "resolution=ignore-duplicates"}
           ]},
           "sendBody": True,
           "bodyParameters": {"parameters": [
               {"name": "business_id", "value": "={{ $('Webhook').first().json.business_id }}"},
               {"name": "company_name", "value": "={{ $json.title }}"},
               {"name": "address", "value": "={{ $json.address }}"},
               {"name": "phone", "value": "={{ $json.phoneNumber }}"},
               {"name": "website", "value": "={{ $json.website }}"},
               {"name": "google_rating", "value": "={{ $json.rating }}"},
               {"name": "review_count", "value": "={{ $json.reviews }}"},
               {"name": "source", "value": "google_maps"},
               {"name": "status", "value": "new"}
           ]}
       }, "position": [850, 300]}
     ]),
    ("n8n/marketing/scrape_website_email.json", "Scrape Website Email", "scrape_website_email",
     "Visit lead website homepage and contact page, extract email addresses.", None),
    ("n8n/marketing/enrich_lead_profile.json", "Enrich Lead Profile", "enrich_lead_profile",
     "Enrich a lead with additional data: social profiles, employee count, tech stack.", None),
    ("n8n/marketing/score_lead.json", "Score Lead", "score_lead",
     "Score a lead 0-100 based on: has website, review count, has booking system, industry fit.", [
         {"id": "3", "name": "Calculate Score", "type": "n8n-nodes-base.code",
          "parameters": {"jsCode": """
const lead = $input.first().json;
let score = 0;
if (lead.has_website) score += 20;
if (lead.review_count > 10) score += 15;
if (lead.review_count > 50) score += 10;
if (!lead.has_booking_system) score += 25; // opportunity!
if (lead.google_rating >= 4.0) score += 15;
if (lead.phone) score += 10;
if (lead.email) score += 5;
return [{ json: { ...lead, score, scored: true } }];
"""},
          "position": [650, 300]}
     ]),
    ("n8n/marketing/send_cold_outreach.json", "Send Cold Outreach", "send_cold_outreach",
     "Send personalized cold outreach SMS or email to a scored lead.", None),
]

for (path, name, webhook, desc, extra) in workflows:
    full = os.path.join(BASE, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        json.dump(workflow(name, webhook, desc, extra), f, indent=2)
    print(f"  {path}")

print(f"Created {len(workflows)} lead scraping workflows")
