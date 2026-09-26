"""Typed Jev decisions. No text generation or inferred numeric listing fields."""
import json
import math
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
QUESTIONS = {
    "pets": {"type": "choice", "instructions": "What does the listing explicitly say about keeping a cat? Do not infer permission from silence.",
             "criteria": {"allowed": "Explicitly permits cats or pets", "forbidden": "Explicitly rules out cats or pets", "conditional": "Permission is conditional or must be discussed", "unspecified": "No usable pet policy stated"}},
    "workspace": {"type": "choice", "instructions": "Is there explicit evidence of a separate usable workspace for video calls? A room count alone is insufficient.",
                  "criteria": {"dedicated": "Office or separately usable working room stated", "possible": "Desk nook or workspace stated, but privacy unclear", "unspecified": "No workspace evidence", "unsuitable": "Explicitly says shared/open layout without private workspace"}},
    "noise": {"type": "choice", "instructions": "Classify claims about quietness or noise, relying on explicit text, not location stereotypes.",
              "criteria": {"quiet_claim": "Explicit quietness or sound insulation claim", "noise_warning": "Explicit noise, traffic or construction warning", "mixed": "Both quiet and noisy clues stated", "unspecified": "No relevant evidence"}},
    "balcony": {"type": "choice", "instructions": "Does the text explicitly describe outdoor space? Do not infer cat safety from a balcony.",
                "criteria": {"private": "Private balcony, terrace or garden stated", "shared": "Only common or shared outdoor space stated", "none": "Explicitly no outdoor space", "unspecified": "Not clear or not mentioned"}},
    "fine_print": {"type": "noul", "instructions": "Does the listing explicitly contain a rental restriction or extra cost that a renter should check, such as commission, deposit, minimum term, no pets, or additional utility charges?"},
    "agency_fee": {"type": "noul", "instructions": "Does the text explicitly state an agency commission or brokerage fee payable by the renter?"},
    "parking_included": {"type": "noul", "instructions": "Does the text explicitly state a parking place is included in the listed price, rather than merely available?"},
    "utilities_extra": {"type": "noul", "instructions": "Does the text explicitly state utilities, maintenance, or another recurring cost are charged on top of the listed price?"},
}


def payload(listing, model="jev-latest"):
    # No seller contact data, images, exact street or coordinates leave the machine.
    state = {k: listing.get(k) for k in ("title", "description", "features", "amenities", "building", "floor", "rooms", "area_sqm", "transaction", "price")}
    state["description"] = (state.get("description") or "")[:12000]
    return {"model": model, "state": state, "questions": QUESTIONS}


def parse_answer(data):
    answers = data.get("answers")
    if not isinstance(answers, dict):
        raise ValueError("Jev response has no answers map")
    result = {}
    for key, question in QUESTIONS.items():
        answer = answers.get(key)
        if not isinstance(answer, dict) or answer.get("type") != question["type"]:
            raise ValueError(f"Jev response missing {key} answer")
        if question["type"] == "choice":
            choice = answer.get("choice")
            probs = answer.get("probabilities")
            if choice not in question["criteria"] or not isinstance(probs, dict):
                raise ValueError(f"Invalid Jev choice for {key}")
            probability = probs.get(choice)
            if not isinstance(probability, (int, float)) or not math.isfinite(probability) or not 0 <= probability <= 1:
                raise ValueError(f"Invalid Jev probability for {key}")
            result[key] = {"value": choice if probability >= 0.72 else "review", "candidate": choice, "probability": probability}
        else:
            value = answer.get("noul")
            if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"Invalid Jev noul for {key}")
            result[key] = {"value": "yes" if value >= 0.8 else "no" if value <= 0.2 else "review", "probability": value}
    return {"model": data.get("model"), "signals": result, "usage": data.get("usage")}


def evaluate(listing, api_key, model="jev-latest"):
    body = json.dumps(payload(listing, model), ensure_ascii=False).encode("utf-8")
    req = Request(ENDPOINT, data=body, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(req, timeout=30) as response:
            data = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"Jev HTTP {exc.code}; check key, quota, or request schema") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"Jev request failed: {exc}") from exc
    return parse_answer(data)
