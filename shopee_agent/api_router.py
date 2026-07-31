"""API versioning support for Laura dashboard."""

from fastapi import APIRouter, FastAPI

API_VERSIONS = ["v1", "v2"]


class VersionedRouter:
    """Provides versioned API routing with fallback."""

    def __init__(self, app: FastAPI):
        self.app = app
        self.routers: dict[str, APIRouter] = {}
        for version in API_VERSIONS:
            self.routers[version] = APIRouter(prefix=f"/api/{version}")

    def get_router(self, version: str = "v1") -> APIRouter:
        """Get router for a specific API version."""
        if version not in self.routers:
            raise ValueError(f"Unsupported API version: {version}. Available: {API_VERSIONS}")
        return self.routers[version]

    def include_all(self) -> None:
        """Include all versioned routers in the app."""
        for router in self.routers.values():
            self.app.include_router(router)

    @property
    def latest(self) -> str:
        return API_VERSIONS[-1]
