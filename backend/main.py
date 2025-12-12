import os
import json
import base64
import stripe
import httpx
from fastapi import FastAPI, HTTPException, Request, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from openai import OpenAI
from fastapi.responses import StreamingResponse
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import io
from fastapi.responses import FileResponse
from reportlab.lib.units import inch
import os
import re
import csv
from collections import Counter
from fastapi.staticfiles import StaticFiles

# ==========================================================
# CONFIG (SECRET KEYS) – PUNE AICI CHEILE TALE
# ==========================================================
STRIPE_SECRET_KEY = "sk_test_51SWljX2V8A3yCU41G6q1XyJdcx9o5BmJpLfnFv9KiZnJCKXoRp20vi34bo7O8LSp4WI9ycMUnHsE4RFots2P5UM900Mfcf9a1c"    # ← CHEIA TA
OPENAI_API_KEY   = "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"     # ← CHEIA TA

stripe.api_key = STRIPE_SECRET_KEY
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# EPC & GEO / CRIME CONFIG
EPC_API_TOKEN = os.getenv("e6a7031d07ecea7518fb3cfc36111abbe5b9d832", "")  # aici pui token-ul Basic encoded din EPC
POSTCODES_BASE = "https://api.postcodes.io"
POLICE_BASE = "https://data.police.uk"

FRONTEND_ORIGIN = "http://127.0.0.1:5500"

# ==========================================================
# FASTAPI INIT
# ==========================================================
app = FastAPI(title="AiHousing Backend", version="2.2")


from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "http://127.0.0.1:8000",
        "http://localhost:8000"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================================
# MODELS
# ==========================================================
class CheckoutRequest(BaseModel):
    plan: str
    property_input: str
    photos: Optional[List[str]] = None
    email: Optional[str] = None


# ==========================================================
# PLACEHOLDER OFFICIAL DATA (până conectăm API-urile gov)
# ==========================================================

# ==========================================================
# OFFICIAL DATA CONNECTORS (EPC, CRIME, PRICE)
# ==========================================================

async def fetch_epc(address: str) -> dict:
    """
    EPC: API oficial epc.opendatacommunities.org (domestic search by postcode).
    Returnăm doar câmpurile de care avem nevoie pentru AI.
    """
    postcode = extract_postcode(address)
    if not postcode or not EPC_API_TOKEN:
        return {
            "postcode": postcode,
            "rating": None,
            "potential_rating": None,
            "current_energy_efficiency": None,
            "potential_energy_efficiency": None,
            "lmk_key": None,
            "source": "epc.opendatacommunities.org (missing postcode or token)"
        }

    url = "https://epc.opendatacommunities.org/api/v1/domestic/search"
    headers = {
        "Accept": "text/csv",  # conform documentației EPC
        "Authorization": f"Basic {EPC_API_TOKEN}",
    }
    params = {"postcode": postcode}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers, params=params)

        if resp.status_code != 200 or not resp.text.strip():
            return {
                "postcode": postcode,
                "rating": None,
                "potential_rating": None,
                "current_energy_efficiency": None,
                "potential_energy_efficiency": None,
                "lmk_key": None,
                "source": f"epc.opendatacommunities.org status={resp.status_code}"
            }

        # Parse CSV (primul rând = header, al doilea = prima proprietate găsită)
        text = resp.text
        reader = csv.DictReader(io.StringIO(text))
        first = next(reader, None)
        if not first:
            return {
                "postcode": postcode,
                "rating": None,
                "potential_rating": None,
                "current_energy_efficiency": None,
                "potential_energy_efficiency": None,
                "lmk_key": None,
                "source": "epc.opendatacommunities.org (no rows)"
            }

        return {
            "postcode": postcode,
            "rating": first.get("current-energy-rating"),
            "potential_rating": first.get("potential-energy-rating"),
            "current_energy_efficiency": first.get("current-energy-efficiency"),
            "potential_energy_efficiency": first.get("potential-energy-efficiency"),
            "lmk_key": first.get("lmk-key"),
            "source": "epc.opendatacommunities.org"
        }

    except Exception as e:
        return {
            "postcode": postcode,
            "rating": None,
            "potential_rating": None,
            "current_energy_efficiency": None,
            "potential_energy_efficiency": None,
            "lmk_key": None,
            "source": f"epc.opendatacommunities.org error: {e}"
        }


