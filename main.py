import os
from typing import Optional
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import xmlrpc.client
import traceback

# Load environment variables
load_dotenv()

# Odoo credentials
ODOO_URL = os.environ["ODOO_URL"]
ODOO_DB = os.environ["ODOO_DB"]
ODOO_USERNAME = os.environ["ODOO_USERNAME"]
ODOO_PASSWORD = os.environ["ODOO_PASSWORD"]

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
    unique_id: str
    name: str
    phone: Optional[str] = None
    mobile: Optional[str] = None
    email: Optional[str] = None
    contact_person: Optional[str] = None
    notes: Optional[str] = None
    exhibition: str
    sales_person: Optional[str] = None
    image: Optional[str] = None


@app.post("/sync-lead")
def sync_lead(lead: Lead):
    # Check Odoo connection
    if uid is None or models is None:
        raise HTTPException(status_code=500, detail="Odoo connection not available")
    
    try:
        print(f"\n{'='*50}")
        print(f"🔄 Processing lead: {lead.name}")
        print(f"📱 Phone: {lead.phone}")
        print(f"📱 Mobile: {lead.mobile}")
        print(f"📧 Email: {lead.email}")
        print(f"👤 Contact Person: {lead.contact_person}")
        print(f"🎪 Exhibition/Source: {lead.exhibition}")
        print(f"🆔 Unique ID: {lead.unique_id}")

        # =============================
        # FIND OR CREATE SOURCE (utm.source)
        # =============================
        source_id = False
        try:
            # Check if source exists in utm.source model
            source_ids = models.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD,
                'utm.source', 'search',
                [[['name', '=', lead.exhibition]]]
            )
            
            if source_ids:
                source_id = source_ids[0]
                print(f"✅ Found existing source: {lead.exhibition} (ID: {source_id})")
            else:
                # Create new source
                source_id = models.execute_kw(
                    ODOO_DB, uid, ODOO_PASSWORD,
                    'utm.source', 'create',
                    [{'name': lead.exhibition}]
                )
                print(f"✅ Created new source: {lead.exhibition} (ID: {source_id})")
        except Exception as e:
            print(f"⚠️ Could not create source in utm.source: {e}")

        # =============================
        # FIND OR CREATE SALES PERSON
        # =============================
        user_id = uid  # Default to API user
        if lead.sales_person:
            user_ids = models.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD,
                'res.users', 'search',
                [[['name', 'ilike', lead.sales_person]]]
            )
            if user_ids:
                user_id = user_ids[0]
                print(f"✅ Found sales person: {lead.sales_person} (ID: {user_id})")

        # =============================
        # CREATE CUSTOMER (res.partner)
        # =============================
        partner_id = None

        if lead.contact_person or lead.name:
            partner_name = lead.contact_person or lead.name
            
            # Search for existing partner
            partner_ids = models.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD,
                'res.partner', 'search',
                [[['name', '=', partner_name]]]
            )

            if partner_ids:
                partner_id = partner_ids[0]
                print(f"✅ Found existing partner: {partner_name} (ID: {partner_id})")
                
                # Update partner with contact details
                update_data = {}
                if lead.phone:
                    update_data['phone'] = lead.phone
                if lead.mobile:
                    update_data['mobile'] = lead.mobile
                if lead.email:
                    update_data['email'] = lead.email
                    
                if update_data:
                    models.execute_kw(
                        ODOO_DB, uid, ODOO_PASSWORD,
                        'res.partner', 'write',
                        [[partner_id], update_data]
                    )
                    print(f"✅ Updated partner with contact details")
            else:
                # Create new partner
                partner_data = {
                    'name': partner_name,
                }
                
                if lead.phone:
                    partner_data['phone'] = lead.phone
                if lead.mobile:
                    partner_data['mobile'] = lead.mobile
                if lead.email:
                    partner_data['email'] = lead.email
                
                partner_id = models.execute_kw(
                    ODOO_DB, uid, ODOO_PASSWORD,
                    'res.partner', 'create',
                    [partner_data]
                )
                print(f"✅ Created new partner: {partner_name} (ID: {partner_id})")

        # =============================
        # CREATE OPPORTUNITY
        # =============================
        print("📝 Creating opportunity in Odoo...")
        
        opportunity_data = {
            'name': lead.name,
            'type': 'opportunity',
            'user_id': user_id,
        }

        # Add SOURCE
        if source_id:
            opportunity_data['source_id'] = source_id
            print(f"✅ Setting source_id: {source_id}")

        # Add partner if exists
        if partner_id:
            opportunity_data['partner_id'] = partner_id

        # Add PHONE
        if lead.phone:
            opportunity_data['phone'] = lead.phone
            print(f"✅ Setting phone: {lead.phone}")
        
        # Add MOBILE - THIS IS FIXED!
        if lead.mobile:
            opportunity_data['mobile'] = lead.mobile
            print(f"✅ Setting mobile: {lead.mobile}")
            
        # Add EMAIL
        if lead.email:
            opportunity_data['email_from'] = lead.email
            print(f"✅ Setting email: {lead.email}")

        # Add notes
        if lead.notes:
            opportunity_data['description'] = lead.notes
            print(f"✅ Setting notes")

        print(f"📤 Final opportunity data: {opportunity_data}")

        opportunity_id = models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            'crm.lead', 'create',
            [opportunity_data]
        )
        
        print(f"✅ Opportunity created with ID: {opportunity_id}")

        # =============================
        # ADD NOTE WITH UNIQUE ID
        # =============================
        if lead.unique_id:
            message_body = f"""
            <b>Unique ID:</b> {lead.unique_id}<br/>
            <b>Source:</b> {lead.exhibition}<br/>
            <b>Contact Person:</b> {lead.contact_person or 'Not provided'}<br/>
            """
            
            models.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD,
                'crm.lead', 'message_post',
                [opportunity_id],
                {
                    'body': message_body,
                    'message_type': 'comment',
                    'subtype_xmlid': 'mail.mt_note'
                }
            )
            print(f"✅ Added note with unique ID")

        # =============================
        # ATTACH IMAGE
        # =============================
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
            "message": "Lead created successfully"
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
        "user": ODOO_USERNAME,
        "fields_available": {
            "phone": "✅ Available",
            "mobile": "✅ Available",
            "email_from": "✅ Available",
            "source_id": "✅ Available"
        }
    }


@app.get("/")
def root():
    return {
        "message": "Lead Sync API is running",
        "endpoints": {
            "POST /sync-lead": "Sync a lead with image",
            "GET /test": "Test Odoo connection"
        }
    }
