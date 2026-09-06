# Plant planning and growing knowledge

The Almanac now stores measurable yield, two-dimensional spacing, succession and harvest windows; soil preferences; linked pests and diseases; food-forest functions and guild suggestions; uses; and eight consistent rotation groups. Nutrition and garden-owned rotation sequences/history remain future work.

## Run and seed

From the repository root, install the Almanac requirements into your environment. Existing installations must retain their database and uploaded images; back them up before upgrading.

```sh
python -m pip install -r almanac/requirements-dev.txt
PYTHONPATH=almanac python -m flask --app app import-notion
PYTHONPATH=almanac python -m flask --app app seed-estimates
PYTHONPATH=almanac python -m flask --app app refresh-garden
PYTHONPATH=almanac python -m flask --app app run --port 5513
```

`DATABASE_URL` chooses the database (SQLite by default; PostgreSQL requires a matching driver, such as psycopg, installed in the deployment environment). The application applies Alembic migrations at startup. Start one instance to complete migrations before bringing up additional workers. Existing unversioned databases are adopted at baseline 001; revision 002 adds nullable fields and linked tables; revision 003 records estimate provenance and maps optional legacy rotation wording. No database reset is required. Downgrades intentionally require restoring a backup, rather than silently deleting plant knowledge.

For Docker, rebuild the Almanac image and run the three seed commands inside that service:

```sh
docker compose up -d --build almanac
docker compose exec almanac python -m flask --app app import-notion
docker compose exec almanac python -m flask --app app seed-estimates
docker compose exec almanac python -m flask --app app refresh-garden
```

The seed commands are repeatable. `refresh-garden` cleans imported/estimated wording and adds starter companion links; it retains existing link notes. It runs only when explicitly invoked, so removed suggestions stay removed during normal browsing. The source snapshot contains 27 Notion plants; against the standard eight-plant seed it adds 26 and links Lettuce, resulting in 34 records. Existing descriptions, planting months and images remain intact. New sowing timing is retained verbatim in source notes rather than converting ambiguous seasonal wording into exact months.

## Use it

1. Open the Almanac and choose **Lettuce** (direct preview: `/plants/lettuce`).
2. Enter **10** and unit **head**, then **Calculate**. The seeded assumptions return **10 plants** and **0.90 m²**, at 30 × 30 cm spacing.
3. Sign in through the existing Auth service and choose **Edit**. Update yield quantity and unit together, both spacings, succession days and harvest weeks. Save.
4. In the same form, select soil/water/sun preferences, one forest layer, multiple garden functions and uses, a part used and a rotation group. Enter comma-separated pest/disease names; these become shared linked records.
5. On a plant detail page, select a companion plant and a garden function in **Guild suggestions**. Save notes, or remove the matching plant/function suggestion. Links are directional; reverse relationships must be added separately.
6. Hover, focus or tap a **?** beside a field to read a short explanation. Press Escape or click outside to dismiss it. Rotation guidance explains where to plant next; sowing notes appear under **When to Plant**.

The calculator rounds `target / yield per plant` upward. Growing area is `plants × in-row cm × row cm / 10,000`. Target and recorded units must match; there is no hidden kg/g or fruit/kg conversion. A harvest window means the entire stated production period, not a yield at every picking. A head/root crop yields once. The result excludes paths, germination losses, immature plants, pollination block geometry and seasonal gaps; succession reminders do not promise continuous supply.

## AI estimates and sources

`data/notion_plants.json` is the selected plant-reference snapshot retrieved on 6 September 2026 from [the user's Notion catalogue](https://app.notion.com/p/3b7a295fe2fa80f08eddca230fe369ba). It omits inventory, prices, personal planting records and expiring image URLs. Synthetic/demo wording in the source is preserved.

`data/ai_estimates.json` contains AI-authored home-garden assumptions, requested by the user, for missing fields. They are not measured yields or Notion facts. `estimated_fields` records their origin in the API, while the app presents garden-facing wording without source links or AI badges. Re-running does not overwrite edits or refill deliberately cleared estimated values. Internal provenance remains after editing; it is not shown in plant forms or detail pages. Uncertain tree yields, traditional medicinal uses and unsubstantiated garden functions remain blank. Lily-of-the-valley identity is explicitly an assumption with an ornamental/poisonous note, never culinary.

The general approach is consistent with [RHS successional sowing](https://www.rhs.org.uk/vegetables/successional-sowing) and [RHS rotation guidance](https://www.rhs.org.uk/vegetables/crop-rotation); individual JSON numbers are AI estimates, not extracted from those references. Regional conditions and cultivars need review.

## Rotation boundary

Alliums, Brassicas, Cucurbits, Legumes, Roots, Solanums, Anywhere and Perennials are seeded lookup records. Anywhere and Perennials are rotation-exempt. Feeder weights are defaults for planning, not measured species nutrition. The user's group classification is retained (including radish in Anywhere); this is not a guarantee against family-specific disease carry-over.

Current main had no free-text rotation field or companion-link model. The migration supports an optional legacy `rotation_group` column: known singular/plural values map to the lookup, while unknown text remains available for manual review. This change adds directional function-tagged companion links.

My Gardens should own `RotationSequence`, steps, spring/autumn restart and bed history. A future step should support several group assignments, with seasonal ordering, so combining groups and cool/warm double-cropping are representable. Those tables and garden UI are deliberately outside this Almanac PR.

## API and validation

`GET /api/plants/<slug>` includes the new fields, linked names, rotation metadata, guild links, density and estimated-field provenance. Authenticated POST/PUT/PATCH accept numeric fields and choice strings; `pests`, `diseases`, `uses`, and `function_tags` accept JSON lists. PATCH preserves omitted values. Empty optional values clear them; yield quantity/unit must be cleared together.

Validation rejects non-finite or non-positive planning numbers, fractional succession days, invalid vocabulary, missing yield units, reversed pH ranges and pH outside 0–14. Database checks and foreign keys also protect persisted records.

```sh
PYTHONPATH=almanac python -m pytest almanac/tests -q
ruff check .
```

Migration tests cover a populated legacy SQLite database, including an image, planting month and legacy rotation text. PostgreSQL support is based on portable SQLAlchemy/Alembic operations; a live PostgreSQL run is not part of this verification.
