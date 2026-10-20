"""
ynotPi — core/dummy_data.py
---------------------------
Fake API data for dummy mode / dev mode (no keys or internet needed).

Every function returns the same shape as its real twin in api_manager.py,
so the slides can't tell the difference.
"""


# ─── WEATHER ───────────────────────────────────────────────────────────────────
def weather(city="Sydney"):
    return {
        "city": city,
        "temp": 22.4,
        "feels_like": 21.8,
        "description": "partly cloudy",
        "humidity": 58,
        "icon": "02d",
    }


# ─── CRYPTO ────────────────────────────────────────────────────────────────────
# (price, 24h change %) — made-up numbers, just for show
_PRICES = {
    "bitcoin": (98500.0, 1.8),
    "ethereum": (5200.0, -0.9),
    "solana": (310.0, 3.2),
    "dogecoin": (0.42, -2.1),
}


def crypto(coin_ids="bitcoin,ethereum", currency="aud"):
    # accept "bitcoin,ethereum" or ["bitcoin", "ethereum"]
    if isinstance(coin_ids, str):
        coins = [c.strip() for c in coin_ids.split(",") if c.strip()]
    else:
        coins = list(coin_ids)

    data = {}
    for coin in coins:
        price, change = _PRICES.get(coin, (100.0, 0.0))
        data[coin] = {
            currency: price,
            f"{currency}_24h_change": change,
        }
    return data


# ─── NEWS ──────────────────────────────────────────────────────────────────────
_HEADLINES = [
    ("Local council approves new Hunter River walking track", "Dummy News"),
    ("Newcastle tech meetup draws record crowd", "Dummy News"),
    ("Small businesses see growth in digital signage use", "Dummy Business"),
    ("Raspberry Pi projects keep getting more creative", "Dummy Tech"),
    ("Weekend forecast: sunshine with a light sea breeze", "Dummy Weather"),
    ("Cafe owners swap paper menus for screens", "Dummy Business"),
    ("University students team up with local IT providers", "Dummy Education"),
]


def news(page_size=5):
    articles = []
    for title, source in _HEADLINES[:page_size]:
        articles.append(
            {
                "title": title,
                "source": source,
                "url": "https://example.com/news",
                "published": "2026-10-20T09:00:00Z",
            }
        )
    return articles


# ─── NASA APOD ─────────────────────────────────────────────────────────────────
def apod():
    return {
        "title": "Dummy Nebula",
        "explanation": (
            "This is placeholder text standing in for NASA's Astronomy Picture "
            "of the Day. In dummy mode no real image is fetched."
        ),
        "url": "",
        "media_type": "image",
        "date": "2026-10-20",
    }


# ─── CUSTOM APIS ───────────────────────────────────────────────────────────────
def custom_apis(configs=None):
    """One fake result per config in apis.json (or one sample if there are none)."""
    results = []

    for config in configs or []:
        results.append(
            {
                "name": config.get("name", "Custom API"),
                "data": {"example": "dummy value", "number": 42},
                "source_url": config.get("url", ""),
            }
        )

    if not results:
        results.append(
            {
                "name": "Sample Custom API",
                "data": {"example": "dummy value", "number": 42},
                "source_url": "https://example.com/api",
            }
        )

    return results


# ─── TRIVIA ────────────────────────────────────────────────────────────────────
# same shape as Open Trivia DB "results" entries
_TRIVIA = [
    ("What is the capital of Australia?", "Canberra", ["Sydney", "Melbourne", "Perth"]),
    ("Which planet is closest to the Sun?", "Mercury", ["Venus", "Earth", "Mars"]),
    ("How many bits are in a byte?", "8", ["4", "16", "32"]),
    ("What does 'HTTP' stand for?", "HyperText Transfer Protocol",
     ["High Transfer Text Process", "Hyper Terminal Tool Protocol", "Host Transfer Type Path"]),
    ("Which language is the Raspberry Pi named to support?", "Python",
     ["Java", "Ruby", "Swift"]),
    ("What is the largest ocean on Earth?", "Pacific", ["Atlantic", "Indian", "Arctic"]),
    ("Who painted the Mona Lisa?", "Leonardo da Vinci", ["Michelangelo", "Raphael", "Donatello"]),
    ("What is the chemical symbol for gold?", "Au", ["Ag", "Gd", "Go"]),
]


def trivia():
    results = []
    for question, correct, wrong in _TRIVIA:
        results.append(
            {
                "type": "multiple",
                "difficulty": "easy",
                "category": "General Knowledge",
                "question": question,
                "correct_answer": correct,
                "incorrect_answers": wrong,
            }
        )
    return results
