"""权限矩阵子包。"""

from crm.permissions.matrix_loader import Matrix, RolePolicy, get_matrix, load_matrix
from crm.permissions.scope import (
    apply_amount_visibility,
    apply_opportunity_scope,
    get_visible_opportunity,
    scoped_select,
    serialize_opportunity,
    serialize_summary,
)

__all__ = [
    "Matrix",
    "RolePolicy",
    "get_matrix",
    "load_matrix",
    "apply_amount_visibility",
    "apply_opportunity_scope",
    "get_visible_opportunity",
    "scoped_select",
    "serialize_opportunity",
    "serialize_summary",
]
