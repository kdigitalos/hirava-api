from app.core.routing import APIRouter

from app.api.v1.health import router as health_router
from app.api.v1.reports import router as reports_router
from app.core.router import router as core_router
from app.modules.organization.router import router as organization_router
from app.modules.recruiting.router import router as recruiting_router
from app.modules.recruiting.careers import router as careers_router
from app.modules.interviews.router import router as interviews_router
from app.modules.offers.router import router as offers_router
from app.modules.conversion.router import router as conversion_router
from app.modules.workforce.router import router as workforce_router
from app.modules.workforce.profile import router as profile_router
from app.modules.leave.router import router as leave_router
from app.modules.hr_service.router import router as hr_service_router
from app.modules.performance.router import router as performance_router
from app.modules.learning.router import router as learning_router

api_router = APIRouter()
api_router.include_router(health_router)
for router in (core_router, organization_router, recruiting_router, interviews_router, offers_router,
               conversion_router, workforce_router, leave_router, hr_service_router, performance_router,
               learning_router, reports_router, careers_router, profile_router):
    api_router.include_router(router)
