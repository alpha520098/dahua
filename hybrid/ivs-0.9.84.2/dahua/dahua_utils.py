"""
Various utilities for Dahua cameras
"""
import json
import re


def dahua_brightness_to_hass_brightness(bri_str: str) -> int:
    """
    Converts a dahua brightness (which is 0 to 100 inclusive) and converts it to what HASS
    expects, which is 0 to 255 inclusive
    """
    bri = 100
    if bri_str:
        bri = int(bri_str)

    current = bri / 100
    return int(current * 255)


def hass_brightness_to_dahua_brightness(hass_brightness: int) -> int:
    """
    Converts a HASS brightness (which is 0 to 255 inclusive) to a Dahua brightness (which is 0 to 100 inclusive)
    """
    if hass_brightness is None:
        hass_brightness = 100
    return int((hass_brightness / 255) * 100)


# https://github.com/rroller/dahua/issues/166
def parse_event(data: str) -> list[dict[str, any]]:
    # This will turn the event stream data into a list of events, where each item in the list is a dictionary and where
    # the key of the dictionary is the key is for example "Code" and the value is "VideoMotion", etc
    # That's a little hard to explain... so look at this example...
    # Code=VideoMotion;action=Start;index=0;data={
    #    "Id" : [ 0 ],
    #    "RegionName" : [ "Region1" ],
    #    "SmartMotionEnable" : true
    # }
    # will be turned into
    # [{
    #   "Code":"VideoMotion",
    #   "action":"Start",
    #   "index":"0",
    #   ...
    # }]

    # We will split on "--myboundary" and then skip the first 3 lines so we end up with a string that starts with Code=
    event_blocks = re.split(r'--myboundary\n', data)

    events = []

    for event_block in event_blocks:
        # Skip the first 3 lines... the first line looks like: Content-Type: text/plain
        s = event_block.split("\n", 3)
        if len(s) < 3:
            continue
        event_block = s[3].strip()
        if not event_block.startswith("Code="):
            continue

        # At this point we'll have something that looks like this...
        # Code=VideoMotion;action=Start;index=0;data={
        #    "Id" : [ 0 ],
        #    "RegionName" : [ "Region1" ],
        #    "SmartMotionEnable" : true
        # }
        # And we want to put each key/value pair into a dictionary...
        event = dict()
        for key_value in event_block.split(';'):
            key, value = key_value.split('=', 1)
            event[key] = value

        # data is a json string, convert it to real json and add it back to the output dic
        if "data" in event:
            try:
                data = json.loads(event["data"])
                event["data"] = data
            except Exception:  # pylint: disable=broad-except
                pass
        events.append(event)

    return events


HOMOGLYPHS = {
    "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I",
    "Κ": "K", "Μ": "M", "Ν": "N", "Ο": "O", "Ρ": "P", "Τ": "T",
    "Υ": "Y", "Χ": "X",
}


def normalize_plate(plate_text: str | None) -> str:
    """Normalize OCR plate text for display and comparison."""
    if not plate_text:
        return ""

    clean = str(plate_text).upper()
    for source, replacement in HOMOGLYPHS.items():
        clean = clean.replace(source, replacement)
    clean = re.sub(r"[^A-Z0-9]", "", clean)

    # Correct the most common O/0 confusion for 3-letter + 4-digit plates.
    if len(clean) == 7:
        letters = clean[:3].replace("0", "O")
        digits = clean[3:].replace("O", "0")
        if letters.isalpha() and digits.isdigit():
            clean = letters + digits

    return clean


def parse_authorized_plates(raw_value: str | list | None) -> list[str]:
    """Parse a comma-separated or list-based authorized plate setting."""
    if not raw_value:
        return []

    if isinstance(raw_value, list):
        items = raw_value
    elif isinstance(raw_value, str):
        items = raw_value.split(",")
    else:
        return []

    plates = []
    for item in items:
        normalized = normalize_plate(str(item).strip())
        if normalized and normalized not in plates:
            plates.append(normalized)
    return plates


def _first_direction(value):
    """Return the first usable direction string from a Dahua value."""
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, (list, tuple)):
        for item in value:
            if isinstance(item, str) and item.strip():
                return item.strip()
    return None


def _extract_plate_from_raw_string(text: str, event: dict) -> dict | None:
    """Extract plate details from malformed or truncated Dahua JSON."""
    plate_text = None
    confidence = None

    match = re.search(
        r'"(?:PlateNumber|plateNumber|PlateText|plateText|PlateNo|plateNo)"\s*:\s*"([A-Za-z0-9 -]+)"',
        text,
    )
    if match:
        plate_text = match.group(1)

    if not plate_text:
        candidates = re.findall(r'"Text"\s*:\s*"([A-Za-z0-9 -]+)"', text)
        for candidate in candidates:
            normalized = normalize_plate(candidate)
            if (
                normalized
                and any(char.isalpha() for char in normalized)
                and any(char.isdigit() for char in normalized)
            ):
                plate_text = candidate
                break

    if not plate_text:
        return None

    clean_plate = normalize_plate(plate_text)
    if not clean_plate:
        return None

    match = re.search(r'"Confidence"\s*:\s*([0-9]+)', text)
    if match:
        try:
            confidence = int(match.group(1))
        except ValueError:
            confidence = None

    brand_match = re.search(
        r'"(?:VehicleSign|Brand|VehicleLogo)"\s*:\s*"([^\"]+)"',
        text,
    )
    color_match = re.search(r'"VehicleColor"\s*:\s*"([^\"]+)"', text)

    return {
        "plate": clean_plate,
        "raw_plate": plate_text,
        "confidence": confidence,
        "vehicle_type": None,
        "vehicle_color": color_match.group(1) if color_match else None,
        "vehicle_brand": brand_match.group(1) if brand_match else None,
        "vehicle_series": None,
        "direction": None,
        "event_code": event.get("Code"),
        "timestamp": None,
    }


