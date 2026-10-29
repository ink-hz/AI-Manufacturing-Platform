"""Project scoped NPI evidence and controlled immutable reuse."""

import json
from uuid import UUID, uuid4

from .commands import COMMAND_REGISTRY
from .contracts import (
    DomainError,
    MutationResult,
    ObjectDetail,
    ObjectKind,
    ObjectRelation,
    ObjectSummary,
)
from .engineering import _history, count, fail
from .execution_models import TestEvidenceScope
from .introduction_models import (
    NPI,
    ApplyAsset,
    ApproveNPI,
    AssetUse,
    IssueNPI,
    NPIIssue,
    OpenNPI,
    PublicAssetEntry,
    PublicAssetPage,
    PublishAsset,
    ResolveNPI,
    ReusableAsset,
    ReviewNPI,
    TrialNPI,
    VerifyAsset,
)
from .orders import own
from .queries import OBJECT_REGISTRY


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def result(kind, ident):
    return MutationResult(object_type=kind, object_id=UUID(str(ident)))


def bump(tx, pid, npi):
    tx.execute(
        "UPDATE npis SET generation=generation+1 WHERE project_id=? AND id=?",
        (str(pid), str(npi)),
    )


def records(tx, pid, npi, kind):
    return [
        json.loads(r[0])
        for r in tx.execute(
            "SELECT payload_json FROM npi_records WHERE project_id=? AND npi_id=? AND record_type=? ORDER BY seq",
            (str(pid), str(npi), kind),
        )
    ]


def append(tx, context, npi, kind, payload):
    ident = str(uuid4())
    payload = dict(
        payload,
        id=ident,
        actor_id=str(context.actor.user_id),
        recorded_at=context.now.isoformat(),
    )
    tx.execute(
        "INSERT INTO npi_records(id,project_id,npi_id,record_type,payload_json) VALUES (?,?,?,?,?)",
        (ident, str(context.project_id), str(npi), kind, dump(payload)),
    )


def bind_work_order(tx, pid, npi, wo_id):
    wo = own(tx, "work_orders", pid, wo_id)
    if wo["revision_id"] != npi["revision_id"]:
        fail("NPI work order must use the fixed NPI revision")
    tx.execute(
        "INSERT OR IGNORE INTO npi_work_orders VALUES (?,?,?)",
        (npi["id"], str(pid), str(wo_id)),
    )
    return wo


def open_npi(tx, context, command):
    own(tx, "engineering_revisions", context.project_id, command.revision_id)
    ident = str(uuid4())
    tx.execute(
        "INSERT INTO npis VALUES (?,?,?,?,?,?,?,?)",
        (
            ident,
            str(context.project_id),
            str(command.revision_id),
            command.product_family,
            command.scenario,
            dump(command.required_checks),
            1,
            context.now.isoformat(),
        ),
    )
    npi = own(tx, "npis", context.project_id, ident)
    for wo in command.work_order_ids:
        bind_work_order(tx, context.project_id, npi, wo)
    return result("npi", ident)


def review_npi(tx, context, command):
    own(tx, "npis", context.project_id, command.npi_id)
    append(
        tx,
        context,
        command.npi_id,
        "review",
        {"checks": [c.model_dump(mode="json") for c in command.checks]},
    )
    bump(tx, context.project_id, command.npi_id)
    return result("npi", command.npi_id)


def tests_valid(tx, pid, npi, wo_id, test_ids, *, require_pass=True):
    """Use the real quality reader; bypass-capable fixture readers cannot approve NPI."""
    from . import quality

    if not test_ids or len(set(map(str, test_ids))) != len(test_ids):
        return False
    wo = tx.execute(
        "SELECT * FROM work_orders WHERE project_id=? AND id=? AND revision_id=?",
        (str(pid), str(wo_id), npi["revision_id"]),
    ).fetchone()
    if wo is None:
        return False
    for ident in test_ids:
        test = tx.execute(
            "SELECT * FROM quality_tests WHERE project_id=? AND id=? AND revision_id=?",
            (str(pid), str(ident), npi["revision_id"]),
        ).fetchone()
        if test is None:
            return False
        unit = tx.execute(
            "SELECT * FROM units WHERE project_id=? AND id=? AND work_order_id=?",
            (str(pid), test["unit_id"], str(wo_id)),
        ).fetchone()
        if not unit or unit["mode"] != "trial" or not unit["accepted_start_id"]:
            return False
        if not quality.valid_test(tx, pid, test["id"]):
            return False
        if require_pass and not quality.complete_pass(
            tx,
            pid,
            test["id"],
            unit["id"],
            npi["revision_id"],
            scope=TestEvidenceScope.model_validate_json(test["scope_json"]),
        ):
            return False
    return True


