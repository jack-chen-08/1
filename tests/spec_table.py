"""需求原文的**人工转写**预期表。

刻意不复用 kb.policy 里的矩阵常量：如果测试从实现里取预期，
实现改错了测试也会跟着错（自证循环）。这里的每一条都能在需求原文里找到出处。
"""

from __future__ import annotations

# 需求原文：「员工按岗位与会所过滤」
ROLES = ["staff", "senior_staff", "supervisor", "site_manager", "org_admin"]

# 需求原文：「5 个岗位 × 6 个知识类别」
CATEGORIES = ["sop", "training", "marketing", "faq", "policy", "pricing"]

# 需求原文：「价格与政策类只对主管及以上开放」
RESTRICTED_CATEGORIES = ["policy", "pricing"]

# 需求原文的「主管及以上」＝ supervisor 及以上三个岗位
SUPERVISOR_AND_ABOVE = ["supervisor", "site_manager", "org_admin"]


def expected_visible(role: str, category: str) -> bool:
    """5×6 = 30 个格子的预期可见性。"""
    if category in RESTRICTED_CATEGORIES:
        return role in SUPERVISOR_AND_ABOVE
    return True


def expected_matrix() -> dict[tuple[str, str], bool]:
    return {(r, c): expected_visible(r, c) for r in ROLES for c in CATEGORIES}


# 验收标准第 2 条要求的「50 条虚构查询」。
# 全部为构造词，落在虚构文档正文里，用于验证会员上下文召回中内部切片数为 0。
MEMBER_QUERIES = [
    "入会流程说明", "会员权益清单", "场地预约规则", "会议室使用办法", "前台接待话术",
    "停车位申请指引", "访客登记要求", "会员卡补办流程", "活动报名方式", "发票开具说明",
    "服务台开放时间", "茶水间使用规范", "打印复印收费", "快递代收须知", "包裹领取流程",
    "会员等级说明", "积分兑换规则", "续费提醒口径", "退会处理流程", "投诉受理通道",
    "保洁巡检标准", "空调温度设定", "网络接入指引", "门禁卡申领", "储物柜租用办法",
    "路演厅预订须知", "直播间使用规范", "洽谈区预约流程", "共享工位说明", "独立办公室配置",
    "会员日安排", "社群加入方式", "导师预约流程", "政策宣讲会报名", "财税咨询预约",
    "法律咨询排期", "投融资对接流程", "供应链撮合说明", "品牌露出申请", "展位申请办法",
    "会员名录收录规则", "服务满意度回访", "设施报修通道", "应急疏散指引", "吸烟区位置",
    "宠物入内规定", "儿童看护说明", "餐饮配套说明", "停车月卡办理", "会员专属通道",
]
