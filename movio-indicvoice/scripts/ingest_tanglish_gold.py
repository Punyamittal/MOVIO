# -*- coding: utf-8 -*-
"""One-shot ingest of English→Tanglish gold pairs into project data."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PAIRS: list[tuple[str, str]] = [
    # batch A (30)
    (
        "I am waiting outside the hotel lobby, and the driver is standing near the parking entrance, but neither of us can see the other.",
        "Naan hotel lobby-ku veliya wait pannitu irukken, driver parking entrance pakkathula nikkiraanga, aana rendu perukkum oruthar oruthara paakka mudiyala.",
    ),
    (
        "Please tell the driver that I have reached the pickup point and that I am standing beside the security guard.",
        "Naan pickup point-ku vandhuten-nu driver-kitta sollunga, naan security guard pakkathula nikkiren.",
    ),
    (
        "The driver is only three minutes away, but there is a lot of traffic near the signal, so he may take a little longer to arrive.",
        "Driver innum moonu minutes distance-la dhaan irukkaaru, aana signal pakkathula romba traffic irukku, so avaru vara konjam late aagalam.",
    ),
    (
        "I have a blue suitcase and a black backpack with me, so the driver should be able to recognize me easily.",
        "En kitta oru blue suitcase-um black backpack-um irukku, so driver enna easy-ah identify panniduvaanga.",
    ),
    (
        "Please ask the driver to wait near the main gate because I need a few minutes to collect my luggage.",
        "En luggage eduthuttu vara enakku konjam time aagum, so driver-a main gate pakkathula wait panna sollunga.",
    ),
    (
        "I think the driver has taken the wrong road because the distance shown on the map is increasing instead of decreasing.",
        "Driver thappana road-la poittu irukkaaru-nu ninaikkiren, yenna map-la distance koraiyaama adhigama aagittu irukku.",
    ),
    (
        "My destination is Chennai Central, but the driver seems to be heading toward Egmore, so please confirm the destination with him.",
        "En destination Chennai Central, aana driver Egmore pakkam poittu irukkaaru pola irukku, so avar kitta destination-a confirm pannunga.",
    ),
    (
        "I received the OTP a few seconds ago, but I want to make sure that I am giving the latest code to the correct driver.",
        "Enakku konjam seconds-ku munnadi OTP vandhuduchu, aana latest code-a correct driver-kitta dhaan share panren-nu confirm pannikanum.",
    ),
    (
        "Please tell the driver to slow down because I have not finished putting my luggage inside the vehicle.",
        "En luggage-a vehicle-kulla innum complete-ah veikkala, so driver-a konjam slow-ah drive panna sollunga.",
    ),
    (
        "I am currently standing on the opposite side of the road, and I will cross over as soon as the traffic becomes lighter.",
        "Naan ippo road-oda opposite side-la nikkiren, traffic konjam koranjadhum naan cross panni vandhuruven.",
    ),
    (
        "The driver said he would reach in ten minutes, but the application now shows an estimated arrival time of eighteen minutes.",
        "Driver ten minutes-la reach aagiduven-nu sonnaaru, aana ippo application-la eighteen minutes ETA kaamikudhu.",
    ),
    (
        "I need to reach the railway station before my train departs, so please avoid roads with heavy traffic if there is another route available.",
        "En train kelamburadhukku munnadi railway station-ku reach aaganum, so vera route irundha heavy traffic irukkura roads-a avoid pannunga.",
    ),
    (
        "The pickup location has changed because the original entrance is temporarily closed for construction.",
        "Construction work nala original entrance temporary-ah close pannitaanga, so pickup location change aagiduchu.",
    ),
    (
        "Please ask the driver whether he can wait for five minutes while I finish my meeting and come downstairs.",
        "Naan meeting-a mudichittu keezha vara five minutes aagum, adhukku varaikkum wait panna mudiyuma-nu driver kitta kelunga.",
    ),
    (
        "I cannot hear the driver clearly because there is too much background noise around me.",
        "Enna suthi romba background noise irukku, so driver enna clear-ah kekka mudiyala.",
    ),
    (
        "The driver is calling me, but I am currently unable to answer the phone because I am inside a meeting.",
        "Driver enakku call pannitu irukkaaru, aana naan ippo meeting-kulla irukken, so phone attend panna mudiyala.",
    ),
    (
        "Please tell the driver that I am standing next to the red signboard directly opposite the pharmacy.",
        "Pharmacy-ku exact opposite-la irukkura red signboard pakkathula naan nikkiren-nu driver-kitta sollunga.",
    ),
    (
        "I have already shared my live location, but the driver says that the map is showing a different entrance.",
        "Naan already live location share panniten, aana map-la vera entrance kaamikudhu-nu driver solraaru.",
    ),
    (
        "The vehicle number is TN 38 AB 7294, so please confirm that this is the correct vehicle before I get inside.",
        "Vehicle number TN 38 AB 7294, so naan vehicle-kulla yeruradhukku munnadi idhu correct vehicle dhaana-nu confirm pannunga.",
    ),
    (
        "If the driver reaches before me, please ask him to wait near the security cabin instead of leaving the pickup location.",
        "Driver enakku munnadi vandhuttaaru-na, pickup location-a vittu pogama security cabin pakkathula wait panna sollunga.",
    ),
    (
        "I have three bags with me, including one fragile suitcase, so please make sure there is enough space in the trunk.",
        "En kitta moonu bags irukku, adhula oru fragile suitcase-um irukku, so trunk-la pothumaana space irukka-nu check pannunga.",
    ),
    (
        "The road ahead is blocked because of an accident, so the driver may need to take a longer route to reach the destination.",
        "Accident nala munnadi road block aagirukku, so destination-ku reach aaga driver konjam long route edukkanum pola irukku.",
    ),
    (
        "I accidentally left my phone charger in the vehicle, so please contact the driver and ask whether he found it.",
        "Thappudhala en phone charger-a vehicle-kulla vittuten, so driver-a contact panni avarukku adhu kidaichudha-nu kelunga.",
    ),
    (
        "The driver dropped me at the wrong entrance, and I need directions to reach the actual destination from here.",
        "Driver enna wrong entrance-la drop pannitaanga, inga irundhu actual destination-ku eppadi poganum-nu directions venum.",
    ),
    (
        "I am not familiar with this area, so please explain to the driver exactly where I need to be picked up.",
        "Enakku indha area pathi familiar illa, so enna exact-ah enga pickup panna vendum-nu driver-kitta explain pannunga.",
    ),
    (
        "The map says that the destination is only two kilometers away, but the current traffic could make the journey take more than fifteen minutes.",
        "Map-la destination rendu kilometers dhaan distance-nu kaamikudhu, aana current traffic nala journey fifteen minutes-ku mela aagalam.",
    ),
    (
        "Please ask the driver to confirm the final fare before we start the trip because the amount shown on my application has changed.",
        "Trip start panradhukku munnadi final fare-a confirm panna driver-kitta sollunga, yenna application-la kaamikura amount change aagiduchu.",
    ),
    (
        "I can see the vehicle approaching from the left, but I am not sure whether it is the taxi assigned to my booking.",
        "Left side-la oru vehicle varradhu enakku theriyudhu, aana adhu en booking-ku assigned aana taxi dhaana-nu sure-ah theriyala.",
    ),
    (
        "The driver has arrived at the pickup point, but he is waiting on the other side of the building.",
        "Driver pickup point-ku vandhutaanga, aana building-oda opposite side-la wait pannitu irukkaaru.",
    ),
    (
        "Please tell the driver that I will be wearing a grey jacket and carrying a red suitcase.",
        "Naan grey jacket pottuttu red suitcase eduthuttu iruppen-nu driver-kitta sollunga.",
    ),
    # batch B (40)
    (
        "Please tell the driver that I am waiting near the blue entrance.",
        "Naan blue entrance pakkathula wait pannitu irukken-nu driver-kitta sollunga.",
    ),
    (
        "The driver is waiting at the wrong gate, so please redirect him to the main entrance.",
        "Driver wrong gate-la wait pannitu irukkaaru, so avara main entrance-ku vara sollunga.",
    ),
    (
        "I am already inside the vehicle, and we are ready to start the trip.",
        "Naan already vehicle-kulla irukken, trip start panna ready-ah irukkom.",
    ),
    (
        "Please ask the driver to stop near the next signal.",
        "Adutha signal pakkathula vehicle-a stop panna driver-kitta sollunga.",
    ),
    (
        "The driver is moving in the opposite direction from my destination.",
        "Driver en destination-ku opposite direction-la poittu irukkaaru.",
    ),
    (
        "I think the map has not updated my new pickup location yet.",
        "En new pickup location-a map innum update pannala-nu ninaikkiren.",
    ),
    (
        "Please wait for me near the entrance while I finish my phone call.",
        "Naan phone call-a mudikkura varaikkum entrance pakkathula enakkaga wait pannunga.",
    ),
    (
        "The security guard is asking for the vehicle details before allowing the driver inside.",
        "Driver-a ulla viduradhukku munnadi security guard vehicle details kekkaraaru.",
    ),
    (
        "I have reached the location, but the driver has not arrived yet.",
        "Naan location-ku vandhuten, aana driver innum varala.",
    ),
    (
        "The driver said he is five minutes away, but the map shows ten minutes.",
        "Driver five minutes distance-la irukken-nu sonnaaru, aana map-la ten minutes kaamikudhu.",
    ),
    (
        "Please tell the driver that I am standing next to the ATM.",
        "Naan ATM pakkathula nikkiren-nu driver-kitta sollunga.",
    ),
    (
        "I cannot cross the road because there is too much traffic right now.",
        "Ippo romba traffic irukkuradhunaala ennaala road cross panna mudiyala.",
    ),
    (
        "Please ask the driver to wait until the traffic signal turns green.",
        "Traffic signal green aagura varaikkum wait panna driver-kitta sollunga.",
    ),
    (
        "The vehicle is parked behind the building near the loading area.",
        "Vehicle building-oda pinnadi loading area pakkathula park pannirukku.",
    ),
    (
        "I am carrying a large suitcase, so I need some help putting it in the trunk.",
        "En kitta periya suitcase irukku, so adha trunk-la vekka konjam help venum.",
    ),
    (
        "Please confirm whether the driver has the correct booking details.",
        "Driver kitta correct booking details irukka-nu confirm pannunga.",
    ),
    (
        "I received a notification saying that the ride has started, but I am still waiting outside.",
        "Ride start aagiduchu-nu notification vandhudhu, aana naan innum veliya wait pannitu irukken.",
    ),
    (
        "The driver accidentally cancelled the ride while I was getting into the vehicle.",
        "Naan vehicle-kulla yerumbodhu driver thappudhala ride cancel pannitaanga.",
    ),
    (
        "Please ask the driver if he can take the highway instead of the local road.",
        "Local road-ku badhila highway-la poga mudiyuma-nu driver-kitta kelunga.",
    ),
    (
        "I would prefer to take a slightly longer route if it has less traffic.",
        "Traffic kammiya irundha konjam long route-a irundhaalum parava illa, adha eduthukkalaam.",
    ),
    (
        "The driver is approaching the pickup point from the other side of the bridge.",
        "Driver bridge-oda opposite side-la irundhu pickup point-ku vandhuttu irukkaaru.",
    ),
    (
        "Please tell the driver not to park directly in front of the entrance.",
        "Entrance-ku direct-ah munnadi park panna vendam-nu driver-kitta sollunga.",
    ),
    (
        "I am standing near a large white signboard with the building name on it.",
        "Building name irukkura periya white signboard pakkathula naan nikkiren.",
    ),
    (
        "The driver cannot hear me because there is too much traffic noise.",
        "Romba traffic noise irukkuradhunaala driver ennaala pesuradha kekka mudiyala.",
    ),
    (
        "Please repeat the destination because I want to make sure it is correct.",
        "Destination-a marubadiyum sollunga, adhu correct dhaana-nu naan confirm pannanum.",
    ),
    (
        "I have changed my destination, so please update the new location before we leave.",
        "Naan destination change panniten, so naanga kelamburadhukku munnadi new location-a update pannunga.",
    ),
    (
        "The driver is asking me which entrance he should use.",
        "Endha entrance use pannanum-nu driver enna kekkaraaru.",
    ),
    (
        "Please tell him to enter through the gate next to the petrol station.",
        "Petrol station pakkathula irukkura gate vazhiya ulla vara sollunga.",
    ),
    (
        "I am waiting near the reception desk on the ground floor.",
        "Naan ground floor-la reception desk pakkathula wait pannitu irukken.",
    ),
    (
        "The driver has reached the destination, but I need help finding the correct building.",
        "Driver destination-ku vandhutaanga, aana correct building-a kandupidikka enakku help venum.",
    ),
    (
        "Please ask the driver to call me when he reaches the pickup location.",
        "Driver pickup location-ku vandhadhum enakku call panna sollunga.",
    ),
    (
        "I accidentally left my wallet in the back seat of the vehicle.",
        "Thappudhala en wallet-a vehicle-oda back seat-la vittuten.",
    ),
    (
        "Please contact the driver and ask him to check the back seat.",
        "Driver-a contact panni back seat-a check panna sollunga.",
    ),
    (
        "The vehicle is moving very slowly because the road is crowded.",
        "Road-la romba crowd irukkuradhunaala vehicle romba slow-ah poittu irukku.",
    ),
    (
        "I need to reach the airport as quickly as possible.",
        "Enakku mudinja alavukku seekiram airport-ku reach aaganum.",
    ),
    (
        "Please tell the driver that I have a flight in two hours.",
        "Innum rendu hours-la enakku flight irukku-nu driver-kitta sollunga.",
    ),
    (
        "There is a road closure ahead, so we need to take a different route.",
        "Munnadi road close pannirukkaanga, so naanga vera route-la poga vendiyadhu irukku.",
    ),
    (
        "I am not sure whether this is the correct vehicle, so please verify the vehicle number.",
        "Idhu correct vehicle dhaana-nu enakku sure-ah theriyala, so vehicle number-a verify pannunga.",
    ),
    (
        "Please tell the driver that I will meet him near the entrance in two minutes.",
        "Rendu minutes-la entrance pakkathula driver-a meet panren-nu sollunga.",
    ),
    (
        "If the driver cannot find me, please ask him to call me instead of cancelling the ride.",
        "Driver enna kandupidikka mudiyalena, ride cancel pannama enakku call panna sollunga.",
    ),
    # batch C (40)
    (
        "Please tell the driver that I am waiting near the lift on the ground floor.",
        "Naan ground floor-la lift pakkathula wait pannitu irukken-nu driver-kitta sollunga.",
    ),
    (
        "The driver has reached the location, but he is standing near a different building.",
        "Driver location-ku vandhutaanga, aana vera building pakkathula nikkiraanga.",
    ),
    (
        "I am coming out of the building now, so please ask the driver to wait for a minute.",
        "Naan ippo building-la irundhu veliya varren, so driver-a oru minute wait panna sollunga.",
    ),
    (
        "Please tell the driver to stop near the yellow board on the left side.",
        "Left side-la irukkura yellow board pakkathula stop panna driver-kitta sollunga.",
    ),
    (
        "The driver is waiting near the wrong entrance, and I am walking toward him now.",
        "Driver wrong entrance pakkathula wait pannitu irukkaaru, naan ippo avara nokki nadandhu varen.",
    ),
    (
        "I can hear the driver, but I cannot see him because there are too many people around me.",
        "Driver pesuradhu kekkudhu, aana enna suthi romba per irukkuradhunaala avara paakka mudiyala.",
    ),
    (
        "Please ask the driver to stay where he is until I reach the vehicle.",
        "Naan vehicle-kitta varaikkum driver irukkura edathulaaye wait panna sollunga.",
    ),
    (
        "The map shows that the driver is nearby, but I cannot find the vehicle.",
        "Map-la driver pakkathula irukkaaru-nu kaamikudhu, aana vehicle-a kandupidikka mudiyala.",
    ),
    (
        "I think the driver has entered the wrong street.",
        "Driver thappana street-kulla poittaaru-nu ninaikkiren.",
    ),
    (
        "Please ask the driver to come back to the previous signal.",
        "Previous signal-kku thirumbi vara driver-kitta sollunga.",
    ),
    (
        "I am standing beside a red car near the main gate.",
        "Main gate pakkathula red car-oda pakkathula naan nikkiren.",
    ),
    (
        "Please tell the driver that I am wearing a black jacket and carrying a blue bag.",
        "Naan black jacket pottuttu blue bag eduthuttu irukken-nu driver-kitta sollunga.",
    ),
    (
        "The driver has called me twice, but I could not answer the phone.",
        "Driver rendu thadava enakku call pannaaru, aana ennaala phone attend panna mudiyala.",
    ),
    (
        "I will call the driver back once I finish speaking to the security guard.",
        "Security guard-kitta pesi mudichadhum driver-ku thirumbi call panren.",
    ),
    (
        "Please ask the driver whether he can wait for another ten minutes.",
        "Innum ten minutes wait panna mudiyuma-nu driver-kitta kelunga.",
    ),
    (
        "The driver says he has arrived, but I am still five minutes away.",
        "Driver vandhutaaraam, aana naan innum five minutes distance-la irukken.",
    ),
    (
        "I am almost at the pickup point, so please ask the driver not to leave.",
        "Naan pickup point-kku almost vandhuten, so driver-a poga vendam-nu sollunga.",
    ),
    (
        "The pickup location is crowded, so it may take me a few minutes to find the vehicle.",
        "Pickup location-la romba crowd irukku, so vehicle-a kandupidikka enakku konjam time aagalam.",
    ),
    (
        "Please tell the driver to wait beside the pharmacy instead of the supermarket.",
        "Supermarket pakkathula wait pannama pharmacy pakkathula wait panna driver-kitta sollunga.",
    ),
    (
        "I am standing exactly where the map shows the pickup location.",
        "Map-la pickup location kaamikura exact edathula dhaan naan nikkiren.",
    ),
    (
        "The driver is moving in the wrong direction again.",
        "Driver marubadiyum thappana direction-la poittu irukkaaru.",
    ),
    (
        "Please check the navigation and make sure we are going toward the correct destination.",
        "Navigation-a check panni naanga correct destination direction-la dhaan poromaa-nu confirm pannunga.",
    ),
    (
        "The road is completely blocked, so we will have to take a different route.",
        "Road full-ah block aagirukku, so naanga vera route-la dhaan poga vendiyadhu irukku.",
    ),
    (
        "Please ask the driver to avoid the road near the market because it is usually very crowded.",
        "Market pakkathula irukkura road-a avoid panna driver-kitta sollunga, anga usually romba crowd-ah irukkum.",
    ),
    (
        "I am in a hurry because I have an appointment in thirty minutes.",
        "Enakku thirty minutes-la appointment irukku, so naan konjam avasaram-ah irukken.",
    ),
    (
        "Please take the fastest route even if the distance is slightly longer.",
        "Distance konjam adhigama irundhaalum parava illa, fastest route-la ponga.",
    ),
    (
        "The estimated fare has increased since I started the ride.",
        "Ride start pannadhula irundhu estimated fare increase aagiduchu.",
    ),
    (
        "Please explain why the fare is different from the amount shown when I booked the ride.",
        "Naan ride book pannumbodhu kaamicha amount-um ippo irukkura fare-um yen different-ah irukku-nu explain pannunga.",
    ),
    (
        "I think I left my sunglasses somewhere inside the vehicle.",
        "En sunglasses-a vehicle-kulla engaavadhu vittuten-nu ninaikkiren.",
    ),
    (
        "Please ask the driver to check underneath the passenger seat.",
        "Passenger seat-keezha check panna driver-kitta sollunga.",
    ),
    (
        "I have already paid for the ride through the application.",
        "Naan already application moolama ride-ku payment panniten.",
    ),
    (
        "Please confirm whether the payment has been received successfully.",
        "Payment successful-ah receive aachaa-nu confirm pannunga.",
    ),
    (
        "The application is showing an error when I try to make the payment.",
        "Payment panna try pannumbodhu application-la error kaamikudhu.",
    ),
    (
        "Please wait while I try the payment again.",
        "Naan payment-a marubadiyum try panra varaikkum wait pannunga.",
    ),
    (
        "The driver has reached the destination, but I need help finding the exact entrance.",
        "Driver destination-ku vandhutaanga, aana exact entrance-a kandupidikka enakku help venum.",
    ),
    (
        "Please tell the driver that I need to get down near the main entrance.",
        "Enna main entrance pakkathula drop panna vendum-nu driver-kitta sollunga.",
    ),
    (
        "I have an elderly passenger with me, so please stop somewhere that is easy to access.",
        "En kooda oru elderly passenger irukkaaru, so easy-ah access panna mudiyura edathula stop pannunga.",
    ),
    (
        "Please drive carefully because the road is wet and slippery.",
        "Road wet-ahum slippery-ahum irukku, so careful-ah drive pannunga.",
    ),
    (
        "I am not comfortable taking this route because it is unfamiliar to me.",
        "Indha route enakku familiar illa, so indha vazhiya poga enakku comfortable-ah illa.",
    ),
    (
        "Please let me know when we are approximately five minutes away from the destination.",
        "Destination-ku approximately five minutes distance-la varumbodhu enakku sollunga.",
    ),
]


def main() -> None:
    assert len(PAIRS) == 110, len(PAIRS)
    rows = []
    for i, (en, ta) in enumerate(PAIRS, 1):
        if i <= 30:
            batch, local = "A", i
        elif i <= 70:
            batch, local = "B", i - 30
        else:
            batch, local = "C", i - 70
        rows.append(
            {
                "id": f"gold_{batch}_{local:02d}",
                "batch": batch,
                "english": en,
                "tanglish": ta,
                "category": "natural_tanglish_gold",
            }
        )

    for rel in (
        "normalization/tanglish_gold_pairs.json",
        "benchmark/data/tanglish_gold_pairs.json",
    ):
        path = ROOT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {path} ({len(rows)})")

    taxi_path = ROOT / "benchmark/data/taxi_driver_sentences.json"
    taxi = json.loads(taxi_path.read_text(encoding="utf-8"))
    existing = {(x.get("text") or "").strip().lower() for x in taxi}
    added = 0
    for r in rows:
        key = r["english"].strip().lower()
        if key in existing:
            continue
        taxi.append(
            {
                "text": r["english"],
                "category": "natural_tanglish_gold",
                "language_mix": "tanglish",
                "stress": ["gold_pair", "natural"],
                "tanglish_ref": r["tanglish"],
            }
        )
        existing.add(key)
        added += 1
    taxi_path.write_text(json.dumps(taxi, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"taxi added {added}; total {len(taxi)}")


if __name__ == "__main__":
    main()
