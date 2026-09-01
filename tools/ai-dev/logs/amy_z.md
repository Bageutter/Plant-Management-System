# AI review index: amy z

| ID | Scope | Author | File | Change | Status | Notes | Full report |
|---|---|---|---|---|---|---|---|
| 1 | Virtual Garden | amy z | [`vgarden/routes.py`](../../../vgarden/routes.py)<br>[`vgarden/models.py`](../../../vgarden/models.py) | Add a database query to verify that the provided owner_id exists in the users table before creating a garden, ensuring data consistency and preventing invalid garden ownership. | rejected | Virtual Garden does not own the users table. User validation belongs in Auth, or must use an Auth API. Direct database access would incorrectly couple the services. | [Open](reports/amy_z/0002-virtual-garden.md) |
