from datetime import datetime, timezone

from extensions import db

LIFECYCLE_STATES = ("planned", "sown", "growing", "harvested", "removed")
AREA_TYPES = ("plot", "bed", "row", "greenhouse", "other")
CONTAINER_TYPES = ("pot", "box", "hanging-basket", "other")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Garden(db.Model):
    __tablename__ = "gardens"

    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    location_label = db.Column(db.String(255), nullable=False, default="")
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    climate_zone = db.Column(db.String(120), nullable=False, default="")
    map_width_m = db.Column(db.Float, nullable=False, default=10.0)
    map_height_m = db.Column(db.Float, nullable=False, default=10.0)
    created_at = db.Column(db.DateTime, default=_now)
    updated_at = db.Column(db.DateTime, default=_now, onupdate=_now)

    areas = db.relationship("GardenArea", backref="garden", cascade="all, delete-orphan")
    plantings = db.relationship("Planting", backref="garden", cascade="all, delete-orphan")
    chat_messages = db.relationship(
        "GardenChatMessage", backref="garden", cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "owner_id": self.owner_id,
            "name": self.name,
            "description": self.description,
            "location_label": self.location_label,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "climate_zone": self.climate_zone,
            "map_width_m": self.map_width_m,
            "map_height_m": self.map_height_m,
            "created_at": self.created_at.isoformat(),
        }


class GardenArea(db.Model):
    __tablename__ = "garden_areas"

    id = db.Column(db.Integer, primary_key=True)
    garden_id = db.Column(db.Integer, db.ForeignKey("gardens.id"), nullable=False, index=True)
    parent_area_id = db.Column(db.Integer, db.ForeignKey("garden_areas.id"), nullable=True, index=True)
    name = db.Column(db.String(120), nullable=False)
    area_type = db.Column(db.String(20), nullable=False, default="bed")
    pos_x = db.Column(db.Float, nullable=False, default=0.0)
    pos_y = db.Column(db.Float, nullable=False, default=0.0)
    width = db.Column(db.Float, nullable=False, default=1.0)
    length = db.Column(db.Float, nullable=False, default=1.0)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=_now)
    updated_at = db.Column(db.DateTime, default=_now, onupdate=_now)

    children = db.relationship("GardenArea", backref=db.backref("parent", remote_side=[id]))
    containers = db.relationship("Container", backref="garden_area", cascade="all, delete-orphan")
    planting_locations = db.relationship(
        "PlantingLocation", backref="garden_area", cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "garden_id": self.garden_id,
            "parent_area_id": self.parent_area_id,
            "name": self.name,
            "area_type": self.area_type,
            "pos_x": self.pos_x,
            "pos_y": self.pos_y,
            "width": self.width,
            "length": self.length,
            "notes": self.notes,
        }


class Container(db.Model):
    __tablename__ = "containers"

    id = db.Column(db.Integer, primary_key=True)
    garden_area_id = db.Column(db.Integer, db.ForeignKey("garden_areas.id"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    container_type = db.Column(db.String(20), nullable=False, default="pot")
    pos_x = db.Column(db.Float, nullable=False, default=0.0)
    pos_y = db.Column(db.Float, nullable=False, default=0.0)
    width = db.Column(db.Float, nullable=True)
    depth = db.Column(db.Float, nullable=True)
    height = db.Column(db.Float, nullable=True)
    volume_liters = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, default=_now)
    updated_at = db.Column(db.DateTime, default=_now, onupdate=_now)

    planting_locations = db.relationship(
        "PlantingLocation", backref="container", cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "garden_area_id": self.garden_area_id,
            "name": self.name,
            "container_type": self.container_type,
            "pos_x": self.pos_x,
            "pos_y": self.pos_y,
            "width": self.width,
            "depth": self.depth,
            "height": self.height,
            "volume_liters": self.volume_liters,
        }


class Planting(db.Model):
    __tablename__ = "plantings"

    id = db.Column(db.Integer, primary_key=True)
    garden_id = db.Column(db.Integer, db.ForeignKey("gardens.id"), nullable=False, index=True)
    # Amy's Crop Almanac isn't built yet - nullable until that service exists (see mock_almanac stage).
    crop_variety_id = db.Column(db.Integer, nullable=True)
    crop_name = db.Column(db.String(120), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    lifecycle_state = db.Column(db.String(20), nullable=False, default="planned")
    growth_stage = db.Column(db.String(60), nullable=True)
    planted_date = db.Column(db.Date, nullable=True)
    expected_harvest_date = db.Column(db.Date, nullable=True)
    actual_harvest_date = db.Column(db.Date, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=_now)
    updated_at = db.Column(db.DateTime, default=_now, onupdate=_now)

    location = db.relationship(
        "PlantingLocation", backref="planting", uselist=False, cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "garden_id": self.garden_id,
            "crop_variety_id": self.crop_variety_id,
            "crop_name": self.crop_name,
            "quantity": self.quantity,
            "lifecycle_state": self.lifecycle_state,
            "growth_stage": self.growth_stage,
            "planted_date": self.planted_date.isoformat() if self.planted_date else None,
            "expected_harvest_date": self.expected_harvest_date.isoformat()
            if self.expected_harvest_date
            else None,
            "actual_harvest_date": self.actual_harvest_date.isoformat()
            if self.actual_harvest_date
            else None,
            "notes": self.notes,
        }


class PlantingLocation(db.Model):
    __tablename__ = "planting_locations"
    __table_args__ = (
        db.CheckConstraint(
            "(garden_area_id IS NOT NULL) != (container_id IS NOT NULL)",
            name="exactly_one_of_area_or_container",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    planting_id = db.Column(db.Integer, db.ForeignKey("plantings.id"), nullable=False, unique=True)
    garden_area_id = db.Column(db.Integer, db.ForeignKey("garden_areas.id"), nullable=True, index=True)
    container_id = db.Column(db.Integer, db.ForeignKey("containers.id"), nullable=True, index=True)
    pos_x = db.Column(db.Float, nullable=False, default=0.0)
    pos_y = db.Column(db.Float, nullable=False, default=0.0)
    created_at = db.Column(db.DateTime, default=_now)
    updated_at = db.Column(db.DateTime, default=_now, onupdate=_now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "planting_id": self.planting_id,
            "garden_area_id": self.garden_area_id,
            "container_id": self.container_id,
            "pos_x": self.pos_x,
            "pos_y": self.pos_y,
        }


class GardenChatMessage(db.Model):
    """One saved message in a garden's AI conversation.

    Scoped by garden_id only - the routes that read/write these already enforce
    that the caller owns the garden.
    """

    __tablename__ = "garden_chat_messages"
    __table_args__ = (
        db.CheckConstraint("role IN ('user', 'assistant')", name="ck_garden_chat_message_role"),
    )

    id = db.Column(db.Integer, primary_key=True)
    garden_id = db.Column(
        db.Integer, db.ForeignKey("gardens.id"), nullable=False, index=True
    )
    role = db.Column(db.String(16), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=_now, nullable=False)
