import asyncio
import uvicorn

from backend.app.main import app
from backend.app.admin_app import admin_app
from backend.app.config import settings

async def main():
    config_api = uvicorn.Config(app, host=settings.HOST, port=settings.PORT, log_level=settings.LOG_LEVEL.lower())
    config_admin = uvicorn.Config(admin_app, host=settings.HOST, port=settings.ADMIN_WS_PORT, log_level=settings.LOG_LEVEL.lower())

    server_api = uvicorn.Server(config_api)
    server_admin = uvicorn.Server(config_admin)

    await asyncio.gather(server_api.serve(), server_admin.serve())

if __name__ == "__main__":
    asyncio.run(main())