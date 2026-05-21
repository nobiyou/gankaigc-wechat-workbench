from fastapi import APIRouter

from app.api import background_tasks, dashboard, health, projects, tone_profiles, topics, tracked_articles, trends, wechat_mp

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(dashboard.router)
api_router.include_router(background_tasks.router)
api_router.include_router(trends.router)
api_router.include_router(tracked_articles.router)
api_router.include_router(wechat_mp.router)
api_router.include_router(topics.router)
api_router.include_router(projects.router)
api_router.include_router(tone_profiles.router)
