"""Catalogue browsing uses stored labels, not guesses from plant names."""


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
            "selected_category": category, "categories": categories, "group_by": group_by}
