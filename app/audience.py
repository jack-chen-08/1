"""audience → 活动可见范围 的唯一映射表。

需求原文：member_only→会员专享、public→公开、invite_only→闭门会。
活动模块的字段取值以「活动模块工单」为准；若对方 token 不同，只改这一张表。
"""

from __future__ import annotations

AUDIENCE_TO_ACTIVITY_VISIBILITY: dict[str, str] = {
    "member_only": "members_only",   # 会员专享
    "public": "public",              # 公开
    "invite_only": "closed_door",     # 闭门会
}

AUDIENCE_LABELS_ZH: dict[str, str] = {
    "member_only": "会员专享",
    "public": "公开",
    "invite_only": "闭门会",
}


class UnknownAudience(ValueError):
    pass


def activity_visibility(audience: str) -> str:
    try:
        return AUDIENCE_TO_ACTIVITY_VISIBILITY[audience]
    except KeyError as exc:  # 未知取值一律拒绝，不做兜底映射
        raise UnknownAudience(audience) from exc
