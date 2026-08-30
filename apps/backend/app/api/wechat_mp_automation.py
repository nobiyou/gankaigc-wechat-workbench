from __future__ import annotations

from fastapi import APIRouter, Query, status

from app.schemas.wechat_mp_automation import (
    AutomationCycleResponse,
    AutomationSubscriptionCreate,
    AutomationSubscriptionUpdate,
)
from app.services.wechat_mp_automation import (
    create_subscription,
    disable_subscription,
    get_run,
    get_subscription,
    list_runs,
    list_subscriptions,
    retry_run,
    run_due_cycle,
    submit_run_in_background,
)


router = APIRouter(prefix="/wechat-mp/automation", tags=["wechat-mp-automation"])


@router.get("/subscriptions")
def get_automation_subscriptions() -> list[dict[str, object]]:
    return [item.model_dump() for item in list_subscriptions()]


@router.post("/subscriptions", status_code=status.HTTP_201_CREATED)
def post_automation_subscription(payload: AutomationSubscriptionCreate) -> dict[str, object]:
    return create_subscription(payload).model_dump()


@router.get("/subscriptions/{subscription_id}")
def get_automation_subscription(subscription_id: int) -> dict[str, object]:
    return get_subscription(subscription_id).model_dump()


@router.patch("/subscriptions/{subscription_id}")
def patch_automation_subscription(
    subscription_id: int,
    payload: AutomationSubscriptionUpdate,
) -> dict[str, object]:
    from app.services.wechat_mp_automation import update_subscription

    return update_subscription(subscription_id, payload).model_dump()


@router.delete("/subscriptions/{subscription_id}")
def delete_automation_subscription(subscription_id: int) -> dict[str, object]:
    return disable_subscription(subscription_id).model_dump()


@router.get("/runs")
def get_automation_runs(
    subscription_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[dict[str, object]]:
    return [item.model_dump() for item in list_runs(subscription_id=subscription_id, limit=limit)]


@router.get("/runs/{run_id}")
def get_automation_run(run_id: int) -> dict[str, object]:
    return get_run(run_id).model_dump()


@router.post("/subscriptions/{subscription_id}/runs", status_code=status.HTTP_202_ACCEPTED)
def post_automation_run(subscription_id: int) -> dict[str, object]:
    return submit_run_in_background(subscription_id).model_dump()


@router.post("/runs/{run_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def post_automation_run_retry(run_id: int) -> dict[str, object]:
    return retry_run(run_id).model_dump()


@router.post("/cycle", response_model=AutomationCycleResponse)
def post_automation_cycle() -> dict[str, object]:
    return run_due_cycle().model_dump()