async def fetch_crime(address: str) -> dict:
    """
    Crime: API oficial data.police.uk, folosind coordonate de la postcodes.io.
    Luăm toate crimele 'all-crime' pentru cea mai recentă lună disponibilă,
    într-un radius ~1 milă (implicit).
    """
    postcode = extract_postcode(address)
    if not postcode:
        return {
            "postcode": None,
            "crime_count_last_month": None,
            "top_categories": [],
            "summary": "No postcode found in address."
        }

    loc = await get_lat_lng_from_postcode(postcode)
    if not loc or not loc.get("lat") or not loc.get("lng"):
        return {
            "postcode": postcode,
            "crime_count_last_month": None,
            "top_categories": [],
            "summary": "Could not resolve postcode to lat/lng."
        }

    url = f"{POLICE_BASE}/api/crimes-street/all-crime"
    params = {
        "lat": loc["lat"],
        "lng": loc["lng"],
        # fără 'date' => ultima lună disponibilă în API
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)

        if resp.status_code != 200:
            return {
                "postcode": postcode,
                "crime_count_last_month": None,
                "top_categories": [],
                "summary": f"data.police.uk error status={resp.status_code}"
            }

        crimes = resp.json()
        total = len(crimes)

        if total == 0:
            return {
                "postcode": postcode,
                "crime_count_last_month": 0,
                "top_categories": [],
                "summary": "No street-level crimes recorded in the latest month for this location."
            }

        categories = [c.get("category", "unknown") for c in crimes]
        counter = Counter(categories)
        top3 = counter.most_common(3)
        top_list = [{"category": cat, "count": cnt} for cat, cnt in top3]
        top_str = ", ".join([f"{cat} ({cnt})" for cat, cnt in top3])

        return {
            "postcode": postcode,
            "crime_count_last_month": total,
            "top_categories": top_list,
            "summary": f"{total} recorded street-level crimes in the latest month within ~1 mile. Most common: {top_str}.",
            "source": "data.police.uk"
        }

    except Exception as e:
        return {
            "postcode": postcode,
            "crime_count_last_month": None,
            "top_categories": [],
            "summary": f"data.police.uk error: {e}"
        }


async def build_dataset(address: str) -> dict:
    """
    Construiește datasetul pe care îl dăm la OpenAI:
    - postcode extras
    - EPC real (dacă există)
    - crime real, ultima lună (data.police.uk)
    - hook pentru price data oficial (Land Registry)
    """
    postcode = extract_postcode(address)

    epc = await fetch_epc(address)
    crime = await fetch_crime(address)
    price = await fetch_price_data(address)

    return {
        "input": address,
        "postcode": postcode,
        "epc": epc,
        "crime": crime,
        "price": price
    }


POSTCODE_REGEX = re.compile(
    r"\b([A-Z]{1,2}\d{1,2}[A-Z]?\s*\d[A-Z]{2})\b",
    re.IGNORECASE
)

def extract_postcode(address: str) -> Optional[str]:
    """
    Extrage un postcode UK dintr-un string de adresă.
    Exemplu: '10 Downing Street, London SW1A 2AA' -> 'SW1A 2AA'
    """
    if not address:
        return None
    m = POSTCODE_REGEX.search(address.upper())
    if not m:
        return None
    pc = m.group(1).upper().replace(" ", "")
    # normalizăm la format 'SW1A 2AA'
    return pc[:-3] + " " + pc[-3:]

async def get_lat_lng_from_postcode(postcode: str) -> Optional[Dict[str, Any]]:
    """
    Folosește postcodes.io pentru a obține coordonatele și un pic de info zonală.
    """
    if not postcode:
        return None

    url = f"{POSTCODES_BASE}/postcodes/{postcode}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url)
    if resp.status_code != 200:
        return None

    data = resp.json().get("result")
    if not data:
        return None

    return {
        "lat": data.get("latitude"),
        "lng": data.get("longitude"),
        "admin_district": data.get("admin_district"),
        "region": data.get("region"),
        "country": data.get("country"),
    }

LAND_REGISTRY_SPARQL = "https://landregistry.data.gov.uk/landregistry/query"

