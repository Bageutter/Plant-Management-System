"""Catalogue browsing uses stored labels, not guesses from plant names."""

from datetime import datetime
from zoneinfo import ZoneInfo
import calendar

def catalogue_view(plants, args):
    query = args.get("q", "").strip()[:200]
    category = args.get("category", "")
    categories = sorted({p.get("plant_category") or "Other" for p in plants})
    if category not in categories:
        category = ""
    group_by = "none" if args.get("group") == "none" else "plant"
    visible = [p for p in plants if (
        not category or (p.get("plant_category") or "Other") == category
    ) and query.casefold() in " ".join(str(p.get(k) or "") for k in (
        "common_name", "scientific_name", "plant_group", "variety_name", "summary"
    )).casefold()]
    sun_options = sorted({p.get("sun_needs") for p in plants if p.get("sun_needs")})
    water_options = sorted({p.get("water_needs") for p in plants if p.get("water_needs")})
    sun = args.get("sun", "")
    water = args.get("water", "")
    if sun not in sun_options: sun = ""
    if water not in water_options: water = ""
    month = args.get("month", "")
    if month == "now":
        month_number = datetime.now(ZoneInfo("Australia/Sydney")).month
    elif month.isdigit() and 1 <= int(month) <= 12:
        month_number = int(month)
    else:
        month, month_number = "", None
    visible = [p for p in visible if
               (not sun or p.get("sun_needs") == sun) and
               (not water or p.get("water_needs") == water) and
               (not month_number or any(str(m).lower() in {
                   str(month_number), calendar.month_name[month_number].lower(),
                   calendar.month_abbr[month_number].lower()
               } for m in p.get("planting_months", [])))]
    groups = {}
    for p in visible:
        name = p.get("plant_group") or p["common_name"]
        groups.setdefault(name, []).append(p)
    result = []
    for name, members in sorted(groups.items(), key=lambda pair: pair[0].casefold()):
        members.sort(key=lambda p: (bool(p.get("variety_name")), p["common_name"].casefold()))
        # Only reuse an actual generic record's summary. Do not invent group copy.
        generic = next((p for p in members if not p.get("variety_name")
                        and p["common_name"].casefold() == name.casefold()), None)
        if generic:
            members = [generic] + [p for p in members if p is not generic]
        result.append({"name": name, "plants": members,
                       "summary": generic["summary"] if generic else None,
                       "variety_count": sum(bool(p.get("variety_name")) for p in members)})
    return {"visible_plants": visible, "plant_groups": result, "query": query,
            "selected_category": category, "categories": categories, "group_by": group_by,
            "sun_options": sun_options, "water_options": water_options,
            "selected_sun": sun, "selected_water": water, "selected_month": month,
            "month_options": list(enumerate(calendar.month_name))[1:]}
