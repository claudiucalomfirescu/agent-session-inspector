"""Static reference data: BMW models, colours, parts catalogue, recalls, bulletins, name lists."""

# model_code, series, name, fuel, body, base_price (retail GBP), lead_time_weeks
MODELS = [
    ("F70-120", "1 Series", "BMW 120 Sport", "petrol", "hatchback", 32_400, 8),
    ("F74-220", "2 Series", "BMW 220 Gran Coupe M Sport", "petrol", "saloon", 35_900, 9),
    ("G20-320I", "3 Series", "BMW 320i M Sport Saloon", "petrol", "saloon", 41_800, 10),
    ("G20-330E", "3 Series", "BMW 330e M Sport Saloon", "hybrid", "saloon", 46_900, 10),
    ("G21-320D", "3 Series", "BMW 320d M Sport Touring", "diesel", "estate", 44_300, 10),
    ("G22-420I", "4 Series", "BMW 420i M Sport Coupe", "petrol", "coupe", 46_200, 11),
    ("G26-I4E35", "i4", "BMW i4 eDrive35 M Sport", "electric", "gran coupe", 52_900, 9),
    ("G60-520I", "5 Series", "BMW 520i M Sport", "petrol", "saloon", 53_300, 11),
    ("G60-I5E40", "i5", "BMW i5 eDrive40 M Sport", "electric", "saloon", 69_900, 12),
    ("U11-X1-20I", "X1", "BMW X1 sDrive20i M Sport", "petrol", "suv", 38_600, 8),
    ("U11-IX1-E20", "iX1", "BMW iX1 eDrive20 M Sport", "electric", "suv", 46_800, 9),
    ("G45-X3-20", "X3", "BMW X3 20 xDrive M Sport", "petrol", "suv", 51_400, 10),
    ("G45-X3-30E", "X3", "BMW X3 30e xDrive M Sport", "hybrid", "suv", 58_900, 10),
    ("G05-X5-50E", "X5", "BMW X5 xDrive50e M Sport", "hybrid", "suv", 79_500, 14),
    ("I20-IX-45", "iX", "BMW iX xDrive45 M Sport", "electric", "suv", 76_400, 13),
    ("G80-M3C", "M3", "BMW M3 Competition", "petrol", "saloon", 86_800, 16),
    ("G82-M4C", "M4", "BMW M4 Competition Coupe", "petrol", "coupe", 87_900, 16),
    ("G07-X7-40D", "X7", "BMW X7 xDrive40d M Sport", "diesel", "suv", 98_600, 16),
]
MODEL_WEIGHTS = [8, 4, 9, 6, 6, 4, 6, 5, 3, 10, 6, 10, 6, 3, 3, 2, 2, 1]
DEALER_MARGIN = 0.09   # dealer cost = retail price less VAT, less 9% margin


def dealer_cost(retail_price):
    """What BMW invoices the dealer (ex VAT). Retail prices include 20% VAT."""
    return round(retail_price / 1.2 * (1 - DEALER_MARGIN), 2)

COLOURS = ["Alpine White", "Black Sapphire", "Brooklyn Grey", "Portimao Blue", "Skyscraper Grey",
           "Mineral White", "Carbon Black", "Dravit Grey", "Fire Red", "Frozen Deep Grey"]
OPTIONS = ["Technology Pack", "Comfort Pack", "Panoramic sunroof", "Harman Kardon sound", "M Sport Pro Pack",
           "Heated steering wheel", "19in M alloys", "Driving Assistant Professional", "Parking Assistant Plus"]

