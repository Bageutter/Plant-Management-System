# AI review 2: Virtual Garden

| Date | Author | Proposer | Reviewer | Files changed |
|---|---|---|---|---|
| 2026-09-01 13:20:53 UTC | amy z | qwen3:4b-instruct | llama3.1:8b | No |

## Stage log

| Stage | Result |
|---|---|
| PLAN | Reviewed 11 repository files |
| ACT | Missing Error Handling in Garden Creation |
| OBSERVE | revise |
| ADAPT | rejected |

## Files reviewed

| # | File |
|---|---|
| 1 | `vgarden/app.py` |
| 2 | `vgarden/config.py` |
| 3 | `vgarden/extensions.py` |
| 4 | `vgarden/models.py` |
| 5 | `vgarden/requirements.txt` |
| 6 | `vgarden/routes.py` |
| 7 | `vgarden/templates/base.html` |
| 8 | `vgarden/templates/garden_not_found.html` |
| 9 | `vgarden/templates/garden_view.html` |
| 10 | `docker-compose.yml` |
| 11 | `AGENTS.md` |

## Missing Error Handling in Garden Creation

The create_garden endpoint does not validate that the owner_id is a valid user ID that exists in the database, leaving the possibility of creating gardens with non-existent owners.

Add a database query to verify that the provided owner_id exists in the users table before creating a garden, ensuring data consistency and preventing invalid garden ownership.

## Evidence

| File | Observation |
|---|---|
| `vgarden/routes.py` | The create_garden route validates owner_id and name types but does not check whether the owner_id corresponds to an actual user in the database. |

## Recommended changes

| File | Recommendation |
|---|---|
| `vgarden/routes.py` | Add a query to check if the owner_id exists in the users table before creating a garden, and return an error if it does not. |
| `vgarden/models.py` | Ensure a User model exists and is referenced in the Garden model, or clarify that ownership is a separate concern that requires a user model. |

## Independent review

The recommendation to add a database query to verify owner_id exists in the users table before creating a garden is partially supported, but it lacks evidence that this query will not impact performance.
- The create_garden endpoint does not validate that the owner_id is a valid user ID that exists in the database, leaving the possibility of creating gardens with non-existent owners. This is supported by the observation in vgarden/routes.py.
- However, the recommendation to add a database query to verify owner_id exists in the users table before creating a garden assumes that this query will not impact performance, which is unsupported by the evidence provided.

## Human outcome

| Outcome | Note |
|---|---|
| rejected | Virtual Garden does not own the users table. User validation belongs in Auth, or must use an Auth API. Direct database access would incorrectly couple the services. |
