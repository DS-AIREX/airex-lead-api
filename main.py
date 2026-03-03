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
print(f"URL: {ODOO_URL}")
print(f"DB: {ODOO_DB}")
print(f"Username: {ODOO_USERNAME}")

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
    company: Optional[str] = None
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
        print(f"🎪 Exhibition: {lead.exhibition}")
        print(f"👤 Sales Person: {lead.sales_person}")

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
            print(f"✅ Source found (ID: {source_id})")
        else:
            source_id = models.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD,
                'utm.source', 'create',
                [{'name': source_name}]
            )
            print(f"✅ Source created (ID: {source_id})")

        # =====================================
        # STEP 2: FIND SALESPERSON
        # =====================================
        user_ids = models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            'res.users', 'search',
            [[['name', 'ilike', lead.sales_person]]]
        )

        assigned_user_id = uid

        if user_ids:
            assigned_user_id = user_ids[0]
            print(f"✅ Salesperson found (ID: {assigned_user_id})")
        else:
            print(f"⚠️ Salesperson not found, using default user")

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
            opportunity_data['mobile'] = lead.phone  # Correct field

        if lead.email:
            opportunity_data['email_from'] = lead.email

        if lead.company:
            opportunity_data['contact_name'] = lead.company

        if lead.notes:
            opportunity_data['description'] = lead.notes

        print(f"📤 Sending data to Odoo: {opportunity_data}")

        # =====================================
        # STEP 4: CREATE OPPORTUNITY
        # =====================================
        opportunity_id = models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            'crm.lead', 'create',
            [opportunity_data]
        )

        print(f"✅ Opportunity created (ID: {opportunity_id})")

        # =====================================
        # STEP 5: ATTACH IMAGE
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

        print("✅ Sync completed successfully")
        print("="*50)

        return {
            "status": "success",
            "id": opportunity_id,
            "assigned_to": lead.sales_person,
            "source": lead.exhibition,
            "message": "Opportunity created successfully"
        }

    except xmlrpc.client.Fault as fault:
        print("\n❌ Odoo XML-RPC Fault:")
        print(fault.faultString)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Odoo Error: {fault.faultString}")

    except Exception as e:
        print("\n❌ Unexpected error:")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# =====================================
# TEST ENDPOINT
# =====================================
@app.get("/test")
def test_connection():

    if uid is None:
        return {
            "status": "error",
            "message": "Odoo connection failed"
        }

    return {
        "status": "connected",
        "uid": uid,
        "url": ODOO_URL,
        "db": ODOO_DB,
        "user": ODOO_USERNAME
    }


# =====================================
# ROOT ENDPOINT
# =====================================
@app.get("/")
def root():
    return {
        "message": "Lead Sync API is running",
        "endpoints": {
            "POST /sync-lead": "Sync a lead",
            "GET /test": "Test Odoo connection"
        }
    }