# Service parts: (key, description, category, fits, dealer price, retail price, reorder level)
# 'fits' groups: ALL, PETROL, DIESEL, EV, HYBRID or a chassis code.
PARTS = [
    ("oil-ll04", "Engine oil BMW Twinpower 0W-30 LL-04, 1L", "service", "PETROL DIESEL HYBRID", 9.80, 16.50, 60),
    ("oil-ll17", "Engine oil BMW Twinpower 0W-20 LL-17, 1L", "service", "PETROL HYBRID", 10.40, 17.90, 40),
    ("oilfilter-b48", "Oil filter element B48/B46 4-cyl petrol", "service", "PETROL HYBRID", 8.20, 14.90, 20),
    ("oilfilter-b47", "Oil filter element B47 4-cyl diesel", "service", "DIESEL", 8.60, 15.40, 12),
    ("oilfilter-b58", "Oil filter element B58/S58 6-cyl", "service", "G80 G82 G07 G05", 9.90, 17.80, 8),
    ("airfilter-4", "Air filter element 4-cyl", "service", "PETROL DIESEL HYBRID", 18.70, 32.50, 10),
    ("cabin-filter", "Microfilter / cabin filter activated carbon", "service", "ALL", 24.10, 41.90, 16),
    ("cabin-filter-ix", "Cabin filter set iX (2 pcs)", "service", "I20", 48.20, 84.00, 4),
    ("spark-plug", "Spark plug high power", "service", "PETROL", 11.30, 19.80, 24),
    ("brake-fluid", "Brake fluid DOT4 LV 1L", "service", "ALL", 9.10, 16.20, 16),
    ("wiper-set", "Wiper blade set front", "service", "ALL", 29.50, 49.90, 10),
    ("adblue", "AdBlue 10L", "service", "DIESEL", 11.00, 22.00, 10),
    ("coolant-ev", "Coolant HV battery circuit 1.5L", "ev", "EV HYBRID", 21.80, 38.40, 6),
    ("pads-front-s", "Brake pads front set (small brake)", "brakes", "F70 F74 U11", 62.40, 109.00, 6),
    ("pads-front-m", "Brake pads front set (M Sport brake)", "brakes", "G20 G21 G22 G26 G60 G45", 88.90, 156.00, 8),
    ("pads-front-l", "Brake pads front set (large SUV)", "brakes", "G05 G07 I20", 112.60, 198.00, 4),
    ("pads-rear-m", "Brake pads rear set", "brakes", "G20 G21 G22 G26 G60 G45 U11 F70 F74", 58.30, 102.00, 8),
    ("discs-front-m", "Brake disc front ventilated (each)", "brakes", "G20 G21 G22 G26 G60 G45", 96.40, 169.00, 4),
    ("discs-rear-m", "Brake disc rear (each)", "brakes", "G20 G21 G22 G26 G60 G45 U11", 71.80, 126.00, 4),
    ("pad-sensor", "Brake pad wear sensor", "brakes", "ALL", 12.20, 21.50, 12),
    ("battery-12v-70", "12V AGM battery 70Ah", "electrical", "ALL", 168.00, 289.00, 3),
    ("battery-12v-90", "12V AGM battery 90Ah", "electrical", "G05 G07 G60 I20", 214.00, 365.00, 2),
    ("tpms", "Tyre pressure sensor (RDC)", "tyres", "ALL", 54.60, 94.00, 8),
    ("tyre-225-45r18", "Tyre 225/45 R18 run-flat star-marked", "tyres", "G20 G21 G22 F74", 142.00, 219.00, 8),
    ("tyre-245-45r19", "Tyre 245/45 R19 run-flat star-marked", "tyres", "G45 G60 G26", 176.00, 268.00, 8),
    ("tyre-255-50r20", "Tyre 255/50 R20 star-marked", "tyres", "G05 G07 I20", 228.00, 339.00, 4),
    ("tyre-225-55r17", "Tyre 225/55 R17 star-marked", "tyres", "U11 F70", 118.00, 182.00, 8),
    ("key-battery", "Key fob battery CR2032", "electrical", "ALL", 1.80, 6.00, 20),
    ("hv-contactor", "HV battery contactor unit", "ev", "EV", 412.00, 689.00, 0),
    ("charge-flap", "Charging flap actuator", "ev", "EV HYBRID", 88.00, 149.00, 1),
    ("onboard-charger-fuse", "On-board charger fuse kit", "ev", "EV HYBRID", 34.00, 59.00, 2),
    ("pdc-sensor", "Park distance control sensor", "electrical", "ALL", 72.30, 124.00, 4),
    ("wheel-bolt", "Wheel bolt (each)", "tyres", "ALL", 3.40, 6.90, 40),
    ("thermostat-b47", "Thermostat B47", "engine", "DIESEL", 96.00, 168.00, 1),
    ("water-pump-b48", "Electric water pump B48", "engine", "PETROL HYBRID", 388.00, 649.00, 1),
    ("egr-cooler-b47", "EGR cooler B47", "engine", "DIESEL", 324.00, 548.00, 0),
    ("ignition-coil", "Ignition coil", "engine", "PETROL HYBRID", 58.00, 99.00, 4),
    ("aux-belt", "Auxiliary drive belt", "engine", "PETROL DIESEL HYBRID", 31.00, 54.00, 3),
    ("washer-fluid", "Screenwash concentrate 1L", "service", "ALL", 3.10, 7.50, 24),
    ("headlamp-led", "LED headlight module", "electrical", "G20 G21 G22", 642.00, 1099.00, 0),
]

