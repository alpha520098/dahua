"""Read-only IVS rule discovery and event state for the 0.9.84 hybrid.

The stable Id, not the array index or rule name, identifies a rule. NVRs may
report different Ids via different APIs, so unmatched events are never guessed.
"""
import re
from collections import Counter


def rule_id(value):
    """Return an unambiguous scalar rule identifier, including zero."""
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    value = str(value).strip()
    return value if value else None


def rules_from_flat(table, channel, table_name="VideoAnalyseRule"):
    """Select complete normal IVS rows belonging to exactly this channel."""
    if not isinstance(table, dict):
        return []
    pattern = re.compile(
        rf"table\.{re.escape(table_name)}\[{int(channel)}\]\[(\d+)\]\.Id"
    )
    rows = []
    counts = Counter()
    for key, value in table.items():
        if not isinstance(key, str):
            continue
        match = pattern.fullmatch(key)
        identity = rule_id(value)
        if not match or identity is None:
            continue
        counts[identity] += 1
        prefix = key[:-3]
        kind = table.get(prefix + ".Type")
        if table.get(prefix + ".Class") != "Normal":
            continue
        if table.get(prefix + ".Enable") not in (True, False, "true", "false"):
            continue
        if not isinstance(kind, str) or not kind:
            continue
        name = table.get(prefix + ".Name")
        rows.append({
            "id": identity,
            "index": int(match[1]),
            "channel": int(channel),
            "name": name if isinstance(name, str) and name else f"IVS Rule {identity}",
            "type": kind,
            "source": table_name,
        })
    return sorted(
        (row for row in rows if counts[row["id"]] == 1),
        key=lambda row: row["index"],
    )


def rules_from_remote(table, channel):
    """Normalize the per-channel RemoteVideoAnalyseRule RPC2 response."""
    if not isinstance(table, list) or any(not isinstance(row, dict) for row in table):
        raise ValueError("RemoteVideoAnalyseRule is not a list of rule objects")
    flat = {}
    for index, row in enumerate(table):
        prefix = f"table.RemoteVideoAnalyseRule[{int(channel)}][{index}]"
        for name in ("Id", "Class", "Enable", "Name", "Type"):
            if name in row:
                flat[prefix + "." + name] = row[name]
    return rules_from_flat(flat, channel, "RemoteVideoAnalyseRule")


class IVSRuleTracker:
    """Keep IVS state separate from the hybrid's existing event sensors."""

    def __init__(self, rules):
        self.rules = {row["id"]: dict(row) for row in rules}
        self.states = {identity: False for identity in self.rules}
        self.details = {identity: {} for identity in self.rules}
        self.active = {}
        self.unmatched_count = 0
        self.last_unmatched = None

    def apply(self, event):
        """Return changed rule IDs; one code-level Stop clears concurrent rules."""
        if not isinstance(event, dict):
            return []
        code = event.get("Code")
        action = event.get("action", event.get("Action"))
        if not isinstance(code, str) or action not in ("Start", "Stop"):
            return []
        payload = event.get("data", event.get("Data", {}))
        payload = payload if isinstance(payload, dict) else {}

        if action == "Stop":
            # A Dahua Stop can name only the first rule, or omit data entirely.
            # Clear the rules this code lit, retaining each rule's own metadata.
            identities = set(self.active.pop(code, ()))
            identities.update(
                identity for identity, row in self.rules.items()
                if row["type"] == code and self.states[identity]
            )
            changed = []
            for identity in sorted(identities):
                if self.states[identity]:
                    self.states[identity] = False
                    changed.append(identity)
            return changed

        if payload.get("Class") != "Normal":
            return []
        identity = rule_id(payload.get("RuleID"))
        if identity is None:
            identity = rule_id(payload.get("RuleId"))
        row = self.rules.get(identity)
        if row is None or row["type"] != code:
            # Ignore unrelated event types (for example HumanTrait).
            if any(item["type"] == code for item in self.rules.values()):
                self.unmatched_count += 1
                self.last_unmatched = {
                    "code": code,
                    "rule_id": identity,
                    "reason": "missing_or_unknown_id" if row is None else "rule_type_mismatch",
                }
            return []

        obj = payload.get("Object")
        obj = obj if isinstance(obj, dict) else {}
        details = {}
        direction = payload.get("Direction")
        if isinstance(direction, str) and direction:
            details["direction"] = direction
        object_type = obj.get("ObjectType")
        if isinstance(object_type, str) and object_type.lower() != "unknown":
            details["object_type"] = object_type
        self.details[identity] = details
        self.states[identity] = True
        self.active.setdefault(code, set()).add(identity)
        return [identity]
