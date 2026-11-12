"""Firm roles and what each one may do.

Roles are per firm (a person may be sócio in one firm and advogado in another).
The backend checks permissions on every request; the UI only hides what is already denied.
"""

from enum import StrEnum


class Role(StrEnum):
    SOCIO = "socio"
    ADVOGADO = "advogado"
    ESTAGIARIO = "estagiario"
    ADMINISTRATIVO = "administrativo"


class Permission(StrEnum):
    MANAGE_FIRM = "manage_firm"
    MANAGE_MEMBERS = "manage_members"
    VIEW_AUDIT_LOG = "view_audit_log"
    VIEW_MEMBERS = "view_members"
    VIEW_MATTERS = "view_matters"
    MANAGE_CLIENTS = "manage_clients"
    MANAGE_DOCUMENTS = "manage_documents"
    MANAGE_TASKS = "manage_tasks"
    VIEW_AI_OUTPUTS = "view_ai_outputs"
    DRAFT_AI_OUTPUTS = "draft_ai_outputs"
    # Approving consequential AI outputs and confirming prazos is reserved to lawyers
    # (brief §2, rule 2). For the MVP this applies to any processo in the firm.
    APPROVE_AI_OUTPUTS = "approve_ai_outputs"
    CONFIRM_DEADLINES = "confirm_deadlines"


_LAWYER_WORK = {
    Permission.VIEW_MEMBERS,
    Permission.VIEW_MATTERS,
    Permission.MANAGE_CLIENTS,
    Permission.MANAGE_DOCUMENTS,
    Permission.MANAGE_TASKS,
    Permission.VIEW_AI_OUTPUTS,
    Permission.DRAFT_AI_OUTPUTS,
}

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.SOCIO: frozenset(Permission),
    Role.ADVOGADO: frozenset(
        _LAWYER_WORK | {Permission.APPROVE_AI_OUTPUTS, Permission.CONFIRM_DEADLINES}
    ),
    Role.ESTAGIARIO: frozenset(_LAWYER_WORK),
    Role.ADMINISTRATIVO: frozenset(
        {
            Permission.VIEW_MEMBERS,
            Permission.VIEW_MATTERS,
            Permission.MANAGE_CLIENTS,
            Permission.MANAGE_DOCUMENTS,
            Permission.MANAGE_TASKS,
        }
    ),
}


def has_permission(role: Role, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS[role]