FIRST = ["Oliver", "Amelia", "George", "Isla", "Harry", "Ava", "Jack", "Mia", "Noah", "Grace", "Leo", "Freya",
         "Arthur", "Sophie", "Charlie", "Emily", "Henry", "Lily", "Thomas", "Ella", "James", "Chloe", "William",
         "Olivia", "Mohammed", "Aisha", "Raj", "Priya", "Arjun", "Ananya", "Wei", "Mei", "Kwame", "Ama",
         "Tomasz", "Zofia", "Andrei", "Ioana", "Luca", "Giulia", "Sean", "Niamh", "Daniel", "Hannah", "Ben",
         "Rachel", "Samuel", "Laura", "David", "Sarah", "Michael", "Kate", "Omar", "Fatima", "Yusuf", "Zara",
         "Hiroshi", "Yuki", "Carlos", "Lucia", "Ethan", "Ruby", "Max", "Evie", "Adam", "Holly", "Ryan", "Jess"]
LAST = ["Smith", "Jones", "Taylor", "Brown", "Williams", "Wilson", "Johnson", "Davies", "Robinson", "Wright",
        "Thompson", "Evans", "Walker", "White", "Roberts", "Green", "Hall", "Wood", "Jackson", "Clarke",
        "Patel", "Khan", "Shah", "Ali", "Singh", "Chen", "Wang", "Mensah", "Owusu", "Kowalski", "Nowak",
        "Popa", "Ionescu", "Rossi", "Murphy", "O'Brien", "Hughes", "Edwards", "Turner", "Hill", "Cooper",
        "Ward", "Morris", "King", "Baker", "Harris", "Lewis", "Carter", "Mitchell", "Tanaka", "Garcia",
        "Hussain", "Ahmed", "Begum", "Fraser", "Campbell", "Stewart", "Kaur", "Gill", "Okoro"]
TOWNS = [("Reading", "RG1"), ("Reading", "RG2"), ("Reading", "RG4"), ("Earley", "RG6"), ("Tilehurst", "RG31"),
         ("Wokingham", "RG40"), ("Wokingham", "RG41"), ("Bracknell", "RG12"), ("Bracknell", "RG42"),
         ("Newbury", "RG14"), ("Thatcham", "RG18"), ("Henley-on-Thames", "RG9"), ("Twyford", "RG10"),
         ("Maidenhead", "SL6"), ("Crowthorne", "RG45")]
EMAIL_DOMAINS = ["mail.example", "inbox.example", "post.example", "web.example"]

RECALLS = [
    ("RC-0061260100", "Front passenger airbag inflator inspection", "G20 G21 G22",
     "Inspect inflator batch number; replace module if affected", 1.2, "2026-02-09"),
    ("RC-0061260210", "High-voltage battery cell module software update", "I20 G26 U11",
     "Flash BMS software to I-level 26-03-540 and run insulation test", 0.8, "2026-04-14"),
    ("RC-0061260377", "Integrated starter-generator wiring harness clip", "G45 G05",
     "Fit additional retaining clip to ISG harness", 0.6, "2026-07-21"),
]
BULLETINS = [
    ("SIB-12-04-26", "Intermittent 12V battery drain from telematics unit", "G20 G21 G60",
     "Battery warning after long standing; vehicle does not wake", "Update TCB software via ISTA; recode", "2026-03-02"),
    ("SIB-61-11-26", "Charging stops at 80% on public AC chargers", "I20 G26 U11",
     "AC charge interrupted, customer complaint", "Update CCU and reset charge profile", "2026-05-18"),
    ("SIB-34-07-26", "Brake squeal at low speed, front axle M Sport brake", "G20 G22 G26",
     "Squeal under light braking below 10 mph", "Fit revised pads 34 10 8 845 112 and apply anti-squeal paste", "2026-06-10"),
    ("SIB-17-02-26", "Coolant smell from HV heater", "I20",
     "Sweet smell in cabin after pre-conditioning", "Replace HV heater seal kit", "2026-09-01"),
]
