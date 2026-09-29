"""Gemini helpers: prompts, JSON parsing, budget enforcement, fallbacks."""
import os, json, urllib.parse
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
_client = None

def client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    return _client

SEARCH = {
    "amazon": "https://www.amazon.in/s?k=", "flipkart": "https://www.flipkart.com/search?q=",
    "ikea": "https://www.ikea.com/in/en/search/?q=", "swiggy": "https://www.swiggy.com/search?query=",
    "zomato": "https://www.zomato.com/search?q=", "oyo": "https://www.oyorooms.com/search?query=",
}
PLATFORMS = {"home": "Amazon, IKEA, Flipkart", "party": "Swiggy, Zomato, OYO, Amazon (decor)", "jewelry": "Amazon, Flipkart"}

def link(platform, name):
    base = SEARCH.get(platform.lower().strip())
    q = urllib.parse.quote_plus(name)
    return base + q if base else "https://www.google.com/search?q=" + urllib.parse.quote_plus(f"{name} {platform}")

RULES = ('You are PocketSmart AI, a budget recommendation assistant for Indian users. Return ONLY JSON: '
         '{"summary":str,"items":[{"category":str,"name":str,"price":number,"platform":str,"reason":str}],"tips":[str]}. '
         'Prices are in Indian rupees (total for that line, including quantity). The sum of all prices MUST NOT exceed the budget. '
         'Balance functionality, style and price. Use only these platforms: {platforms}. Give 5-10 items.')

SPLIT = {"home": [("Lighting", .2), ("Furniture", .5), ("Decor", .3)],
         "party": [("Catering", .5), ("Decoration", .25), ("Entertainment", .15), ("Venue/Stay", .10)],
         "jewelry": [("Main piece", .6), ("Accessories", .4)]}
DEFAULT_PLATFORM = {"home": "IKEA", "party": "Swiggy", "jewelry": "Amazon"}

def fallback(category, budget):
    items = [{"category": c, "name": f"Best-rated {c.lower()} option", "price": round(budget * p),
              "platform": DEFAULT_PLATFORM[category], "reason": f"Default {int(p*100)}% share of your budget."}
             for c, p in SPLIT[category]]
    return {"summary": "Default budget split", "items": items, "tips": ["Try again later for personalised AI suggestions."], "fallback": True}

def recommend(category, budget, details, image=None):
    """image = (bytes, mime_type) or None. Always returns a usable result dict."""
    prompt = RULES.replace("{platforms}", PLATFORMS[category]) + f"\nCategory: {category}\nBudget: ₹{budget:,.0f}\n{details}"
    contents = [prompt]
    if image:
        contents.append(types.Part.from_bytes(data=image[0], mime_type=image[1]))
    try:
        r = client().models.generate_content(model=MODEL, contents=contents,
                config=types.GenerateContentConfig(response_mime_type="application/json"))
        data = json.loads(r.text)
        items = []
        for i in data.get("items", []):
            items.append({"category": str(i.get("category", "Item")), "name": str(i.get("name", "Item")),
                          "price": max(float(i.get("price", 0)), 0), "platform": str(i.get("platform", "Amazon")),
                          "reason": str(i.get("reason", ""))})
        if not items:
            raise ValueError("empty AI result")
        data = {"summary": str(data.get("summary", "Your plan")), "items": items, "tips": [str(t) for t in data.get("tips", [])]}
    except Exception as e:
        print("Gemini error -> fallback:", e)
        data = fallback(category, budget)
    while sum(i["price"] for i in data["items"]) > budget and len(data["items"]) > 1:
        data["items"].pop()  # enforce budget adherence
    for i in data["items"]:
        i["link"] = link(i["platform"], i["name"])
    data["budget"], data["total"] = budget, sum(i["price"] for i in data["items"])
    return data