def trial_qualified(tx, pid, npi, trial):
    if not tests_valid(tx, pid, npi, trial["work_order_id"], trial["test_ids"]):
        return False
    started = {
        r[0]
        for r in tx.execute(
            "SELECT id FROM units WHERE project_id=? AND work_order_id=? AND mode='trial' AND accepted_start_id IS NOT NULL",
            (str(pid), trial["work_order_id"]),
        )
    }
    covered = {
        tx.execute(
            "SELECT unit_id FROM quality_tests WHERE project_id=? AND id=?",
            (str(pid), tid),
        ).fetchone()[0]
        for tid in trial["test_ids"]
    }
    return bool(started) and started == covered


def trial_views(tx, pid, npi):
    return [
        dict(t, qualified=trial_qualified(tx, pid, npi, t))
        for t in records(tx, pid, npi["id"], "trial")
    ]


def trial_npi(tx, context, command):
    npi = own(tx, "npis", context.project_id, command.npi_id)
    bind_work_order(tx, context.project_id, npi, command.work_order_id)
    if not tests_valid(
        tx,
        context.project_id,
        npi,
        command.work_order_id,
        command.test_ids,
        require_pass=False,
    ):
        fail(
            "NPI trial requires real completed trial tests for its work order and revision"
        )
    append(
        tx,
        context,
        command.npi_id,
        "trial",
        {
            "work_order_id": str(command.work_order_id),
            "test_ids": list(map(str, command.test_ids)),
            "evidence": command.evidence,
            "outcome": "pass"
            if all(
                tx.execute(
                    "SELECT outcome FROM quality_tests WHERE project_id=? AND id=?",
                    (str(context.project_id), str(tid)),
                ).fetchone()[0]
                == "pass"
                for tid in command.test_ids
            )
            else "fail",
        },
    )
    bump(tx, context.project_id, command.npi_id)
    return result("npi", command.npi_id)


def issue_npi(tx, context, command):
    own(tx, "npis", context.project_id, command.npi_id)
    ident = str(uuid4())
    payload = command.model_dump(
        mode="json", include={"phenomenon", "risk", "containment"}
    )
    tx.execute(
        "INSERT INTO npi_issues VALUES (?,?,?,?,?,?)",
        (
            ident,
            str(context.project_id),
            str(command.npi_id),
            dump(payload),
            None,
            context.now.isoformat(),
        ),
    )
    bump(tx, context.project_id, command.npi_id)
    return result("npi_issue", ident)


def resolution_valid(tx, pid, npi, test_ids):
    if not test_ids:
        return True
    # Resolution can cite only actual trial evidence previously adopted by this NPI.
    trials = records(tx, pid, npi["id"], "trial")
    return any(
        set(map(str, test_ids)) <= set(t["test_ids"])
        and tests_valid(tx, pid, npi, t["work_order_id"], test_ids)
        for t in trials
    )


def resolve_npi(tx, context, command):
    issue = own(tx, "npi_issues", context.project_id, command.issue_id)
    npi = own(tx, "npis", context.project_id, issue["npi_id"])
    if issue["resolution_json"]:
        fail("NPI issue resolution is immutable")
    if not resolution_valid(tx, context.project_id, npi, command.test_ids):
        fail("NPI resolution requires current verified trial measurements")
    payload = command.model_dump(
        mode="json", exclude={"action", "operation_id", "expected_version", "issue_id"}
    )
    payload.update(
        actor_id=str(context.actor.user_id), recorded_at=context.now.isoformat()
    )
    tx.execute(
        "UPDATE npi_issues SET resolution_json=? WHERE project_id=? AND id=?",
        (dump(payload), str(context.project_id), issue["id"]),
    )
    bump(tx, context.project_id, npi["id"])
    return result("npi_issue", issue["id"])


def verification_records(tx, pid, use_id):
    return [
        json.loads(r[0])
        for r in tx.execute(
            "SELECT payload_json FROM asset_verifications WHERE project_id=? AND asset_use_id=? ORDER BY seq",
            (str(pid), str(use_id)),
        )
    ]


