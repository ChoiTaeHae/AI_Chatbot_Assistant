from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import FRONTEND_ORIGINS
from core.Database import Base, engine
from api import ROUTERS
from services import start_periodic_stats_save


def create_app():
    app = FastAPI()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=FRONTEND_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for router in ROUTERS:
        app.include_router(router)

    @app.on_event("startup")
    def on_startup():
        Base.metadata.create_all(bind=engine)
        start_periodic_stats_save()

    return app