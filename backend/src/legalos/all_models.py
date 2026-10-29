"""Import every model module, so SQLAlchemy can resolve foreign keys between them.

Entrypoints that don't import the API routers (the worker, scripts) must import this.
"""

from legalos.audit import models as audit_models
from legalos.auth import models as auth_models
from legalos.documents import models as documents_models
from legalos.jobs import models as jobs_models
from legalos.matters import models as matters_models
from legalos.tenancy import models as tenancy_models

__all__ = [
    "audit_models",
    "auth_models",
    "documents_models",
    "jobs_models",
    "matters_models",
    "tenancy_models",
]
