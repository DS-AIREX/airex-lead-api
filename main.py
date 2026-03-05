import os
from typing import Optional
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import xmlrpc.client
import traceback
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

# ============ Helper function to get Odoo connection ============
def get_odoo_connection():
    """Create a new Odoo connection for each request"""
    try:
        common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
        uid = common.authenticate(ODOO_DB, ODOO_USERNAME, ODOO_PASSWORD, {})
        
        if not uid:
            raise Exception("Authentication failed")
        
        models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")
        return uid, models
    except Exception as e:
        logger.error(f"❌ Failed to connect to Odoo: {e}")
        return None, None

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
    # Create a NEW connection for each request
    uid, models = get_odoo_connection()
    
    if uid is None or models is None:
        raise HTTPException(status_code=500, detail="Odoo connection not available")
    
    try:
        logger.info(f"\n{'='*50}")
        logger.info(f"🔄 Processing lead: {lead.name}")
        logger.info(f"📱 Phone received: '{lead.phone}'")
        logger.info(f"🎪 Exhibition/Source received: '{lead.exhibition}'")
        logger.info(f"📧 Email: {lead.email}")
        logger.info(f"🆔 Unique ID: {lead.unique_id}")

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
                logger.info(f"✅ Found existing source: {lead.exhibition} (ID: {source_id})")
            else:
                # Create new source
                source_id = models.execute_kw(
                    ODOO_DB, uid, ODOO_PASSWORD,
                    'utm.source', 'create',
                    [{'name': lead.exhibition}]
                )
                logger.info(f"✅ Created new source: {lead.exhibition} (ID: {source_id})")
        except Exception as e:
            logger.warning(f"⚠️ Could not create source: {e}")

        # =============================
        # CREATE CUSTOMER (res.partner)
        # =============================
        partner_id = None
        partner_name = lead.contact_person or lead.name

        if partner_name:
            try:
                # Search for existing partner
                partner_ids = models.execute_kw(
                    ODOO_DB, uid, ODOO_PASSWORD,
                    'res.partner', 'search',
                    [[['name', '=', partner_name]]]
                )

                if partner_ids:
                    partner_id = partner_ids[0]
                    logger.info(f"✅ Found existing partner: {partner_name} (ID: {partner_id})")
                    
                    # Update partner with phone if available
                    if lead.phone:
                        clean_phone = str(lead.phone).replace('+', '').strip()
                        models.execute_kw(
                            ODOO_DB, uid, ODOO_PASSWORD,
                            'res.partner', 'write',
                            [[partner_id], {'phone': clean_phone}]
                        )
                else:
                    # Create new partner
                    partner_data = {'name': partner_name}
                    
                    if lead.phone:
                        clean_phone = str(lead.phone).replace('+', '').strip()
                        partner_data['phone'] = clean_phone
                    
                    if lead.email:
                        partner_data['email'] = lead.email
                    
                    partner_id = models.execute_kw(
                        ODOO_DB, uid, ODOO_PASSWORD,
                        'res.partner', 'create',
                        [partner_data]
                    )
                    logger.info(f"✅ Created new partner: {partner_name} (ID: {partner_id})")
            except Exception as e:
                logger.warning(f"⚠️ Partner error: {e}")

        # =============================
        # CREATE OPPORTUNITY
        # =============================
        logger.info("📝 Creating opportunity in Odoo...")
        
        # Clean phone number for CRM lead
        clean_phone = ""
        if lead.phone:
            clean_phone = str(lead.phone).replace('+', '').replace(' ', '').strip()
        
        # Prepare opportunity data
        opportunity_data = {
            'name': lead.name or "Lead from Exhibition",
            'type': 'opportunity',
        }

        # Add SOURCE
        if source_id:
            opportunity_data['source_id'] = source_id
        
        # Add partner
        if partner_id:
            opportunity_data['partner_id'] = partner_id

        # Add PHONE
        if clean_phone:
            opportunity_data['phone'] = clean_phone
            
        # Add EMAIL
        if lead.email:
            opportunity_data['email_from'] = lead.email

        # Add notes
        if lead.notes:
            opportunity_data['description'] = lead.notes

        logger.info(f"📤 Creating opportunity with data: {opportunity_data}")

        # CREATE THE OPPORTUNITY
        opportunity_id = models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            'crm.lead', 'create',
            [opportunity_data]
        )
        
        logger.info(f"✅ Opportunity created with ID: {opportunity_id}")

        # =============================
        # ATTACH IMAGE
        # =============================
        if lead.image:
            try:
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
                logger.info(f"✅ Image attached. Attachment ID: {attachment_id}")
            except Exception as e:
                logger.warning(f"⚠️ Could not attach image: {e}")

        logger.info(f"\n✅ Sync completed for opportunity {opportunity_id}")
        
        return {
            "status": "success", 
            "id": opportunity_id,
            "message": "Lead created successfully"
        }

    except Exception as e:
        logger.error(f"\n❌ Error: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/test")
def test_connection():
    # Create a new connection for test
    uid, models = get_odoo_connection()
    
    if uid is None:
        return {"status": "error", "message": "Odoo connection failed"}
    
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
            "POST /sync-lead": "Sync a lead with image",
            "GET /test": "Test Odoo connection"
        }
    }
