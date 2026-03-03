import os
from typing import Optional
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import xmlrpc.client
import traceback

# =====================================
# LOAD ENVIRONMENT VARIABLES
# =====================================
load_dotenv()

ODOO_URL = os.environ["ODOO_URL"]
ODOO_DB = os.environ["ODOO_DB"]
ODOO_USERNAME = os.environ["ODOO_USERNAME"]
ODOO_PASSWORD = os.environ["ODOO_PASSWORD"]

print("✅ Environment variables loaded")

# =====================================
# FASTAPI INITIALIZATION
# =====================================
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# =====================================
# CONNECT TO ODOO
# =====================================
try:
    common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
    uid = common.authenticate(ODOO_DB, ODOO_USERNAME, ODOO_PASSWORD, {})

    if not uid:
        raise Exception("Authentication failed")

    models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")

    print(f"✅ Connected to Odoo successfully (User ID: {uid})")

except Exception as e:
    print(f"❌ Failed to connect to Odoo: {e}")
    uid = None
    models = None


# =====================================
# REQUEST MODEL  ✅ FIXED HERE
# =====================================
class Lead(BaseModel):
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    contact_person: Optional[str] = None   # ✅ FIXED
    notes: Optional[str] = None
    exhibition: str
    sales_person: Optional[str] = "Preet Kaur"
    image: Optional[str] = None


# =====================================
# SYNC LEAD ENDPOINT
# =====================================
@app.post("/sync-lead")
def sync_lead(lead: Lead):

    if uid is None or models is None:
        raise HTTPException(status_code=500, detail="Odoo connection not available")

    try:
        print("\n" + "="*50)
        print(f"🔄 Processing lead: {lead.name}")
        print(f"Contact Person Received: {lead.contact_person}")  # Debug

        # =====================================
        # STEP 1: FIND OR CREATE SOURCE
        # =====================================
        source_name = lead.exhibition.strip()

        source_ids = models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            'utm.source', 'search',
            [[['name', '=', source_name]]]
        )

        if source_ids:
            source_id = source_ids[0]
        else:
            source_id = models.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD,
                'utm.source', 'create',
                [{'name': source_name}]
            )

        # =====================================
        # STEP 2: FIND SALESPERSON
        # =====================================
        user_ids = models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            'res.users', 'search',
            [[['name', 'ilike', lead.sales_person]]]
        )

        assigned_user_id = user_ids[0] if user_ids else uid

        # =====================================
        # STEP 3: PREPARE OPPORTUNITY DATA
        # =====================================
        opportunity_data = {
            'name': lead.name,
            'type': 'opportunity',
            'user_id': assigned_user_id,
            'source_id': source_id,
        }

        if lead.phone:
            opportunity_data['mobile'] = lead.phone

        if lead.email:
            opportunity_data['email_from'] = lead.email

        # ✅ CORRECT FIELD FOR ODOO
        if lead.contact_person:
            opportunity_data['contact_name'] = lead.contact_person

        if lead.notes:
            opportunity_data['description'] = lead.notes

        print(f"📤 Sending to Odoo: {opportunity_data}")

        # =====================================
        # CREATE OPPORTUNITY
        # =====================================
        opportunity_id = models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            'crm.lead', 'create',
            [opportunity_data]
        )

        print(f"✅ Opportunity created (ID: {opportunity_id})")

        # =====================================
        # ATTACH IMAGE
        # =====================================
        if lead.image:
            models.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD,
                'ir.attachment', 'create',
                [{
                    'name': f"{lead.name}_{opportunity_id}.jpg",
                    'type': 'binary',
                    'datas': lead.image,
                    'res_model': 'crm.lead',
                    'res_id': opportunity_id,
                    'mimetype': 'image/jpeg'
                }]
            )

        return {
            "status": "success",
            "id": opportunity_id
        }

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