def blockers(tx, pid, npi):
    reasons = []
    reviews = records(tx, pid, npi["id"], "review")
    required = set(json.loads(npi["required_checks_json"]))
    for review in reviews:
        required.update(c["code"] for c in review["checks"] if c["required"])
    latest = {c["code"]: c for c in reviews[-1]["checks"]} if reviews else {}
    if any(
        code not in latest or latest[code]["decision"] == "blocked" for code in required
    ):
        reasons.append("NPI required engineering review is missing or blocked")
    if any(c["decision"] == "blocked" for c in latest.values()):
        reasons.append("NPI engineering review contains a blocker")
    trials = records(tx, pid, npi["id"], "trial")
    latest_trials = {t["work_order_id"]: t for t in trials}
    if not latest_trials or not all(
        trial_qualified(tx, pid, npi, t) for t in latest_trials.values()
    ):
        reasons.append("NPI requires current valid completed trial measurements")
    for issue in tx.execute(
        "SELECT * FROM npi_issues WHERE project_id=? AND npi_id=?",
        (str(pid), npi["id"]),
    ):
        if not issue["resolution_json"] or not resolution_valid(
            tx, pid, npi, json.loads(issue["resolution_json"])["test_ids"]
        ):
            reasons.append("NPI has unresolved or unverified issues")
            break
    for use in tx.execute(
        "SELECT * FROM asset_uses WHERE project_id=? AND npi_id=? AND required=1",
        (str(pid), npi["id"]),
    ):
        checks = verification_records(tx, pid, use["id"])
        if not checks or checks[-1]["decision"] != "pass":
            reasons.append("NPI required adopted asset check has not passed")
            break
    return reasons


def bulk_reasons(tx, pid, npi):
    reasons = blockers(tx, pid, npi)
    approvals = records(tx, pid, npi["id"], "approval")
    if not approvals or approvals[-1]["generation"] != npi["generation"]:
        reasons.append("NPI current revision of evidence requires approval")
    return reasons


def guard_bulk_start(tx, pid, wo_id):
    for row in tx.execute(
        "SELECT n.* FROM npis n JOIN npi_work_orders w ON w.npi_id=n.id AND w.project_id=n.project_id WHERE w.project_id=? AND w.work_order_id=?",
        (str(pid), str(wo_id)),
    ):
        reasons = bulk_reasons(tx, pid, row)
        if reasons:
            raise DomainError(
                "PRECONDITION_FAILED",
                409,
                "NPI approval blocks bulk start",
                blocking_reasons=reasons,
            )


def approve_npi(tx, context, command):
    npi = own(tx, "npis", context.project_id, command.npi_id)
    reasons = blockers(tx, context.project_id, npi)
    if reasons:
        raise DomainError(
            "PRECONDITION_FAILED", 409, "NPI approval blocked", blocking_reasons=reasons
        )
    append(
        tx,
        context,
        npi["id"],
        "approval",
        {"generation": npi["generation"], "evidence": command.evidence},
    )
    return result("npi", npi["id"])


def authorize(actor, command):
    """Public-publication policy is live even when returning an idempotent receipt."""
    if (
        isinstance(command, PublishAsset)
        and command.public_content is not None
        and not actor.configuration_admin
    ):
        raise DomainError(
            "FORBIDDEN",
            403,
            "Public asset publication requires configuration administrator approval",
        )


def publish_asset(tx, context, command):
    authorize(context.actor, command)
    issue = own(tx, "npi_issues", context.project_id, command.issue_id)
    npi = own(tx, "npis", context.project_id, issue["npi_id"])
    if not issue["resolution_json"] or not resolution_valid(
        tx, context.project_id, npi, json.loads(issue["resolution_json"])["test_ids"]
    ):
        fail("Asset publication requires a resolved verified NPI issue")
    if npi["product_family"] not in command.content.product_families:
        fail("Asset applicability must include its validated source product family")
    if (
        command.public_content is not None
        and npi["product_family"] not in command.public_content.product_families
    ):
        fail("Public asset applicability must include its validated product family")
    revision = 1
    if command.supersedes_id:
        prior = own(tx, "reusable_assets", context.project_id, command.supersedes_id)
        prior_content = json.loads(prior["content_json"])
        if (
            prior_content["category"] != command.content.category
            or prior["issue_id"] != issue["id"]
        ):
            fail("Asset revision must preserve its source issue and category")
        if tx.execute(
            "SELECT 1 FROM reusable_assets WHERE supersedes_id=?", (prior["id"],)
        ).fetchone():
            fail("Asset revision already superseded")
        revision = prior["revision"] + 1
    ident = str(uuid4())
    tx.execute(
        "INSERT INTO reusable_assets(id,project_id,issue_id,content_json,public_content_json,supersedes_id,revision,published_by,published_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            ident,
            str(context.project_id),
            issue["id"],
            command.content.model_dump_json(),
            command.public_content.model_dump_json()
            if command.public_content
            else None,
            str(command.supersedes_id) if command.supersedes_id else None,
            revision,
            str(context.actor.user_id),
            context.now.isoformat(),
        ),
    )
    return result("reusable_asset", ident)


