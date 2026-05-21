from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "apps" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.settings import settings
from app.services.workbench import (  # noqa: E402
    build_publish_package,
    create_project_from_topic,
    generate_assets,
    generate_draft,
    generate_outline,
    generate_topic_from_trend,
    get_project_detail,
    initialize_store,
)
from app.schemas.projects import ProjectCreate  # noqa: E402


def main() -> int:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    initialize_store(reset=True)

    topic = generate_topic_from_trend("office-burnout-recovery")
    project = create_project_from_topic(
        topic.slug,
        ProjectCreate(
            slug=f"{topic.slug}-live-project",
            title=f"{topic.title} Live Smoke Project",
            owner="live-smoke",
            preferred_tone_profile_id=None,
        ),
    )
    outline = generate_outline(project.slug)
    draft = generate_draft(project.slug)
    assets = generate_assets(project.slug)
    publish_package = build_publish_package(project.slug)
    detail = get_project_detail(project.slug)

    result = {
      "topic": topic.model_dump(),
      "project": project.model_dump(),
      "outline": outline.model_dump(),
      "draft": {
        "project_slug": draft.project_slug,
        "version": draft.version,
        "title": draft.title,
        "word_count": draft.word_count,
      },
      "assets": {
        "project_slug": assets.project_slug,
        "version": assets.version,
        "title_options": assets.title_options,
        "cover_copy": assets.cover_copy,
        "cover_image_url": assets.cover_image_url,
      },
      "publish_package": {
        "project_slug": publish_package.project_slug,
        "version": publish_package.version,
        "abstract": publish_package.abstract,
        "tags": publish_package.tags,
        "manifest_url": publish_package.manifest_url,
        "markdown_url": publish_package.markdown_url,
      },
      "detail": detail.model_dump(),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
