"""Read-time eligibility of authority-confirmed material lots."""

from datetime import date

from .ownership import material_hold


def lot_unavailable_reason(tx, project_id, lot, now):
    if lot['state'] != 'active':
        return 'Material lot is frozen'
    if date.fromisoformat(lot['expiry']) < now.date():
        return 'Material lot has expired'
    return material_hold(tx, project_id, lot)