def apply_asset(tx, context, command):
    npi = own(tx, "npis", context.project_id, command.npi_id)
    # Query itself filters the visibility boundary; denied/nonexistent IDs have identical errors.
    asset = tx.execute(
        "SELECT * FROM reusable_assets WHERE id=? AND (project_id=? OR public_content_json IS NOT NULL)",
        (str(command.asset_revision_id), str(context.project_id)),
    ).fetchone()
    if not asset:
        raise DomainError("NOT_FOUND", 404, "Workflow resource not found")
    snapshot = (
        asset["content_json"]
        if asset["project_id"] == str(context.project_id)
        else asset["public_content_json"]
    )
    if npi["product_family"] not in json.loads(snapshot)["product_families"]:
        fail("Asset is not applicable to the target product family")
    if tx.execute(
        "SELECT 1 FROM asset_uses WHERE npi_id=? AND asset_revision_id=?",
        (npi["id"], asset["id"]),
    ).fetchone():
        fail("Asset revision already adopted by this NPI")
    ident = str(uuid4())
    tx.execute(
        "INSERT INTO asset_uses VALUES (?,?,?,?,?,?,?,?)",
        (
            ident,
            str(context.project_id),
            npi["id"],
            asset["id"],
            asset["revision"],
            snapshot,
            int(command.required),
            context.now.isoformat(),
        ),
    )
    bump(tx, context.project_id, npi["id"])
    return result("asset_use", ident)


def verify_asset(tx, context, command):
    use = own(tx, "asset_uses", context.project_id, command.asset_use_id)
    ident = str(uuid4())
    payload = {
        "id": ident,
        "decision": command.decision,
        "evidence": command.evidence,
        "actor_id": str(context.actor.user_id),
        "recorded_at": context.now.isoformat(),
    }
    tx.execute(
        "INSERT INTO asset_verifications(id,project_id,asset_use_id,payload_json) VALUES (?,?,?,?)",
        (ident, str(context.project_id), use["id"], dump(payload)),
    )
    bump(tx, context.project_id, use["npi_id"])
    return result("asset_use", use["id"])


TABLES = {
    "npi": "npis",
    "npi_issue": "npi_issues",
    "reusable_asset": "reusable_assets",
    "asset_use": "asset_uses",
}
MODELS = {
    "npi": NPI,
    "npi_issue": NPIIssue,
    "reusable_asset": ReusableAsset,
    "asset_use": AssetUse,
}


def value(tx, pid, kind, row):
    if kind == "npi":
        approvals = records(tx, pid, row["id"], "approval")
        reasons = bulk_reasons(tx, pid, row)
        return NPI(
            revision_id=row["revision_id"],
            product_family=row["product_family"],
            scenario=row["scenario"],
            required_checks=json.loads(row["required_checks_json"]),
            work_order_ids=[
                r[0]
                for r in tx.execute(
                    "SELECT work_order_id FROM npi_work_orders WHERE project_id=? AND npi_id=? ORDER BY work_order_id",
                    (str(pid), row["id"]),
                )
            ],
            state="approved" if approvals else "open",
            bulk_eligible=not reasons,
            blocking_reasons=reasons,
            reviews=records(tx, pid, row["id"], "review"),
            trials=trial_views(tx, pid, row),
            approvals=approvals,
        )
    if kind == "npi_issue":
        return NPIIssue(
            npi_id=row["npi_id"],
            **json.loads(row["payload_json"]),
            state="resolved" if row["resolution_json"] else "open",
            resolution=json.loads(row["resolution_json"])
            if row["resolution_json"]
            else None,
        )
    if kind == "reusable_asset":
        return ReusableAsset(
            issue_id=row["issue_id"],
            content=json.loads(row["content_json"]),
            public_content=json.loads(row["public_content_json"])
            if row["public_content_json"]
            else None,
            supersedes_id=row["supersedes_id"],
            revision=row["revision"],
            published_by=row["published_by"],
            published_at=row["published_at"],
        )
    return AssetUse(
        npi_id=row["npi_id"],
        asset_revision_id=row["asset_revision_id"],
        revision=row["revision"],
        snapshot=json.loads(row["snapshot_json"]),
        required=bool(row["required"]),
        verifications=verification_records(tx, pid, row["id"]),
    )


