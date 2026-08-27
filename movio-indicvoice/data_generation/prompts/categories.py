"""
Taxi-domain Tanglish prompt categories and seed examples for synthetic generation.

Each category includes DATE and TIME example sentences as first-class cases.
"""
from __future__ import annotations

CATEGORIES = [
    "booking",
    "cancellation",
    "driver_arrival",
    "pickup",
    "drop",
    "payment",
    "otp",
    "traffic",
    "complaints",
    "general_conversation",
]

# 5–8 SEED_EXAMPLES per category (used as placeholders in the generation prompt)
SEED_EXAMPLES: dict[str, list[str]] = {
    "booking": [
        "Naan Guindy ku cab book pannanum, evening 7:30 PM ku.",
        "Booking for tomorrow 9 AM from Velachery to Airport.",
        "Oru AC cab T Nagar la irundhu OMR ku book pannunga.",
        "Adyar pickup, Porur drop — booking confirm aana sollunga.",
        "Cab needed at 6 AM tomorrow near Anna Nagar metro.",
        "Share auto Velachery to Tambaram book pannalama?",
        "Office ku 8:15 AM sharp cab venum.",
    ],
    "cancellation": [
        "Booking cancel pannunga please, plans change aagiruchu.",
        "Cancel my cab scheduled for 5:30 PM today.",
        "Cancellation charges irukka? Tomorrow morning booking cancel.",
        "Driver late ah irukku, cancel panni new booking pannunga.",
        "Wrong location select panniten — cancel and rebook please.",
        "Cancel the booking ID TN45AB1234 for tonight 9 PM.",
    ],
    "driver_arrival": [
        "Unga driver 5 minutes la vandhuruvaanga.",
        "Driver has arrived at your pickup point near Guindy.",
        "Cab TN45AB1234 gate la wait pannitu irukku.",
        "Driver 7:30 PM sharp ku reach aavaaru.",
        "Your driver is 2 minutes away from Velachery location.",
        "Driver arrived — white Swift, plate TN09CD5678.",
    ],
    "pickup": [
        "Pickup location Guindy bus stand opposite ah confirm pannunga.",
        "Naan Velachery main road la wait pannitu irukken.",
        "Please come to Gate 3 Airport pickup at 10:45 AM.",
        "Driver, pickup point T Nagar bus terminus.",
        "Customer waiting at Porur toll plaza for pickup.",
        "Share your live location for accurate pickup.",
    ],
    "drop": [
        "Drop location Adyar signal nearby office building.",
        "OMR Sholinganallur ku drop pannunga.",
        "Please drop at Tambaram railway station entrance.",
        "Final drop Anna Nagar 2nd avenue tomorrow 8 AM trip.",
        "Drop me at Central station by 6:20 PM.",
        "Home drop Velachery 4th main road.",
    ],
    "payment": [
        "Payment UPI la settle pannalam, fare ₹245.",
        "Cash payment okay va? Receipt venum.",
        "GPay scan pannunga — total ₹180 including toll.",
        "Payment failed for booking yesterday 9 PM trip.",
        "Fare estimate Guindy to Airport roughly ₹450.",
        "Invoice email pannunga for corporate payment.",
    ],
    "otp": [
        "Your OTP is 4821 — share with driver only.",
        "OTP 7390 enter pannunga to start the trip.",
        "Please verify OTP 1568 before pickup.",
        "Driver asking OTP — ungal OTP 9042.",
        "Trip start aaganum na OTP 2210 share pannunga.",
        "Do not share OTP 8831 with anyone except your driver.",
    ],
    "traffic": [
        "Traffic heavy ah irukku on OMR, delay aagum.",
        "Guindy signal jam — ETA 15 minutes extra.",
        "Avoid ECR, traffic clear on Inner Ring Road.",
        "Peak hour traffic from 6 PM to 8:30 PM near T Nagar.",
        "Accident near Porur — alternate route suggest pannunga.",
        "Rain traffic Velachery la slow moving.",
    ],
    "complaints": [
        "Driver rude ah speak pannanga — complaint raise pannunga.",
        "AC work aagala during my 3 PM Airport trip.",
        "Wrong route take pannitu fare increase aagiruchu.",
        "Cab dirty ah irundhuchu — feedback register pannunga.",
        "Driver called and asked to cancel for tomorrow 7 AM booking.",
        "Payment double charged for booking ID 88421.",
    ],
    "general_conversation": [
        "Hello anna, location correct ah confirm pannunga.",
        "Romba thanks for the quick cab assignment.",
        "Can you wait 2 minutes? Lift la irukken.",
        "Chennai weather heavy rain — careful ah drive pannunga.",
        "Okay sir, reaching in five minutes.",
        "Any luggage ah? Boot space check pannunga.",
        "Call me when you reach the gate at 9:15 AM.",
    ],
}


SYSTEM_INSTRUCTION = (
    "Do NOT translate to pure Tamil or pure English. Code-mix naturally the way "
    "real Chennai taxi customers/drivers speak. Keep English loanwords like cab, "
    "OTP, driver, location, traffic UNTRANSLATED — do not convert them to Tamil "
    "script. Mix in real Chennai place names (Guindy, Velachery, OMR, T Nagar, "
    "Porur, Adyar). Vary formality and sentence length. Avoid textbook Tamil or "
    "literary register — this is spoken conversational Tanglish. "
    "Include some DATE and TIME sentences (e.g. cab at 7:30 PM, booking for "
    "tomorrow 9 AM). "
    "Respond with a JSON array ONLY — no markdown fences, no commentary. "
    'Each item: {"text": "...", "category": "...", "language_mix": "..."} '
    "where language_mix is one of: tanglish, english, tamil, mixed."
)


def build_user_prompt(category: str, n_sentences: int) -> str:
    seeds = SEED_EXAMPLES.get(category, [])
    seed_block = "\n".join(f"- {s}" for s in seeds)
    return (
        f"Generate exactly {n_sentences} unique spoken Tanglish taxi-agent sentences "
        f"for category '{category}'.\n\n"
        f"SEED_EXAMPLES:\n{seed_block}\n\n"
        f"{SYSTEM_INSTRUCTION}\n"
        f"All items must have category=\"{category}\"."
    )
