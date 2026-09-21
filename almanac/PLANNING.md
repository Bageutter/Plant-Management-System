# Plant growing knowledge

The Almanac now stores measurable yield, two-dimensional spacing, succession and harvest windows; soil preferences; linked pests and diseases; food-forest functions and guild suggestions; uses; and eight consistent rotation groups. Nutrition and garden-owned rotation sequences/history remain future work.

## Run and seed

From the repository root, install the Almanac requirements into your environment. Existing installations must retain their database and uploaded images; back them up before upgrading.

```sh
python -m pip install -r almanac/requirements-dev.txt
PYTHONPATH=almanac python -m flask --app app refresh-garden
PYTHONPATH=almanac python -m flask --app app run --port 5513
```

`DATABASE_URL` chooses the database (SQLite by default; PostgreSQL requires a matching driver, such as psycopg, installed in the deployment environment). The application applies Alembic migrations at startup. Start one instance to complete migrations before bringing up additional workers. Existing unversioned databases are adopted at baseline 001; revision 002 adds nullable fields and linked tables; revision 003 maps optional legacy rotation wording. No database reset is required. Downgrades intentionally require restoring a backup, rather than silently deleting plant knowledge.

For Docker, rebuild the Almanac image and run the optional garden refresh inside that service:

```sh
docker compose up -d --build almanac
docker compose exec almanac python -m flask --app app refresh-garden
```

`refresh-garden` updates legacy demo wording and adds starter companion links while retaining existing link notes. It runs only when explicitly invoked, so removed suggestions stay removed during normal browsing.

### Optional public starter dataset

Docker Compose enables `LOAD_MY_GARDEN_SEED=true` for local development. On the
first start of a brand-new Almanac database, the service downloads the public
[`0melette/my_garden`](https://github.com/0melette/my_garden) catalogue snapshot
and copies its plants, planting months, pests, diseases, functions, uses, and
companion relationships into the local database. Application edits never write
back to the public repository, and later restarts never re-import or overwrite
an existing catalogue.

Set `LOAD_MY_GARDEN_SEED=false` to use only the eight built-in starter plants.
`MY_GARDEN_SEED_URL` can point to a specific commit or release for reproducible
development. If the public snapshot cannot be reached during a fresh start, the
service logs a warning and falls back to the eight built-in plants.

## Use it

1. Open the Almanac and choose **Lettuce** (direct preview: `/plants/lettuce`).
2. Browse recorded growing information, soil preferences and companion suggestions.
3. Sign in through the existing Auth service and choose **Edit**. Update growing facts; yield quantity and unit must be entered together. Save.
4. In the same form, select soil/water/sun preferences, one forest layer, multiple garden functions and uses, a part used and a rotation group. Enter comma-separated pest/disease names; these become shared linked records.
5. On a plant detail page, select a companion plant and a garden function in **Guild suggestions**. Save notes, or remove the matching plant/function suggestion. Links are directional; reverse relationships must be added separately.
6. Hover, focus or tap a **?** beside a field to read a short explanation. Press Escape or click outside to dismiss it. Rotation guidance explains where to plant next; sowing notes appear under **When to Plant**.

Harvest-to-space planning is outside this Almanac's scope. The calculator UI and endpoint have been removed. Existing yield, spacing and harvest-window records remain descriptive growing knowledge; no saved data or migrations were dropped. Recorded values are not guarantees of yield or continuous supply.

## Rotation boundary

Alliums, Brassicas, Cucurbits, Legumes, Roots, Solanums, Anywhere and Perennials are seeded lookup records. Anywhere and Perennials are rotation-exempt. Feeder weights are defaults for planning, not measured species nutrition. The user's group classification is retained (including radish in Anywhere); this is not a guarantee against family-specific disease carry-over.

Current main had no free-text rotation field or companion-link model. The migration supports an optional legacy `rotation_group` column: known singular/plural values map to the lookup, while unknown text remains available for manual review. This change adds directional function-tagged companion links.

My Gardens should own `RotationSequence`, steps, spring/autumn restart and bed history. A future step should support several group assignments, with seasonal ordering, so combining groups and cool/warm double-cropping are representable. Those tables and garden UI are deliberately outside this Almanac PR.

## API and validation

`GET /api/plants/<slug>` includes the new fields, linked names, rotation metadata and guild links. It does not derive planting density or target-based space requirements. Authenticated POST/PUT/PATCH accept numeric fields and choice strings; `pests`, `diseases`, `uses`, and `function_tags` accept JSON lists. PATCH preserves omitted values. Empty optional values clear them; yield quantity/unit must be cleared together.

Validation rejects non-finite or non-positive planning numbers, fractional succession days, invalid vocabulary, missing yield units, reversed pH ranges and pH outside 0–14. Database checks and foreign keys also protect persisted records.

```sh
PYTHONPATH=almanac python -m pytest almanac/tests -q
ruff check .
```

Migration tests cover a populated legacy SQLite database, including an image, planting month and legacy rotation text. PostgreSQL support is based on portable SQLAlchemy/Alembic operations; a live PostgreSQL run is not part of this verification.
