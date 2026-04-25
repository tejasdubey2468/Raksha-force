"""
RAKSHA-FORCE — Geospatial Utilities
Provides Haversine distance calculation and coordinate validation.
"""

import math
from typing import Optional


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the great-circle distance between two points on Earth.

    Uses the Haversine formula for accurate distance calculation.

    Args:
        lat1, lon1: Source coordinates (degrees)
        lat2, lon2: Destination coordinates (degrees)

    Returns:
        Distance in kilometres (float)

    Example:
        >>> dist = haversine_distance(18.5204, 73.8567, 18.5104, 73.8450)
        >>> print(f"{dist:.2f} km")  # ~1.45 km
    """
    R = 6371.0  # Earth's radius in km

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


def estimate_eta_minutes(distance_km: float, team_type: str) -> int:
    """
    Estimate ETA in minutes based on distance and team type.
    Accounts for urban traffic conditions in Indian cities.

    Args:
        distance_km: Distance to incident in km
        team_type:   'fire' | 'medical' | 'police' | 'ndrf'

    Returns:
        Estimated arrival time in minutes
    """
    # Average speeds (km/h) by team type in urban India
    speeds = {
        "fire":    45,   # Fire trucks have sirens, some road clearing
        "medical": 50,   # Ambulances highest priority
        "police":  55,   # Police bikes/cars, fastest responders
        "ndrf":    35,   # Heavy equipment, slower
    }
    speed = speeds.get(team_type, 40)  # default 40 km/h for unknown
    eta = (distance_km / speed) * 60
    return max(3, round(eta))  # minimum 3 minutes


def validate_india_coordinates(lat: float, lng: float) -> bool:
    """
    Validate that coordinates fall within India's approximate bounding box.
    Rough bounds: lat 6–37°N, lon 68–98°E

    Args:
        lat: Latitude
        lng: Longitude

    Returns:
        True if within India's bounding box
    """
    return 6.0 <= lat <= 37.0 and 68.0 <= lng <= 98.0


def validate_coordinates(lat: float, lng: float) -> tuple[bool, Optional[str]]:
    """
    Validate GPS coordinates are within valid global ranges.

    Returns:
        (is_valid: bool, error_message: str | None)

    Example:
        >>> ok, err = validate_coordinates(18.52, 73.86)
        >>> assert ok and err is None
    """
    if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
        return False, "Coordinates must be numeric"
    if not (-90 <= lat <= 90):
        return False, f"Latitude {lat} out of range [-90, 90]"
    if not (-180 <= lng <= 180):
        return False, f"Longitude {lng} out of range [-180, 180]"
    return True, None


def bearing_degrees(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate initial compass bearing from point 1 to point 2.
    Useful for dispatch routing hints.

    Returns:
        Bearing in degrees (0–360, clockwise from North)
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dl = math.radians(lon2 - lon1)

    x = math.sin(dl) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dl)

    bearing = math.degrees(math.atan2(x, y))
    return (bearing + 360) % 360
