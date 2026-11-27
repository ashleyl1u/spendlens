from fastapi import APIRouter

from ..categorization.categories import CATEGORIES

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("", response_model=list[str])
def list_categories() -> list[str]:
    """The fixed spending categories, in display order. Public: it is the same for
    everyone, and clients use it so their dropdowns can't drift from the backend."""
    return list(CATEGORIES)
