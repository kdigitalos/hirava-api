"""Model registration for Alembic. Domain routes use service contracts for cross-domain writes."""
from app.core.models import *  # noqa: F403
from app.modules.organization.models import *  # noqa: F403
from app.modules.recruiting.models import *  # noqa: F403
from app.modules.interviews.models import *  # noqa: F403
from app.modules.offers.models import *  # noqa: F403
from app.modules.workforce.models import *  # noqa: F403
from app.modules.conversion.models import *  # noqa: F403
from app.modules.leave.models import *  # noqa: F403
from app.modules.hr_service.models import *  # noqa: F403
from app.modules.performance.models import *  # noqa: F403
from app.modules.learning.models import *  # noqa: F403
