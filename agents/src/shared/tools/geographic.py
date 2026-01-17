"""Geographic tools using PostGIS and AWS Location Service."""

# asyncio import removed
import json
from typing import Any
from uuid import UUID

import boto3
from strands import tool

from ..config import get_settings
from ..database import execute_command, execute_one, execute_query, run_async


def _get_location_client():
    """Get AWS Location Service client."""
    settings = get_settings()
    return boto3.client("location", region_name=settings.aws_region)


@tool
def geocode_address(address: str) -> dict[str, Any]:
    """Convert an address to geographic coordinates.

    Use this tool to get latitude/longitude coordinates for an address.
    Uses AWS Location Service for geocoding.

    Args:
        address: The address to geocode (street, city, state, zip, etc.).

    Returns:
        Dictionary with coordinates and normalized address components.
    """
    settings = get_settings()
    client = _get_location_client()

    try:
        response = client.search_place_index_for_text(
            IndexName=settings.location_place_index,
            Text=address,
            MaxResults=1,
        )

        if not response.get("Results"):
            return {
                "status": "error",
                "message": f"Could not geocode address: {address}",
            }

        result = response["Results"][0]
        place = result["Place"]
        geometry = place["Geometry"]["Point"]

        return {
            "status": "success",
            "latitude": geometry[1],
            "longitude": geometry[0],
            "confidence": result.get("Relevance", 1.0),
            "address_components": {
                "label": place.get("Label"),
                "street": place.get("Street"),
                "municipality": place.get("Municipality"),
                "region": place.get("Region"),
                "postal_code": place.get("PostalCode"),
                "country": place.get("Country"),
            },
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Geocoding failed: {str(e)}",
        }


