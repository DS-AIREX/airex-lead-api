import os
from typing import Optional
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import xmlrpc.client
import base64
import traceback

# Load environment variables
load_dotenv()

# Odoo credentials
ODOO_URL = os.environ["ODOO_URL"]
ODOO_DB = os.environ["ODOO_DB"]
ODOO_USERNAME = os.environ["ODOO_USERNAME"]
ODOO_PASSWORD = os.environ["ODOO_PASSWORD"]

print(f"✅ Environment variables loaded:")
print(f"   URL: {ODOO_URL}")
print(f"   DB: {ODOO_DB}")
print(f"   Username: {ODOO_USERNAME}")
print(f"   Password: {'*' * len(ODOO_PASSWORD)}")

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Connect to Odoo
try:
    common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
    uid = common.authenticate(ODOO_DB, ODOO_USERNAME, ODOO_PASSWORD, {})
    
    if not uid:
        raise Exception("Authentication failed")
    
    models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")
    print(f"✅ Connected to Odoo successfully! User ID: {uid}")
    
except Exception as e:
    print(f"❌ Failed to connect to Odoo: {e}")
    uid = None
    models = None

class Lead(BaseModel):
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    company: Optional[str] = None
    notes: Optional[str] = None
    exhibition: str
    sales_person: Optional[str] = "Preet Kaur"
    image: Optional[str] = None


@app.post("/sync-lead")
def sync_lead(lead: Lead):
    # Check Odoo connection
    if uid is None or models is None:
        raise HTTPException(status_code=500, detail="Odoo connection not available")
    
    try:
        print(f"\n{'='*50}")
        print(f"🔄 Processing lead: {lead.name}")
        print(f"🎪 Exhibition: {lead.exhibition}")
        print(f"👤 Sales Person: {lead.sales_person}")
        
        # STEP 1: Find the salesperson in Odoo
        print("🔍 Searching for sales person...")
        user_ids = models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            'res.users', 'search',
            [[['name', 'ilike', lead.sales_person]]]
        )
        
        assigned_user_id = uid
        if user_ids:
            assigned_user_id = user_ids[0]
            print(f"✅ Found sales person: {lead.sales_person} (ID: {assigned_user_id})")
        else:
            print(f"⚠️ Sales person '{lead.sales_person}' not found, using default user (ID: {uid})")
        
        # STEP 2: Create the opportunity
        print("📝 Creating opportunity in Odoo...")
        
        opportunity_data = {
            'name': lead.name,
            'type': 'opportunity',
            'user_id': assigned_user_id,
        }
        
        # Add source/exhibition to description
        if lead.notes:
            opportunity_data['description'] = f"Source: {lead.exhibition}\n\n{lead.notes}"
        else:
            opportunity_data['description'] = f"Source: {lead.exhibition}"
        
        # Add optional fields
        if lead.phone:
            opportunity_data['phone'] = lead.phone
        if lead.email:
            opportunity_data['email_from'] = lead.email
        if lead.company:
            opportunity_data['company_name'] = lead.company
        
        print(f"📤 Sending data: {opportunity_data}")
        
        opportunity_id = models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            'crm.lead', 'create',
            [opportunity_data]
        )
        
        print(f"✅ Opportunity created with ID: {opportunity_id}")

        # STEP 3: Attach image if exists
        if lead.image:
            print("🖼️ Attaching image to opportunity...")
            
            attachment_id = models.execute_kw(
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
            
            print(f"✅ Image attached successfully. Attachment ID: {attachment_id}")

        print(f"\n✅ Sync completed successfully for opportunity {opportunity_id}")
        print('='*50)
        
        return {
            "status": "success", 
            "id": opportunity_id,
            "assigned_to": lead.sales_person,
            "source": lead.exhibition,
            "message": f"Opportunity created and assigned to {lead.sales_person}"
        }
    
    except xmlrpc.client.Fault as fault:
        print(f"\n❌ Odoo XML-RPC Fault:")
        print(f"Fault code: {fault.faultCode}")
        print(f"Fault string: {fault.faultString}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Odoo Error: {fault.faultString}")
    
    except Exception as e:
        print(f"\n❌ Unexpected error:")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/test")
def test_connection():
    """Test endpoint to verify Odoo connection"""
    if uid is None:
        return {
            "status": "error",
            "message": "Odoo connection failed",
            "env_vars_loaded": {
                "ODOO_URL": ODOO_URL if 'ODOO_URL' in os.environ else "MISSING",
                "ODOO_DB": ODOO_DB if 'ODOO_DB' in os.environ else "MISSING",
                "ODOO_USERNAME": ODOO_USERNAME if 'ODOO_USERNAME' in os.environ else "MISSING",
                "ODOO_PASSWORD": "Loaded" if 'ODOO_PASSWORD' in os.environ else "MISSING"
            }
        }
    
    return {
        "status": "connected",
        "uid": uid,
        "url": ODOO_URL,
        "db": ODOO_DB,
        "user": ODOO_USERNAME
    }


@app.get("/")
def root():
    return {
        "message": "Lead Sync API is running",
        "endpoints": {
            "POST /sync-lead": "Sync a lead with image and sales person",
            "GET /test": "Test Odoo connection"
        }
    }
