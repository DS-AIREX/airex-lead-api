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

ODOO_URL = os.environ["ODOO_URL"]
ODOO_DB = os.environ["ODOO_DB"]
ODOO_USERNAME = os.environ["ODOO_USERNAME"]
ODOO_PASSWORD = os.environ["ODOO_PASSWORD"]

app = FastAPI()

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
    logger.info(f"✅ Connected to Odoo successfully! User ID: {uid}")
    
except Exception as e:
    logger.error(f"❌ Failed to connect to Odoo: {e}")
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
    if uid is None or models is None:
        raise HTTPException(status_code=500, detail="Odoo connection not available")
    
    # Log the incoming lead data
    logger.info(f"\n{'='*50}")
    logger.info(f"🔄 Processing lead: {lead.name}")
    logger.info(f"📱 Phone: {lead.phone}")
    logger.info(f"📧 Email: {lead.email}")
    logger.info(f"🎪 Exhibition: {lead.exhibition}")
    logger.info(f"🆔 Unique ID: {lead.unique_id}")
    
    # Try with minimal data first, then add fields one by one
    try:
        # Start with absolute minimum required fields
        opportunity_data = {
            'name': str(lead.name)[:100] if lead.name else 'Lead from Exhibition',
            'type': 'opportunity',
        }
        
        logger.info(f"📝 Step 1: Creating with minimal data: {opportunity_data}")
        
        # Create the lead with minimal data
        opportunity_id = models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            'crm.lead', 'create',
            [opportunity_data]
        )
        
        logger.info(f"✅ Step 1 success: Created lead with ID: {opportunity_id}")
        
        # Step 2: Add phone if available
        if lead.phone:
            try:
                clean_phone = str(lead.phone).replace('+', '').replace(' ', '').strip()
                models.execute_kw(
                    ODOO_DB, uid, ODOO_PASSWORD,
                    'crm.lead', 'write',
                    [[opportunity_id], {'phone': clean_phone}]
                )
                logger.info(f"✅ Added phone: {clean_phone}")
            except Exception as e:
                logger.warning(f"⚠️ Could not add phone: {e}")
        
        # Step 3: Add email if available
        if lead.email:
            try:
                models.execute_kw(
                    ODOO_DB, uid, ODOO_PASSWORD,
                    'crm.lead', 'write',
                    [[opportunity_id], {'email_from': lead.email}]
                )
                logger.info(f"✅ Added email: {lead.email}")
            except Exception as e:
                logger.warning(f"⚠️ Could not add email: {e}")
        
        # Step 4: Add notes/source
        if lead.exhibition or lead.notes:
            try:
                description = ""
                if lead.exhibition:
                    description += f"Source: {lead.exhibition}\n"
                if lead.notes:
                    description += f"{lead.notes}\n"
                if lead.unique_id:
                    description += f"Unique ID: {lead.unique_id}"
                
                if description:
                    models.execute_kw(
                        ODOO_DB, uid, ODOO_PASSWORD,
                        'crm.lead', 'write',
                        [[opportunity_id], {'description': description}]
                    )
                    logger.info(f"✅ Added description")
            except Exception as e:
                logger.warning(f"⚠️ Could not add description: {e}")
        
        # Step 5: Add image if available
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
                logger.info(f"✅ Image attached: {attachment_id}")
            except Exception as e:
                logger.warning(f"⚠️ Could not attach image: {e}")
        
        return {
            "status": "success", 
            "id": opportunity_id,
            "message": "Lead created successfully"
        }
        
    except xmlrpc.client.Fault as fault:
        logger.error(f"❌ Odoo Fault: {fault.faultString}")
        logger.error(f"Fault code: {fault.faultCode}")
        
        # If it's a duplicate error, return success anyway
        if "unique" in fault.faultString.lower() or "duplicate" in fault.faultString.lower():
            logger.warning("⚠️ Duplicate lead detected")
            return {
                "status": "already_exists",
                "message": "Lead may already exist",
                "id": None
            }
        
        # For other errors, return the fault string
        raise HTTPException(status_code=500, detail=fault.faultString)
    
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/test")
def test_connection():
    if uid is None:
        return {"status": "error", "message": "Odoo connection failed"}
    
    return {
        "status": "connected",
        "uid": uid,
        "url": ODOO_URL,
        "db": ODOO_DB,
        "user": ODOO_USERNAME
    }
