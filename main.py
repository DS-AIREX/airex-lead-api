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
# REQUEST MODEL
# =====================================
class Lead(BaseModel):
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    contact_person: Optional[str] = None
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
        print(f"🔄 Processing Lead: {lead.name}")
        print(f"👤 Contact Person: {lead.contact_person}")

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
        # STEP 3: CREATE OR FIND CUSTOMER
        # =====================================
        partner_id = None

        if lead.contact_person:
            partner_ids = models.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD,
                'res.partner', 'search',
                [[['name', '=', lead.contact_person]]]
            )

            if partner_ids:
                partner_id = partner_ids[0]
                print(f"✅ Existing customer found (ID: {partner_id})")
            else:
                partner_id = models.execute_kw(
                    ODOO_DB, uid, ODOO_PASSWORD,
                    'res.partner', 'create',
                    [{
                        'name': lead.contact_person,
                        'phone': lead.phone or '',
                        'email': lead.email or ''
                    }]
                )
                print(f"✅ New customer created (ID: {partner_id})")

        # =====================================
        # STEP 4: PREPARE OPPORTUNITY DATA
        # =====================================
        opportunity_data = {
            'name': lead.name,
            'type': 'opportunity',
            'user_id': assigned_user_id,
            'source_id': source_id,
        }

        if partner_id:
            opportunity_data['partner_id'] = partner_id

        if lead.phone:
            opportunity_data['mobile'] = lead.phone

        if lead.email:
            opportunity_data['email_from'] = lead.email

        if lead.notes:
            opportunity_data['description'] = lead.notes

        print(f"📤 Sending to Odoo: {opportunity_data}")

        # =====================================
        # STEP 5: CREATE OPPORTUNITY
        # =====================================
        opportunity_id = models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            'crm.lead', 'create',
            [opportunity_data]
        )

        print(f"✅ Opportunity created (ID: {opportunity_id})")

        # =====================================
        # STEP 6: ATTACH IMAGE
        # =====================================
        if lead.image:
            print("🖼️ Attaching image...")

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

            print("✅ Image attached")

        print("✅ Sync Completed Successfully")
        print("="*50)

        return {
            "status": "success",
            "id": opportunity_id
        }

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# =====================================
# TEST ENDPOINT
# =====================================
@app.get("/test")
def test_connection():

    if uid is None:
        return {"status": "error"}

    return {
        "status": "connected",
        "uid": uid
    }


# =====================================
# ROOT
# =====================================
@app.get("/")
def root():
    return {"message": "Lead Sync API Running"}
