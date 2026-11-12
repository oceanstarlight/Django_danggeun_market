"""신고/차단 서비스."""

from django.db import IntegrityError, transaction
from django.db.models import Q

from .models import Block, Report


def blocked_user_ids(user) -> set[int]:
    """내가 차단했거나 나를 차단한 사용자 id 집합."""
    if not getattr(user, "is_authenticated", False):
        return set()
    ids = set()
    for blocker_id, blocked_id in Block.objects.filter(Q(blocker=user) | Q(blocked=user)).values_list(
        "blocker_id", "blocked_id"
    ):
        ids.add(blocked_id if blocker_id == user.pk else blocker_id)
    ids.discard(user.pk)
    return ids


def is_blocked_between(a, b) -> bool:
    """두 사용자 사이에 어느 방향이든 차단이 있으면 True."""
    if a is None or b is None or not getattr(a, "pk", None) or not getattr(b, "pk", None):
        return False
    return Block.objects.filter(Q(blocker=a, blocked=b) | Q(blocker=b, blocked=a)).exists()


# ───────── 쓰기 서비스 (accounts/moderation UI) ─────────
class ModerationError(Exception):
    """사용자에게 보여줄 수 있는 신고/차단 오류."""


def has_blocked(blocker, blocked) -> bool:
    """blocker 가 blocked 를 차단했는지 (한 방향)."""
    if not getattr(blocker, "is_authenticated", False) or blocked is None:
        return False
    return Block.objects.filter(blocker=blocker, blocked=blocked).exists()


def block_user(blocker, blocked) -> Block:
    if blocker.pk == blocked.pk:
        raise ModerationError("나 자신은 차단할 수 없어요.")
    try:
        with transaction.atomic():
            block, _ = Block.objects.get_or_create(blocker=blocker, blocked=blocked)
    except IntegrityError:  # 동시 요청
        block = Block.objects.get(blocker=blocker, blocked=blocked)
    return block


def unblock_user(blocker, blocked) -> bool:
    """차단을 해제한다. 해제한 게 있으면 True."""
    deleted, _ = Block.objects.filter(blocker=blocker, blocked=blocked).delete()
    return deleted > 0


def toggle_block(blocker, blocked) -> bool:
    """차단 상태를 뒤집고, 이제 차단 중이면 True 를 돌려준다."""
    if unblock_user(blocker, blocked):
        return False
    block_user(blocker, blocked)
    return True


def create_report(reporter, *, reason, detail="", product=None, reported_user=None) -> Report:
    """상품 또는 사용자를 신고한다. 같은 대상에 접수 중인 신고가 있으면 ModerationError."""
    if product is None and reported_user is None:
        raise ModerationError("신고할 대상을 찾을 수 없어요.")
    if product is not None:
        if product.seller_id == reporter.pk:
            raise ModerationError("내 상품은 신고할 수 없어요.")
        reported_user = reported_user or product.seller
    if reported_user is not None and reported_user.pk == reporter.pk:
        raise ModerationError("나 자신은 신고할 수 없어요.")

    pending = Report.objects.filter(reporter=reporter, status=Report.Status.PENDING)
    if product is not None:
        pending = pending.filter(product=product)
    else:
        pending = pending.filter(product__isnull=True, reported_user=reported_user)
    if pending.exists():
        raise ModerationError("이미 신고했어요. 운영팀이 확인하고 있어요.")

    return Report.objects.create(
        reporter=reporter,
        product=product,
        reported_user=reported_user,
        reason=reason,
        detail=(detail or "").strip(),
    )