async def fetch_price_data(address: str) -> dict:
    postcode = extract_postcode(address)
    if not postcode:
        return {
            "postcode": None,
            "transactions": [],
            "notes": "No postcode; cannot query Land Registry."
        }

    query = f"""
    PREFIX lrppi: <http://landregistry.data.gov.uk/def/ppi/>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

    SELECT ?price ?date ?paon ?street
    WHERE {{
      ?transx lrppi:pricePaid ?price .
      ?transx lrppi:transactionDate ?date .
      ?transx lrppi:propertyAddress ?addr .
      ?addr lrppi:postcode "{postcode}" .
      OPTIONAL {{ ?addr lrppi:paon ?paon . }}
      OPTIONAL {{ ?addr lrppi:street ?street . }}
    }}
    ORDER BY DESC(?date)
    LIMIT 20
    """

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                LAND_REGISTRY_SPARQL,
                data={"query": query},
                headers={"Accept": "application/sparql-results+json"}
            )

        if resp.status_code != 200:
            return {
                "postcode": postcode,
                "transactions": [],
                "notes": f"SPARQL error {resp.status_code}"
            }

        results = resp.json().get("results", {}).get("bindings", [])

        tx = []
        for row in results:
            tx.append({
                "price": int(row.get("price", {}).get("value", "0")),
                "date": row.get("date", {}).get("value", ""),
                "address": f"{row.get('paon',{}).get('value','')} {row.get('street',{}).get('value','')}".strip()
            })

        return {
            "postcode": postcode,
            "transactions": tx,
            "notes": "Land Registry SPARQL latest 20 sales (price, date, address)"
        }

    except Exception as e:
        return {
            "postcode": postcode,
            "transactions": [],
            "notes": f"SPARQL exception: {e}"
        }
# ==========================================================
# MAIN AI REPORT
# ==========================================================
async def generate_ai(property_input: str, plan: str, dataset: dict, photos_ai: list):

              prompt = f"""
    You are AiHousing. You generate property reports ONLY based on:

    1) PROPERTY INPUT: {property_input}
2) OFFICIAL DATA (JSON below)
3) PHOTO ANALYSIS (if available)

You must use the official data in a meaningful way, including:

- For EPC:
  * current-energy-rating
  * potential-energy-rating
  * current-energy-efficiency
  * potential-energy-efficiency
  * explain if rating is good, average or poor vs UK average

- For CRIME:
  * crime_count_last_month
  * top_categories
  * administrivia (region/district)
  * describe what this means for safety, noise, lifestyle and perception

- For PRICE:
  * if notes mention Land Registry
  * use postcode and property type to infer a realistic value range
  * use recent sold prices (from dataset if available)
  * justify if property looks OVER or UNDER market

WRITE LIKE A HUMAN EXPERT SURVEYOR:
- clear, concise, confident
- avoid legal language
- say what matters for a buyer

OUTPUT: STRICT JSON ONLY, with these keys:

"title", "subtitle",
"overall_condition_score", "overall_condition_label",
"max_recommended_offer", "ai_value_range",
"damp_mould_risk", "crime_noise", "flood_zone",
"tags", "section1_points",
"negotiation_bullets",
"negotiation_email",
"next_steps",
"raw_full_report"

Where:

- "negotiation_bullets" = 6–10 short bullets for price negotiation
- "negotiation_email" = short email template (2 paragraphs max)
- "next_steps" = 5–8 bullet items
- "raw_full_report" = full reasoning in plain text

IMPORTANT:
- Do NOT invent exact property prices or exact crime counts.
- Use ranges and narrative when uncertain.
- For price, use LAND REGISTRY data logic:
  - similar properties in same postcode area
  - UK average price movements

Here are the JSON datasets you MUST USE:

OFFICIAL DATA:
{json.dumps(dataset, indent=2)}

PHOTO ANALYSIS:
{json.dumps(photos_ai, indent=2)}
"""


@app.post("/start-report")
async def start_report(req: Request, payload: dict = Body(...)):

    origin = req.headers.get("origin") or FRONTEND_ORIGIN

    plan = payload.get("plan", "basic")
    address = payload.get("address", "")
    link = payload.get("link", "")
    photos = payload.get("photos", [])

    # convert array to JSON
    photos_json = json.dumps(photos)

    # choose price
    amount = 1299 if plan == "basic" else 4999

    # create stripe session
    sess = stripe.checkout.Session.create(
        mode="payment",
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": "gbp",
                "product_data": {"name": f"AiHousing {plan} report"},
                "unit_amount": amount
            },
            "quantity": 1
        }],
        success_url=f"{origin}/premium_report.html?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{origin}/",
        metadata={
            "plan": plan,
            "property_input": address,
            "link": link,
            "photos": photos_json
        }
    )

    return {"session_url": sess.url}

