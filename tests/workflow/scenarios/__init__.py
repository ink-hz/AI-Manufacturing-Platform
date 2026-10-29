"""Private acceptance registry. This package is intentionally outside the wheel."""

from importlib import import_module

CASE_IDS = tuple([f"F{i:02}" for i in range(1, 5)] + [f"E{i:02}" for i in range(1, 33)])


class ScenarioRegistry:
    @staticmethod
    def validate(case_id):
        if case_id not in CASE_IDS:
            raise ValueError(f"Unknown case: {case_id}")
        return case_id

    @classmethod
    def get(cls, case_id):
        cls.validate(case_id)
        module = import_module(
            ".full_flows" if case_id.startswith("F") else ".exceptions", __package__
        )
        return getattr(module, case_id.lower())


# Required end states; E18 reflects the approved administrator full-access policy.
EXPECTATIONS = {
    "F01": "Camera100; orders→WO60+40; fixed versions; each SN/lot/test/release; two shipments/acceptances; remaining40 after first; cost/quality close; feedback link retained",
    "F02": "Camera20; trial5 M1 issues; approved ECO M2 subsequent15; both histories; real first article and calibration; deliver/accept/review",
    "F03": "Printer10 WO6+4; distinct printer route/limits; camera evidence rejected; two deliveries/acceptances and closure/feedback",
    "F04": "OEM30 C1/M1; mixed owned supply; customer version approval and release; shipments10+20; customer material consumption/return reconciliation and independent closures",
    "E01": "Forecast rejected for production; later firm demand/source review/order; duplicate ERP source once",
    "E02": "Original promise retained; reduction/cancel pending against allocation/PO/WIP; no silent release",
    "E03": "Wrong customer revision retained as exception; correct one satisfies only matching approval; others independent",
    "E04": "Old/new WO/SN histories and stock/WIP impacts; unresolved disposition prevents ECO close",
    "E05": "Qualified80, in-transit20, confirmed reserve≤80, shortage20",
    "E06": "Received20, IQC15/5, shortage5 then replacement5; original reject persists",
    "E07": "Foreign owner/frozen/expired/allocated stock rejected; eligible balances unchanged",
    "E08": "Partial receipt sums/balance, original/revised promise, customer replenishment, no duplication",
    "E09": "Unit/precision/cutoff/import errors identify source fields; no readiness success",
    "E10": "Concurrent external atomic reserve sum≤stock; independent receipts and idempotent retry",
    "E11": "New current package never mutates bound executed snapshot; explicit split/switch",
    "E12": "Calibration expired at planned use blocks; corrected evidence and re-evaluation required",
    "E13": "Trial valid without first article; bulk fails for planned/failed first article; genuine retest unblocks",
    "E14": "Wrong station/program/unknownSN/duplicate/overreport no good-count pollution",
    "E15": "Shortage interruption links supply exception; restored stock+plan+resume receipt; timeline retained",
    "E16": "First96/final99/scrap1; four first failures retained; ship100 rejected",
    "E17": "Missing measurement/unit/limit/version not PASS; cannot weaken frozen limits",
    "E18": "Ordinary production/planner quality403; trusted global admin and qualified scoped quality actor approved/audited",
    "E19": "Manufacturing+quality do not replace contractual customer release; shipment blocked until correct receipt",
    "E20": "Lot forward and shippedSN reverse exact links; pending vs accepted freeze, no source impersonation",
    "E21": "60 shipped→40 remaining; duplicateSN/41 rejected; valid40 and acceptance close",
    "E22": "Shipped/signed/accepted separate; required issue has owner and blocks fulfillment",
    "E23": "ERP cost close while quality/RMA unresolved remains open",
    "E24": "RMA→containment→root cause→correction→effectiveness→actual ECO execution; original delivery/history retained",
    "E25": "Same op/payload returns same result once; changed payload409; revoked actor cannot replay",
    "E26": "Authority committed timeout; unknown local status; receipt query resolves once after restart",
    "E27": "Old freeze/unfreeze/version event rejected, current state and rejection audit intact",
    "E28": "Same sum/different detail detected, owned discrepancy; reject never posted",
    "E29": "Real trusted identity/CSRF/project/customer/action ACL and revocation; legacy endpoints protected",
    "E30": "Two edits CAS; draft retained; handbook full/context stable; abandon executes exactly one departure",
    "E31": "Fresh process/session resumes all key states; API/DB/dashboard same; no duplicate operation",
    "E32": "Alternate seeds/reset/mock state; owned test data only, legacy seven unchanged, simulation labels",
}
