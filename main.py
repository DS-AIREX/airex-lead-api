import os
import re
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

# Helper function to sanitize text for Odoo
def sanitize_text(text, max_length=200):
    """Remove special characters that might break XML-RPC"""
    if not text:
        return ""
    # Remove control characters
    text = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', str(text))
    # Limit length
    if len(text) > max_length:
        text = text[:max_length] + "..."
    return text

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
    
    try:
        logger.info(f"\n{'='*50}")
        logger.info(f"🔄 Processing lead: {lead.name}")
        logger.info(f"📱 Phone: {lead.phone}")
        logger.info(f"📧 Email: {lead.email}")
        
        # =============================
        # SANITIZE ALL DATA
        # =============================
        safe_name = sanitize_text(lead.name, 100)
        safe_phone = sanitize_text(lead.phone, 20).replace('+', '').replace(' ', '')
        safe_email = sanitize_text(lead.email, 100)
        safe_notes = sanitize_text(lead.notes, 500)
        
        # Create a clean description without special characters
        description_parts = []
        if lead.exhibition:
            description_parts.append(f"Source: {sanitize_text(lead.exhibition, 50)}")
        if lead.notes:
            description_parts.append(sanitize_text(lead.notes, 200))
        if lead.unique_id:
            description_parts.append(f"ID: {sanitize_text(lead.unique_id, 30)}")
        
        safe_description = "\n".join(description_parts) if description_parts else ""
        
        logger.info(f"📝 Sanitized data ready")
        
        # =============================
        # CREATE OPPORTUNITY WITH SAFE DATA
        # =============================
        
        # Start with minimal data
        opportunity_data = {
            'name': safe_name or "Lead from Exhibition",
            'type': 'opportunity',
        }
        
        # Add optional fields if they exist and are valid
        if safe_phone:
            opportunity_data['phone'] = safe_phone
        if safe_email:
            opportunity_data['email_from'] = safe_email
        if safe_description:
            opportunity_data['description'] = safe_description
        
        logger.info(f"📤 Creating opportunity: {opportunity_data}")
        
        # Create the lead
        opportunity_id = models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            'crm.lead', 'create',
            [opportunity_data]
        )
        
        logger.info(f"✅ Lead created with ID: {opportunity_id}")
        
        # =============================
        # ATTACH IMAGE (if exists)
        # =============================
        if lead.image:
            try:
                attachment_id = models.execute_kw(
                    ODOO_DB, uid, ODOO_PASSWORD,
                    'ir.attachment', 'create',
                    [{
                        'name': f"{safe_name}_{opportunity_id}.jpg",
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
        
        # If it's a duplicate, return success anyway
        if "unique" in fault.faultString.lower() or "duplicate" in fault.faultString.lower():
            logger.warning("⚠️ Duplicate lead detected")
            return {
                "status": "already_exists",
                "message": "Lead already exists",
                "id": None
            }
        
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