# ==========================================================
# PHOTO ANALYSIS (AI)
# ==========================================================
@app.post("/ai-photo-multiple")
async def ai_photo_multiple(payload: dict = Body(...)):
    images = payload.get("images", [])
    if not images:
        return {"results": []}

    results = []

    for img in images[:5]:
        clean = img.split(",")[-1]

        try:
            img_bytes = base64.b64decode(clean)
        except:
            results.append({
                "title": "Invalid image",
                "description": "Could not decode image",
                "tags": ["invalid"]
            })
            continue

        try:
            resp = openai_client.chat.completions.create(
                model="gpt-4.1",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are AiHousing Photo Inspector. "
                            "Describe ONLY what is visible. "
                            "No locations, no prices, no extra assumptions. "
                            "Return JSON only."
                        )
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": "Analyse this photo"},
                            {"type": "input_image", "image": img_bytes}
                        ]
                    }
                ],
                response_format={"type": "json_object"},
                temperature=0.25
            )

            results.append(json.loads(resp.choices[0].message.content))

        except Exception as e:
            results.append({
                "title": "Error analysing photo",
                "description": str(e),
                "tags": ["error"]
            })

    return {"results": results}


# ==========================================================
# STRIPE CHECKOUT
# ==========================================================
@app.post("/create-checkout-session")
async def create_checkout(req: Request, body: CheckoutRequest):

    origin = req.headers.get("origin") or FRONTEND_ORIGIN

    # basic = £12.49 | full = £49.99
    amount = 1299 if body.plan == "basic" else 4999

    sess = stripe.checkout.Session.create(
        mode="payment",
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": "gbp",
                "product_data": {"name": f"AiHousing {body.plan} report"},
                "unit_amount": amount
            },
            "quantity": 1
        }],
        success_url=f"{origin}/premium_report.html?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{origin}/paywall.html",
        metadata={
            "plan": body.plan,
            "property_input": body.property_input,
            "photos": json.dumps(body.photos or [])
        }
    )

    return {"id": sess.id}


# ==========================================================
# FINAL PREMIUM REPORT ENDPOINT (FULL STACK)
# ==========================================================
@app.get("/premium-report")
async def premium_report(session_id: str):

    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except:
        raise HTTPException(400, "Invalid session_id")

    if session.payment_status != "paid":
        raise HTTPException(402, "Payment incomplete")

    metadata = session.metadata or {}
    plan = metadata.get("plan", "basic")
    property_input = metadata.get("property_input", "")

    # decode photos
    try:
        photos = json.loads(metadata.get("photos", "[]"))
    except:
        photos = []

    # build dataset
    dataset = await build_dataset(property_input)

    # photo AI
    photos_ai = []
    if photos:
        ai_resp = await ai_photo_multiple({"images": photos})
        photos_ai = ai_resp.get("results", [])

        for i, p in enumerate(photos_ai):
            p["base64"] = photos[i]

    # main AI report
    ai = await generate_ai(property_input, plan, dataset, photos_ai)

    return {
        "session_id": session_id,
        "plan": plan,
        "property_input": property_input,
        "dataset": dataset,
        "ai": {
            **ai,
            "photo_analysis": photos_ai
        }
    }
# ==========================================================
# GENERARE PDF DIN RAPORT
# ==========================================================
@app.post("/generate-pdf")
async def generate_pdf(payload: dict = Body(...)):
    session_id = payload.get("session_id")
    ai = payload.get("ai")

    if not session_id or not ai:
        raise HTTPException(status_code=400, detail="Missing session_id or ai data")

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    y = height - 60

    # TITLU
    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, y, ai.get("title", "AiHousing Report"))
    y -= 25

    # SUBTITLU
    c.setFont("Helvetica", 11)
    c.drawString(50, y, ai.get("subtitle", ""))
    y -= 30

    # REZUMAT PUNCTE
    c.setFont("Helvetica-Bold", 13)
    c.drawString(50, y, "Summary")
    y -= 18

    c.setFont("Helvetica", 10)
    for point in ai.get("section1_points", []):
        c.drawString(60, y, f"- {point}")
        y -= 14
        if y < 80:
            c.showPage()
            y = height - 60
            c.setFont("Helvetica", 10)

    # PAGINA NOUĂ – FULL REPORT
    c.showPage()
    y = height - 60
    c.setFont("Helvetica-Bold", 13)
    c.drawString(50, y, "Full AI report")
    y -= 20

    c.setFont("Helvetica", 9)
    text = c.beginText(50, y)
    raw = ai.get("raw_full_report", "")

    for line in raw.split("\n"):
        text.textLine(line)
        if text.getY() < 60:
            c.drawText(text)
            c.showPage()
            text = c.beginText(50, height - 60)
            text.setFont("Helvetica", 9)

    c.drawText(text)
    c.save()

    buffer.seek(0)
    headers = {
        "Content-Disposition": f'attachment; filename="aihousing_report_{session_id}.pdf"'
    }
    return StreamingResponse(buffer, media_type="application/pdf", headers=headers)

app.mount("/", StaticFiles(directory="frontend", html=True), name="static")