def extract_plate_data(event: dict) -> dict | None:
    """Extract plate and vehicle metadata from common Dahua ANPR schemas."""
    if not isinstance(event, dict):
        return None

    data = event.get("data", event.get("Data", {}))
    if not isinstance(data, dict):
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception:  # pylint: disable=broad-except
                return _extract_plate_from_raw_string(data, event)
        else:
            return None

    ignored = {"unlicensed", "unknown", "none", "null", "--", ""}
    plate_text = None
    confidence = None
    vehicle_type = None
    vehicle_color = None
    vehicle_brand = None
    vehicle_series = None
    direction = None

    obj = data.get("Object") or data.get("object")
    if isinstance(obj, dict):
        object_type = str(obj.get("ObjectType", "")).strip().lower()
        if object_type in ("plate", "") or "plate" in obj:
            text = str(obj.get("Text", "")).strip()
            if text.lower() not in ignored:
                plate_text = text
                confidence = obj.get("Confidence")

    if not plate_text:
        plate_obj = data.get("Plate") or data.get("plate")
        if isinstance(plate_obj, dict):
            text = str(
                plate_obj.get("Text")
                or plate_obj.get("PlateNumber")
                or ""
            ).strip()
            if text.lower() not in ignored:
                plate_text = text
                confidence = plate_obj.get("Confidence")
        elif isinstance(plate_obj, str):
            text = plate_obj.strip()
            if text.lower() not in ignored:
                plate_text = text

    traffic_car = data.get("TrafficCar") or data.get("trafficCar")
    if isinstance(traffic_car, dict):
        if not plate_text:
            text = str(traffic_car.get("PlateNumber", "")).strip()
            if text.lower() not in ignored:
                plate_text = text
        vehicle_type = traffic_car.get("VehicleType")
        vehicle_color = traffic_car.get("VehicleColor")
        vehicle_brand = (
            traffic_car.get("Brand")
            or traffic_car.get("VehicleSign")
            or traffic_car.get("VehicleLogo")
            or traffic_car.get("Logo")
        )
        vehicle_series = traffic_car.get("SubBrand") or traffic_car.get("Series")
        direction = (
            traffic_car.get("Direction")
            or traffic_car.get("DirectionName")
            or _first_direction(traffic_car.get("DrivingDirection"))
            or _first_direction(traffic_car.get("JunctionDirection"))
            or _first_direction(traffic_car.get("VehicleDirection"))
        )

    if not plate_text:
        for key in (
            "PlateNumber", "plateNumber", "PlateText", "plateText",
            "PlateNo", "plateNo",
        ):
            value = data.get(key)
            if isinstance(value, str):
                text = value.strip()
                if text.lower() not in ignored:
                    plate_text = text
                    break

    if not plate_text:
        return None

    clean_plate = normalize_plate(plate_text)
    if not clean_plate:
        return None

    vehicle = data.get("Vehicle") or data.get("vehicle")
    if isinstance(vehicle, dict):
        vehicle_type = vehicle_type or vehicle.get("Category") or vehicle.get("VehicleType") or vehicle.get("Text")
        if not vehicle_color and isinstance(vehicle.get("MainColor"), str):
            vehicle_color = vehicle.get("MainColor")
        vehicle_brand = (
            vehicle_brand
            or vehicle.get("Brand")
            or vehicle.get("VehicleSign")
            or vehicle.get("VehicleLogo")
            or vehicle.get("Logo")
        )
        vehicle_series = vehicle_series or vehicle.get("SubBrand") or vehicle.get("Series")

    vehicle_brand = (
        vehicle_brand
        or data.get("Brand")
        or data.get("VehicleSign")
        or data.get("VehicleLogo")
        or data.get("Logo")
    )
    direction = (
        direction
        or data.get("Direction")
        or data.get("DirectionName")
        or _first_direction(data.get("DrivingDirection"))
        or _first_direction(data.get("JunctionDirection"))
        or _first_direction(data.get("VehicleDirection"))
    )

    return {
        "plate": clean_plate,
        "raw_plate": plate_text,
        "confidence": confidence,
        "vehicle_type": vehicle_type,
        "vehicle_color": vehicle_color,
        "vehicle_brand": vehicle_brand,
        "vehicle_series": vehicle_series,
        "direction": direction,
        "event_code": event.get("Code"),
        "timestamp": event.get("UTC") or data.get("UTC") or data.get("LocaleTime"),
    }
