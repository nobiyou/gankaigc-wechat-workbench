from fastapi import APIRouter

from app.schemas.tone_profiles import ToneProfileReorder, ToneProfileUpsert
from app.services.workbench import (
    activate_tone_profile,
    create_tone_profile,
    delete_tone_profile,
    duplicate_tone_profile,
    list_tone_profiles,
    reorder_tone_profiles,
    update_tone_profile,
)

router = APIRouter(prefix="/tone-profiles", tags=["tone-profiles"])


@router.get("")
def get_tone_profiles() -> list[dict[str, object]]:
    return [profile.model_dump() for profile in list_tone_profiles()]


@router.post("", status_code=201)
def post_tone_profile(payload: ToneProfileUpsert) -> dict[str, object]:
    return create_tone_profile(payload).model_dump()


@router.patch("/{profile_id}")
def patch_tone_profile(profile_id: int, payload: ToneProfileUpsert) -> dict[str, object]:
    return update_tone_profile(profile_id, payload).model_dump()


@router.post("/{profile_id}/activate")
def post_activate_tone_profile(profile_id: int) -> dict[str, object]:
    return activate_tone_profile(profile_id).model_dump()


@router.post("/{profile_id}/duplicate", status_code=201)
def post_duplicate_tone_profile(profile_id: int) -> dict[str, object]:
    return duplicate_tone_profile(profile_id).model_dump()


@router.post("/reorder")
def post_reorder_tone_profiles(payload: ToneProfileReorder) -> list[dict[str, object]]:
    return [profile.model_dump() for profile in reorder_tone_profiles(payload)]


@router.delete("/{profile_id}")
def delete_tone_profile_route(profile_id: int) -> dict[str, int]:
    return delete_tone_profile(profile_id)