def summary(tx, pid, kind, row):
    data = value(tx, pid, kind, row)
    title = (
        data.product_family
        if kind == "npi"
        else (
            data.phenomenon
            if kind == "npi_issue"
            else data.content.title
            if kind == "reusable_asset"
            else data.snapshot.title
        )
    )
    state = (
        data.state
        if kind in {"npi", "npi_issue"}
        else "published"
        if kind == "reusable_asset"
        else (data.verifications[-1].decision if data.verifications else "pending")
    )
    return ObjectSummary(
        id=row["id"],
        project_id=pid,
        kind=kind,
        title=title,
        state=state,
        version=data.revision if kind in {"reusable_asset", "asset_use"} else 1,
        blocking_reasons=data.blocking_reasons if kind == "npi" else [],
    )


def page_reader(kind):
    def page(tx, pid, limit, offset):
        return [
            summary(tx, pid, kind, r)
            for r in tx.execute(
                f"SELECT * FROM {TABLES[kind]} WHERE project_id=? ORDER BY rowid LIMIT ? OFFSET ?",
                (str(pid), limit, offset),
            )
        ]

    return page


def detail_reader(kind):
    def detail(tx, pid, ident):
        row = tx.execute(
            f"SELECT * FROM {TABLES[kind]} WHERE project_id=? AND id=?",
            (str(pid), str(ident)),
        ).fetchone()
        if not row:
            return None
        data = value(tx, pid, kind, row)
        relations = []
        if kind == "npi":
            relations.append(
                ObjectRelation(
                    relation="fixed_revision",
                    project_id=pid,
                    kind="revision",
                    id=data.revision_id,
                )
            )
        elif kind in {"npi_issue", "asset_use"}:
            relations.append(
                ObjectRelation(
                    relation="introduction", project_id=pid, kind="npi", id=data.npi_id
                )
            )
        elif kind == "reusable_asset":
            relations.append(
                ObjectRelation(
                    relation="source_issue",
                    project_id=pid,
                    kind="npi_issue",
                    id=data.issue_id,
                )
            )
        # Cross-project adoption never projects a source relation, history or source payload.
        return ObjectDetail[MODELS[kind]](
            summary=summary(tx, pid, kind, row),
            value=data,
            relations=relations,
            evidence=[],
            history=_history(tx, pid, ident),
        )

    return detail


def public_catalog(tx, limit, offset):
    rows = tx.execute(
        "SELECT id,revision,public_content_json FROM reusable_assets WHERE public_content_json IS NOT NULL ORDER BY seq LIMIT ? OFFSET ?",
        (limit, offset),
    )
    return PublicAssetPage(
        items=[
            PublicAssetEntry(
                asset_revision_id=r["id"],
                revision=r["revision"],
                content=json.loads(r["public_content_json"]),
            )
            for r in rows
        ],
        total=tx.execute(
            "SELECT COUNT(*) FROM reusable_assets WHERE public_content_json IS NOT NULL"
        ).fetchone()[0],
        limit=limit,
        offset=offset,
    )


def register():
    for model, handler, roles in (
        (OpenNPI, open_npi, {"engineering"}),
        (ReviewNPI, review_npi, {"engineering"}),
        (TrialNPI, trial_npi, {"engineering"}),
        (IssueNPI, issue_npi, {"engineering", "quality"}),
        (ResolveNPI, resolve_npi, {"engineering", "quality"}),
        (ApproveNPI, approve_npi, {"project_owner"}),
        (PublishAsset, publish_asset, {"engineering"}),
        (ApplyAsset, apply_asset, {"engineering"}),
        (VerifyAsset, verify_asset, {"engineering", "quality"}),
    ):
        COMMAND_REGISTRY.register(
            model, roles=roles, qualifications=set(), handler=handler
        )
    for kind, model in MODELS.items():
        OBJECT_REGISTRY.register(
            ObjectKind(kind),
            model,
            count=count(TABLES[kind]),
            summaries=page_reader(kind),
            detail=detail_reader(kind),
        )


register()
