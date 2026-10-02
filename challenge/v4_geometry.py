"""Small, dependency-free geometry layer for Agent Observer v4 cards."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Mapping


DEG = math.pi / 180.0


@dataclass(frozen=True)
class Site:
    latitude_deg: float
    longitude_deg: float
    utc_offset_hours: float = 0.0


@dataclass(frozen=True)
class FiberConfig:
    n_fibers: int
    fiber_area_deg2: float
    gap_deg: float = 0.0

    @property
    def grid_size(self) -> int:
        side = math.isqrt(self.n_fibers)
        if side * side != self.n_fibers:
            raise ValueError("v4 fibre maps currently require a square number of fibres")
        return side

    @property
    def cell_side_deg(self) -> float:
        return math.sqrt(self.fiber_area_deg2)

    @property
    def field_side_deg(self) -> float:
        return self.grid_size * self.cell_side_deg + (self.grid_size - 1) * self.gap_deg


def _jd(utc: datetime) -> float:
    return 2451545.0 + (utc - datetime(2000, 1, 1, 12, 0, 0)).total_seconds() / 86400.0


def _lst_deg(utc: datetime, site: Site) -> float:
    jd = _jd(utc)
    centuries = (jd - 2451545.0) / 36525.0
    gmst = (
        280.46061837
        + 360.98564736629 * (jd - 2451545.0)
        + 0.000387933 * centuries * centuries
        - centuries * centuries * centuries / 38710000.0
    )
    return (gmst + site.longitude_deg) % 360.0


def _wrap_deg(value: float) -> float:
    return (value + 180.0) % 360.0 - 180.0


def altaz_to_radec(alt_deg: float, az_deg: float, utc: datetime, site: Site) -> tuple[float, float]:
    """Convert horizon coordinates to ICRS-like RA/Dec for the card simulator."""
    alt = alt_deg * DEG
    az = az_deg * DEG
    latitude = site.latitude_deg * DEG
    sin_dec = math.sin(alt) * math.sin(latitude) + math.cos(alt) * math.cos(latitude) * math.cos(az)
    dec = math.asin(max(-1.0, min(1.0, sin_dec)))
    cos_dec = max(1e-12, math.cos(dec))
    sin_hour_angle = -math.sin(az) * math.cos(alt) / cos_dec
    cos_hour_angle = (
        math.sin(alt) - math.sin(latitude) * math.sin(dec)
    ) / max(1e-12, math.cos(latitude) * cos_dec)
    hour_angle = math.atan2(sin_hour_angle, cos_hour_angle) / DEG
    ra = (_lst_deg(utc, site) - hour_angle) % 360.0
    return ra, dec / DEG


def radec_to_altaz(ra_deg: float, dec_deg: float, utc: datetime, site: Site) -> tuple[float, float]:
    """Convert RA/Dec to horizon coordinates using north-through-east azimuth."""
    latitude = site.latitude_deg * DEG
    dec = dec_deg * DEG
    hour_angle = _wrap_deg(_lst_deg(utc, site) - ra_deg) * DEG
    sin_alt = (
        math.sin(dec) * math.sin(latitude)
        + math.cos(dec) * math.cos(latitude) * math.cos(hour_angle)
    )
    alt = math.asin(max(-1.0, min(1.0, sin_alt)))
    y = -math.sin(hour_angle) * math.cos(dec)
    x = math.sin(dec) * math.cos(latitude) - math.cos(dec) * math.sin(latitude) * math.cos(hour_angle)
    az = math.atan2(y, x) / DEG
    return alt / DEG, az % 360.0


def tangent_offset_deg(pointing_ra_deg: float, pointing_dec_deg: float, target_ra_deg: float, target_dec_deg: float) -> tuple[float, float]:
    """Return east/north small-angle offsets from a pointing to a target."""
    delta_ra = _wrap_deg(target_ra_deg - pointing_ra_deg)
    mean_dec = ((pointing_dec_deg + target_dec_deg) / 2.0) * DEG
    return delta_ra * math.cos(mean_dec), target_dec_deg - pointing_dec_deg


def fiber_center_offset(config: FiberConfig, fiber_index: int) -> tuple[float, float]:
    if not 0 <= fiber_index < config.n_fibers:
        raise ValueError(f"fibre index {fiber_index} is outside 0..{config.n_fibers - 1}")
    side = config.grid_size
    row, column = divmod(fiber_index, side)
    pitch = config.cell_side_deg + config.gap_deg
    center = (side - 1) / 2.0
    east = (column - center) * pitch
    north = (center - row) * pitch
    return east, north


def fiber_cell_for_offset(config: FiberConfig, east_deg: float, north_deg: float) -> int | None:
    side = config.grid_size
    pitch = config.cell_side_deg + config.gap_deg
    center = (side - 1) / 2.0
    for row in range(side):
        for column in range(side):
            cell_east = (column - center) * pitch
            cell_north = (center - row) * pitch
            if (
                abs(east_deg - cell_east) <= config.cell_side_deg / 2.0
                and abs(north_deg - cell_north) <= config.cell_side_deg / 2.0
            ):
                return row * side + column
    return None


def target_in_fiber_cell(
    config: FiberConfig,
    pointing_ra_deg: float,
    pointing_dec_deg: float,
    target_ra_deg: float,
    target_dec_deg: float,
    fiber_index: int,
) -> bool:
    east, north = tangent_offset_deg(pointing_ra_deg, pointing_dec_deg, target_ra_deg, target_dec_deg)
    return fiber_cell_for_offset(config, east, north) == fiber_index


def minimum_altitude_deg(ra_deg: float, dec_deg: float, start_utc: datetime, end_utc: datetime, site: Site) -> float:
    """Sample the exposure interval; endpoint and midpoint checks catch the card's horizon constraint."""
    if end_utc < start_utc:
        raise ValueError("exposure end precedes start")
    seconds = max(0.0, (end_utc - start_utc).total_seconds())
    sample_count = max(2, min(9, int(seconds // 900) + 2))
    values = []
    for index in range(sample_count):
        fraction = index / (sample_count - 1)
        instant = start_utc + timedelta(seconds=seconds * fraction)
        values.append(radec_to_altaz(ra_deg, dec_deg, instant, site)[0])
    return min(values)


def pointing_from_target(ra_deg: float, dec_deg: float, utc: datetime, site: Site) -> dict[str, float]:
    alt_deg, az_deg = radec_to_altaz(ra_deg, dec_deg, utc, site)
    return {"alt_deg": round(alt_deg, 8), "az_deg": round(az_deg, 8)}


def as_site(value: Mapping[str, object]) -> Site:
    return Site(
        latitude_deg=float(value["latitude_deg"]),
        longitude_deg=float(value["longitude_deg"]),
        utc_offset_hours=float(value.get("utc_offset_hours", 0.0)),
    )


def as_fiber_config(value: Mapping[str, object]) -> FiberConfig:
    field = value.get("field")
    if not isinstance(field, Mapping):
        raise ValueError("v4 fiber config missing field")
    return FiberConfig(
        n_fibers=int(field["n_fibers"]),
        fiber_area_deg2=float(field["fiber_area_deg2"]),
        gap_deg=float(field.get("gap_deg", 0.0)),
    )
