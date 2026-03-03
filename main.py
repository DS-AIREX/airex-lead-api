import os
from typing import Optional
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import xmlrpc.client
import traceback

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

common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
uid = common.authenticate(ODOO_DB, ODOO_USERNAME, ODOO_PASSWORD, {})
models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")


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

    try:

        # =============================
        # DUPLICATE CHECK
        # =============================
        existing = models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            'crm.lead', 'search',
            [[['x_unique_id', '=', lead.unique_id]]]
        )

        if existing:
            return {"status": "already_exists"}

        # =============================
        # CREATE CUSTOMER
        # =============================
        partner_id = None

        if lead.contact_person:
            partner_ids = models.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD,
                'res.partner', 'search',
                [[['name', '=', lead.contact_person]]]
            )

            if partner_ids:
                partner_id = partner_ids[0]
            else:
                partner_id = models.execute_kw(
                    ODOO_DB, uid, ODOO_PASSWORD,
                    'res.partner', 'create',
                    [{
                        'name': lead.contact_person,
                        'phone': lead.phone or '',
                        'mobile': lead.mobile or '',
                        'email': lead.email or ''
                    }]
                )

        # =============================
        # CREATE OPPORTUNITY
        # =============================
        opportunity_data = {
            'name': lead.name,
            'type': 'opportunity',
            'x_unique_id': lead.unique_id
        }

        if partner_id:
            opportunity_data['partner_id'] = partner_id

        if lead.phone:
            opportunity_data['phone'] = lead.phone

        if lead.mobile:
            opportunity_data['mobile'] = lead.mobile

        if lead.email:
            opportunity_data['email_from'] = lead.email

        if lead.notes:
            opportunity_data['description'] = lead.notes

        opportunity_id = models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            'crm.lead', 'create',
            [opportunity_data]
        )

        # =============================
        # ATTACH IMAGE
        # =============================
        if lead.image:
            models.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD,
                'ir.attachment', 'create',
                [{
                    'name': f"{lead.name}.jpg",
                    'type': 'binary',
                    'datas': lead.image,
                    'res_model': 'crm.lead',
                    'res_id': opportunity_id,
                    'mimetype': 'image/jpeg'
                }]
            )

        return {"status": "success"}

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