@tool
def proximity_search(
    user_id: str,
    latitude: float,
    longitude: float,
    radius_meters: float = 1000,
    entity_type: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Search for entities near a geographic location.

    Use this tool to find people, places, or organizations within a certain
    distance of a point. Great for answering questions like "Who lives nearby?"

    Args:
        user_id: UUID of the user performing the search.
        latitude: Latitude of the center point.
        longitude: Longitude of the center point.
        radius_meters: Search radius in meters (default 1000m = ~0.6 miles).
        entity_type: Optional filter by entity type.
        limit: Maximum number of results (default 20).

    Returns:
        Dictionary with nearby entities sorted by distance.
    """
    async def _search() -> dict[str, Any]:
        params: list[Any] = [longitude, latitude, radius_meters, UUID(user_id)]
        param_idx = 5

        type_filter = ""
        if entity_type:
            type_filter = f"AND e.entity_type = ${param_idx}"
            params.append(entity_type)
            param_idx += 1

        params.append(limit)

        query = f"""
            SELECT
                e.id,
                e.entity_type,
                e.name,
                el.label as location_label,
                el.address_raw,
                ST_Y(el.location::geometry) as latitude,
                ST_X(el.location::geometry) as longitude,
                ST_Distance(
                    el.location,
                    ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography
                ) as distance_meters
            FROM entities e
            JOIN entity_locations el ON el.entity_id = e.id
            WHERE ST_DWithin(
                el.location,
                ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography,
                $3
            )
            AND (el.valid_to IS NULL OR el.valid_to > CURRENT_DATE)
            AND (
                (e.owner_type = 'user' AND e.owner_id = $4)
                OR e.owner_type = 'family'
            )
            {type_filter}
            ORDER BY distance_meters ASC
            LIMIT ${param_idx}
        """

        results = await execute_query(query, *params)

        entities = [
            {
                "id": str(row["id"]),
                "entity_type": row["entity_type"],
                "name": row["name"],
                "location_label": row["location_label"],
                "address": row["address_raw"],
                "latitude": float(row["latitude"]),
                "longitude": float(row["longitude"]),
                "distance_meters": float(row["distance_meters"]),
                "distance_display": _format_distance(float(row["distance_meters"])),
            }
            for row in results
        ]

        return {
            "status": "success",
            "center": {"latitude": latitude, "longitude": longitude},
            "radius_meters": radius_meters,
            "count": len(entities),
            "results": entities,
        }

    return run_async(_search())


def _format_distance(meters: float) -> str:
    """Format distance for display."""
    if meters < 1000:
        return f"{int(meters)}m"
    else:
        km = meters / 1000
        if km < 10:
            return f"{km:.1f}km"
        else:
            return f"{int(km)}km"


@tool
def store_entity_location(
    entity_id: str,
    label: str,
    address: str,
    latitude: float | None = None,
    longitude: float | None = None,
    geocode_if_missing: bool = True,
) -> dict[str, Any]:
    """Store a location for an entity.

    Use this tool to add or update a location (home, work, school, etc.)
    for a person, organization, or place. Will geocode the address if
    coordinates are not provided.

    Args:
        entity_id: UUID of the entity.
        label: Location label (home, work, school, etc.).
        address: The street address.
        latitude: Optional latitude (will geocode if not provided).
        longitude: Optional longitude (will geocode if not provided).
        geocode_if_missing: Whether to geocode if coordinates not provided.

    Returns:
        Dictionary with the stored location details.
    """
    async def _store() -> dict[str, Any]:
        lat = latitude
        lon = longitude
        geocode_source = "manual"
        geocode_confidence = 1.0

        # Geocode if coordinates not provided
        if (lat is None or lon is None) and geocode_if_missing:
            geocode_result = geocode_address(address)
            if geocode_result["status"] == "success":
                lat = geocode_result["latitude"]
                lon = geocode_result["longitude"]
                geocode_source = "aws_location"
                geocode_confidence = geocode_result.get("confidence", 1.0)
            else:
                return {
                    "status": "error",
                    "message": f"Could not geocode address: {geocode_result.get('message')}",
                }

        if lat is None or lon is None:
            return {
                "status": "error",
                "message": "Coordinates required but geocoding was disabled",
            }

        # Upsert the location
        await execute_command(
            """
            INSERT INTO entity_locations (
                entity_id, label, address_raw, location,
                geocode_source, geocode_confidence
            )
            VALUES (
                $1, $2, $3,
                ST_SetSRID(ST_MakePoint($4, $5), 4326)::geography,
                $6, $7
            )
            ON CONFLICT (entity_id, label) DO UPDATE SET
                address_raw = EXCLUDED.address_raw,
                location = EXCLUDED.location,
                geocode_source = EXCLUDED.geocode_source,
                geocode_confidence = EXCLUDED.geocode_confidence
            """,
            UUID(entity_id),
            label,
            address,
            lon,
            lat,
            geocode_source,
            geocode_confidence,
        )

        return {
            "status": "success",
            "entity_id": entity_id,
            "label": label,
            "address": address,
            "latitude": lat,
            "longitude": lon,
            "geocode_source": geocode_source,
        }

    return run_async(_store())


@tool
def calculate_distance(
    from_latitude: float,
    from_longitude: float,
    to_latitude: float,
    to_longitude: float,
) -> dict[str, Any]:
    """Calculate the distance between two geographic points.

    Use this tool to find the straight-line distance between two locations.
    Returns distance in both meters and a human-readable format.

    Args:
        from_latitude: Latitude of the starting point.
        from_longitude: Longitude of the starting point.
        to_latitude: Latitude of the destination point.
        to_longitude: Longitude of the destination point.

    Returns:
        Dictionary with distance in various units.
    """
    async def _calculate() -> dict[str, Any]:
        result = await execute_one(
            """
            SELECT ST_Distance(
                ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography,
                ST_SetSRID(ST_MakePoint($3, $4), 4326)::geography
            ) as distance_meters
            """,
            from_longitude,
            from_latitude,
            to_longitude,
            to_latitude,
        )

        if not result:
            return {"status": "error", "message": "Failed to calculate distance"}

        meters = float(result["distance_meters"])

        return {
            "status": "success",
            "distance_meters": meters,
            "distance_km": meters / 1000,
            "distance_miles": meters / 1609.34,
            "display": _format_distance(meters),
        }

    return run_async(_calculate())
