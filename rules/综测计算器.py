# -*- coding: utf-8 -*-
"""综测计算器（v3）：把规则卡的口径做成可跑的最小实现。

口径来源（逐条对着原文写，不做近似）：
  S2《中南财经政法大学本科学生奖学金综合评价体系实施办法》
  S3《校发-附件2-本科学生能力评价测评计分标准》正文表 + 附表说明 (1)-(8)

用法：
  python 综测计算器.py 个人情况.json      # 算一个人
  python 综测计算器.py --selftest        # 自检（含与官方原文逐句对账）
  python 综测计算器.py --dump-table      # 打印内置分值表
  python 综测计算器.py --judge "数学建模 省二等奖"      # 只判定一个比赛
  python 综测计算器.py --judge --tongshu "美赛 M 奖"   # 按统数口径判定
  python 综测计算器.py --judge-file 描述.txt           # 每行一条，批量判定
  python 综测计算器.py --draft "挑战杯校赛金奖" "数模省二 3人"
                                            # 口语描述 → 成果 JSON（可直接粘进个人情况）
  python 综测计算器.py --draft-file 描述.txt            # 批量版

只用标准库，不装依赖。
"""
import csv
import json
import os
import re
import sys

CAP = 100.0                    # 附表说明(1)：能力评价各指标总得分最高 100
F1_ITEMS = ["A1思想政治", "A2道德品质", "A3组织纪律", "A4身心健康"]   # 各基准 25，只减不加
WEIGHTS = {"B1科研创新": 0.35, "B2专业技能": 0.15, "B3文体特长": 0.15,
           "B4社会工作": 0.10, "B5社会实践": 0.25}
TOTAL_W = {"基本素质": 0.15, "知识水平": 0.55, "能力评价": 0.30}
LEVELS = ["国家级", "省级", "校级", "院级"]

SUBS = {
    "B1科研创新": ["学术竞赛", "学术论文", "发明专利", "学术科研"],
    "B2专业技能": ["技能竞赛", "技能证书"],
    "B3文体特长": ["文艺赛事", "体育赛事", "文化知识竞赛"],
    "B4社会工作": ["团学活动", "志愿服务"],
    "B5社会实践": ["社会实践"],
}
SUB2DIM = {s: d for d, ss in SUBS.items() for s in ss}

# ── 分值表 ───────────────────────────────────────────────────────────────
# 形状 A：(子类, 级别) → 按"档位"取；档位含义见各子类注释
TIERED = {
    # 档位 = 奖项等级 1/2/3/4（一二三等、优秀奖）
    ("学术竞赛", "国家级"): "30/25/22/20", ("学术竞赛", "省级"): "20/15/12/10",
    ("学术竞赛", "校级"): "10/8/6/5",     ("学术竞赛", "院级"): "5/3/2/1",
    ("技能竞赛", "国家级"): "30/25/22/20", ("技能竞赛", "省级"): "20/15/12/10",
    ("技能竞赛", "校级"): "10/8/6/5",     ("技能竞赛", "院级"): "5/3/2/1",
    ("文艺赛事", "国家级"): "30/25/22/20", ("文艺赛事", "省级"): "20/15/12/10",
    ("文艺赛事", "校级"): "10/8/6/5",     ("文艺赛事", "院级"): "5/3/2/1",
    ("文化知识竞赛", "国家级"): "30/25/22/20", ("文化知识竞赛", "省级"): "20/15/12/10",
    ("文化知识竞赛", "校级"): "10/8/6/5",  ("文化知识竞赛", "院级"): "5/3/2/1",
    # 档位 = 名次 1..8（原文只列一至八名）
    ("体育赛事", "国家级"): "30/25/20/15/15/10/10/10",
    ("体育赛事", "省级"): "20/15/10/8/8/4/4/4",
    ("体育赛事", "校级"): "10/8/7/6/6/2/2/2",
    ("体育赛事", "院级"): "7/6/4/3/3/1/1/1",
    # 档位 = 作者位次 1独撰·2合著第一·3第二·4第三以后
    ("学术论文", "一类"): "30/20/15/8", ("学术论文", "二类"): "20/15/10/5",
    ("学术论文", "三类"): "15/10/5/3", ("学术论文", "四类"): "10/5/3/2",
    ("学术论文", "一般"): "5/3/2/1",
    # 档位 = 申报排序 1第一负责人·2第二·3第三以后
    ("学术科研", "国家级"): "20/15/8", ("学术科研", "省级"): "15/10/5",
    ("学术科研", "校级"): "10/5/3",   ("学术科研", "院级"): "5/3/2",
    # 级别取自专利类型，单值
    ("发明专利", "国家发明专利"): "20", ("发明专利", "实用新型"): "4", ("发明专利", "外观设计"): "2",
    # 档位 = 认定级别 1高级·2中级·3初级（三类证书同值）
    ("技能证书", "高级"): "10", ("技能证书", "中级"): "5", ("技能证书", "初级"): "3",
}
# 形状 B：(子类, 类别) → 按"级别"序号取（国家/省/校/院 四级）
LEVEL_KEYED = {
    ("团学活动", "优秀学生干部"): "30/20/10/5",
    ("团学活动", "优秀学生组织主要负责人"): "15/10/6/3",
    ("团学活动", "团学先进个人"): "20/15/8/4",
    ("志愿服务", "先进个人"): "30/20/10/5",
    ("志愿服务", "优秀团队"): "30/20/10/5",
    ("社会实践", "先进个人"): "30/20/10/5",
    ("社会实践", "团队"): "30/20/10/5",
    ("社会实践", "调查报告"): "25/15/8/4",
}

# ── 集体项目（附表说明 4）三句话拆成三套策略 ────────────────────────────
ALWAYS_HALF = {"文艺赛事", "体育赛事"}          # 集体项目（n>=2）一律减半；个人项目 n<=1 不减半
POSITION_IS_TIER = {"学术论文", "发明专利", "技能证书"}  # 位次已含在档位里
ORDERED = {"学术科研"}                          # 按申报排序取档，不减半
NO_TEAM = {"团学活动"}                          # 个人称号，不适用集体折算
# 其余（学术竞赛/技能竞赛/文化知识竞赛/志愿服务/社会实践）走通用句：
#   n<=1 不加人数限制；n<=5 各成员减半；n>5 仅主要负责人减半，其他不加

# 未获奖参与分：竞赛类须"经学院及以上选拔推荐"，志愿/实践只需参加证明
SELECTED_ONLY = {"学术竞赛", "技能竞赛", "文艺赛事", "体育赛事", "文化知识竞赛", "学术科研"}
PROOF_ONLY = {"志愿服务", "社会实践"}
PARTICIPATION_UNIT = 0.5
PARTICIPATION_CAP = 2.0


def _vals(s):
    return [float(x) for x in s.split("/")]


def tier_of(award):
    """附表说明(5)：奖项写法 → 档位 1..4。名次按 1/2-3/4-6/7+ 折档。"""
    s = str(award).strip()
    m = re.search(r"第\s*(\d+)\s*名", s)
    if m:
        n = int(m.group(1))
        return 1 if n == 1 else 2 if n <= 3 else 3 if n <= 6 else 4
    if re.search(r"优秀", s):
        return 4                                  # 优秀奖就是第四档
    if re.search(r"优胜|入围|佳作|未分等级|不分等级", s):
        return 3                                  # 不分等级按三等奖（优胜/入围/佳作同口径）
    if re.search(r"特等|金|冠军|一等", s):
        return 1                                  # 特等奖按一等奖档计
    if re.search(r"银|亚军|二等", s):
        return 2
    if re.search(r"铜|季军|三等", s):
        return 3
    return 3


def sport_pos(text):
    """体育赛事的档位是名次本身（一至八名），不能折成四档。"""
    s = str(text).strip()
    m = re.search(r"第\s*(\d+)\s*名", s)
    if m:
        return int(m.group(1))
    if re.search(r"优秀", s):
        return 8                                  # 优秀奖在体育序列里取末档
    return tier_of(s)


def author_pos(text):
    """学术论文作者位次 → 档位。独撰=1·合著第一=2·第二=3·第三以后=4（四档）。"""
    s = str(text).strip()
    if re.search(r"独撰|独立", s):
        return 1
    if re.search(r"第三|第\s*3\s*作者|^3$|以后", s):
        return 4
    if re.search(r"第二|第\s*2\s*作者|^2$", s):
        return 3
    if re.search(r"第一|第\s*1\s*作者|一作|^1$", s):
        return 2
    return 2                                     # 未写位次按合著第一，并在报告里提示核对


def rank_pos(text):
    """学术科研申报排序 → 档位。第一负责人=1·第二=2·第三以后=3（三档）。"""
    s = str(text).strip()
    if re.search(r"第三|^3$|以后", s):
        return 3
    if re.search(r"第二|^2$", s):
        return 2
    return 1                                     # 第一/主持/负责人 均取第一档


def score_of(sub, level, tier=3, cat=None):
    """取分。level 对形状 A 是级别/类型，对形状 B 是四级之一；cat 是形状 B 的类别。"""
    if sub in {"团学活动", "志愿服务", "社会实践"}:
        key = (sub, cat)
        if key not in LEVEL_KEYED:
            raise KeyError("类别缺失或未知：%s / %s" % (sub, cat))
        if level not in LEVELS:
            raise KeyError("「%s」的级别须为 国家级/省级/校级/院级 之一，收到：%r"
                           "（县级等其他级别请按学院口径折算后填入）" % (sub, level))
        idx = LEVELS.index(level)
        vals = _vals(LEVEL_KEYED[key])
        return vals[idx]
    key = (sub, level)
    if key not in TIERED:
        cand = [k for k in TIERED if k[0] == sub and level.startswith(k[1])]
        if not cand:
            raise KeyError("分值表无此项：%s / %s" % (sub, level))
        key = cand[0]
    vals = _vals(TIERED[key])
    return vals[min(max(int(tier), 1), len(vals)) - 1]


def collective(sub, raw, n, lead):
    """附表说明(4) 集体折算。n=参与人数，lead=是否项目主要负责人。"""
    if sub in POSITION_IS_TIER or sub in ORDERED or sub in NO_TEAM:
        return raw
    n = int(n or 1)
    if n <= 1:
        return raw
    if sub in ALWAYS_HALF:
        return raw / 2.0
    if n <= 5:
        return raw / 2.0
    return raw / 2.0 if lead else 0.0



# ── 比赛定级（--judge）──────────────────────────────────────────────
# 设计原则：先认赛事，再认级别，最后才给分；任何一环缺证据就降置信度或拒绝给分。
_EVENTS = None


def _db_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "赛事定级库.csv")


def load_events():
    global _EVENTS
    if _EVENTS is not None:
        return _EVENTS
    _EVENTS = []
    with open(_db_path(), encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            _EVENTS.append({
                "name": (r.get("赛事名") or "").strip(),
                "aliases": [a.strip() for a in (r.get("别名") or "").split("|") if a.strip()],
                "sub": (r.get("子类") or "").strip(),
                "hint": (r.get("级别提示") or "").strip(),
                "ts": (r.get("统数规则") or "").strip(),
                "note": (r.get("备注") or "").strip(),
            })
    return _EVENTS


def match_event(text):
    """最长别名匹配：返回 (赛事记录, 命中的别名)。"""
    best = None
    for ev in load_events():
        for a in [ev["name"]] + ev["aliases"]:
            if a and a in text:
                key = (len(a), 1 if a != ev["name"] else 0)
                if best is None or key > best[0]:
                    best = (key, ev, a)
    return (best[1], best[2]) if best else (None, None)


def guess_sub(text):
    rules = [
        ("学术科研", r"大创|创新创业训练|结项"),
        ("体育赛事", r"篮球|足球|排球|羽毛球|乒乓球|网球|游泳|田径|运动会|拔河"),
        ("文艺赛事", r"歌手|舞蹈|书画|摄影|微电影|短视频|合唱|乐器|文艺"),
        ("文化知识竞赛", r"辩论|演讲|征文|知识竞赛|答题"),
        ("技能竞赛", r"技能|职业|模拟法庭|案例分析|会计|金融|英语|翻译|程序设计|软件"),
        ("学术竞赛", r"竞赛|大赛|比赛|杯|挑战"),
    ]
    for sub, pat in rules:
        if re.search(pat, text):
            return sub
    return ""


def parse_level(rest, ev):
    """返回 (级别, 判定依据, 置信度)。显式级别词 > 主办单位 > 赛事库标注。"""
    ptn = [
        ("国家级", r"国家级|[国國]赛|全国总决赛|全国赛|国家[一二三]等奖|全国[一二三]等奖|[国國][一二三](?!等奖)"),
        ("省级", r"省级|省赛|赛区|省总决赛|湖北省|省[一二三]等奖|省[一二三](?!等奖)|省(?=[金银铜特优])"),
        ("校级", r"校级|校赛|校内|校[一二三]等奖|校(?=\s|第|内)|^校(?=[一-龥])"),
        ("院级", r"院级|院赛|院[一二三]等奖|院(?=\s|第|内|级)|^院(?=[一-龥])|学院(主办|承办|颁发|第)"),
    ]
    for lv, pat in ptn:
        m = re.search(pat, rest)
        if m:
            return lv, "描述含“%s”" % m.group(0), "高"
    if re.search(r"教育部|共青团中央|全国学联|国家体育总局|中国科协", rest):
        return "国家级", "主办单位为中央部委/全国性组织", "中"
    if re.search(r"省教育厅|省团委|团省委|省学联|省体育局", rest):
        return "省级", "主办单位为省级部门", "中"
    if re.search(r"校团委|教务处|学工部|校学生会", rest):
        return "校级", "主办单位为校内部门", "中"
    if ev and ev["hint"]:
        return ev["hint"], "赛事库标注（名称固有级别，需落款核对）", "中"
    return "", "描述未给出级别，需补充证书落款/主办单位", "低"


def parse_award(rest, ev=None):
    """返回 (档位, 名次, 奖项原文, 说明)。档位 1-4；0=参与未获奖；None=未识别。"""
    s = rest
    if re.search(r"未获奖|未获|参与|参赛未", s) and not re.search(r"[一二三]等奖|优秀奖|金奖|银奖|铜奖", s):
        return 0, None, "参与未获奖", "须经学院及以上选拔推荐才计 0.5/次"
    m = re.search(r"第\s*(\d+)\s*名", s)
    rank = int(m.group(1)) if m else None
    grade = re.search(r"特等|一等|二等|三等|金奖|银奖|铜奖|冠军|亚军|季军|优秀|优胜|入围|佳作", s)
    if not grade:
        ab = re.search(r"[国國省]([一二三])(?!等奖|名)", s)
        if ab:
            t = {"一": 1, "二": 2, "三": 3}[ab.group(1)]
            return t, rank, "%s等奖" % ab.group(1), "由“%s”缩写识别" % ab.group(0)
    if rank and not grade:
        t = 1 if rank == 1 else 2 if rank <= 3 else 3 if rank <= 6 else 4
        return t, rank, "第 %d 名" % rank, ""
    if re.search(r"特等", s):
        return 1, rank, "特等奖", "特等奖按一等奖档计"
    if re.search(r"一等|金奖|冠军|第一名|第1名", s):
        return 1, rank or 1, "一等奖/金奖", ""
    if re.search(r"二等|银奖|亚军|第二名|第2名|第3名", s):
        return 2, rank or 2, "二等奖/银奖", ""
    if re.search(r"三等|铜奖|季军|第三名|第4名|第5名|第6名", s):
        return 3, rank or 3, "三等奖/铜奖", ""
    if re.search(r"优胜|入围|佳作|未分等级|不分等级", s):
        return 3, rank, "优胜/入围（未列等级）", "未列等级按三等奖档（附表说明 5）"
    if re.search(r"优秀", s):
        return 4, rank, "优秀奖", "优秀奖为第四档"
    if rank:
        t = 1 if rank == 1 else 2 if rank <= 3 else 3 if rank <= 6 else 4
        return t, rank, "第 %d 名" % rank, ""
    return None, rank, "", ""


def _mcm_letter(text):
    t = str(text).upper()
    m = re.search(r"(?:^|[\s（(【])([OFMHS])\s*(?:奖|$|[\s）)】])", t)
    if m:
        return m.group(1)
    for word, ch in [("OUTSTANDING", "O"), ("FINALIST", "F"), ("MERITORIOUS", "M"),
                     ("HONORABLE", "H"), ("SUCCESSFUL", "S")]:
        if re.search(r"\b%s\b" % word, t):
            return ch
    return ""


def tongshu_view(ev, level, tier, text):
    """统数口径 T2：返回 {level, tier, note, uncertain}。"""
    rule = ev["ts"] if ev else ""
    info = {"rule": rule or "未收录", "level": level, "tier": tier, "note": "", "uncertain": False}
    if rule == "不降":
        info["note"] = "统数 T2 白名单：不降等"
        return info
    if rule == "美赛":
        letter = _mcm_letter(text)
        mp = {"O": ("省级", 1), "F": ("省级", 1), "M": ("省级", 2), "H": ("省级", 3)}
        if letter in mp:
            info["level"], info["tier"] = mp[letter]
            info["note"] = "统数 T2：美赛 %s 奖 → 省级%s等奖" % (letter, "一二三"[info["tier"] - 1])
        elif letter == "S":
            info["level"], info["tier"] = "不加分", 0
            info["note"] = "统数 T2：美赛 S 奖不加分"
        else:
            info["uncertain"] = True
            info["note"] = "统数 T2：需先确认美赛奖项字母（O/F/M/H/S）"
        return info
    if rule == "降为校级":
        if level == "国家级":
            info["level"], info["note"] = "校级", "统数 T2：国家级 → 校级"
        elif level == "省级":
            info["level"], info["note"] = "院级", "统数 T2：省级 → 院级"
        elif level:
            info["level"], info["note"] = "院级", "统数 T2：校级及以下 → 院级"
        else:
            info["uncertain"] = True
            info["note"] = "统数 T2：需先确定原级别，再按国家级→校级、省级→院级降等"
        return info
    if rule == "初赛校级":
        if re.search(r"初赛", text):
            info["level"], info["note"] = "校级", "统数 T2：初赛 → 校级"
        else:
            info["uncertain"] = True
            info["note"] = "统数 T2：仅初赛明确按校级，其他轮次需向学院确认"
        return info
    if rule == "降一级":
        if level in LEVELS[:3]:
            info["level"] = LEVELS[LEVELS.index(level) + 1]
            info["note"] = "统数 T2：降一级 → %s" % info["level"]
        elif level == "院级":
            info["uncertain"] = True
            info["note"] = "统数 T2：院级已是最低档，需向学院确认是否仍认定"
        else:
            info["uncertain"] = True
            info["note"] = "统数 T2：需先确定原级别"
        return info
    if rule == "不适用":
        info["note"] = "结项类，无统数降等规则"
        return info
    info["uncertain"] = True
    info["note"] = "统数 T2：该赛事未列入已知不降名单，需核对《推免奖励分细则》认定结果"
    return info


def judge(text, tongshu=False):
    """把一句比赛描述 → 级别、档位、分值、依据、置信度、统数差异。"""
    text = str(text).strip()
    ev, alias = match_event(text)
    rest = text.replace(alias, " ", 1) if alias else text
    level, level_src, conf = parse_level(rest, ev)
    if not level and alias:
        # 赛事别名吞掉了描述里的级别证据（如“校运会 第3名”匹配“校运会”后 rest 只剩名次）：
        # 回退用别名本身定级；仍以证书落款为准，故置信度取“中”。
        lv2, src2, _ = parse_level(alias, None)
        if lv2:
            level, level_src, conf = lv2, "别名「%s」自带级别（%s），以落款为准" % (alias, src2), "中"
    tier, rank, award, award_note = parse_award(rest, ev)
    sub = ev["sub"] if ev else guess_sub(rest)

    out = {"input": text, "event": ev["name"] if ev else "", "alias": alias or "",
           "sub": sub, "level": level, "level_src": level_src, "award": award,
           "tier": tier, "rank": rank, "conf": conf, "notes": [],
           "raw": None, "score": None, "team": None, "tongshu": None, "basis": ""}

    # 美赛字母 → 档位（校发口径：O/F≈一等，M≈二等，H≈三等，S 不加分）
    if ev and ev["ts"] == "美赛" and tier is None:
        letter = _mcm_letter(text)
        mp = {"O": 1, "F": 1, "M": 2, "H": 3}
        if letter in mp:
            tier = mp[letter]
            award = "美赛 %s 奖" % letter
        elif letter == "S":
            tier = 0
            award = "美赛 S 奖（成功参赛）"
        out["tier"] = tier
        out["award"] = award

    # 学术科研按申报排序取档，未写默认第一负责人
    if sub == "学术科研" and tier is None:
        tier = rank_pos(text) if re.search(r"第一|第二|第三|负责人|主持", text) else 1
        out["tier"] = tier

    if level and sub and tier is not None:
        if tier == 0:
            out["raw"] = 0.0
            out["basis"] = "报名即参赛未获奖不加分；经选拔推荐参赛未获奖 0.5/次（累计≤2）"
            if re.search(r"选拔|推荐|代表", text):
                out["raw"] = PARTICIPATION_UNIT
                out["basis"] = "经学院及以上选拔推荐参赛未获奖：0.5 分/次，累计≤2"
        else:
            try:
                if sub == "学术科研":
                    out["raw"] = score_of(sub, level, tier=tier)
                elif sub == "体育赛事":
                    out["raw"] = score_of(sub, level, tier=rank or tier)
                else:
                    out["raw"] = score_of(sub, level, tier=max(1, min(4, tier)))
                if (sub, level) in TIERED:
                    tbl = " / ".join("%g" % x for x in _vals(TIERED[(sub, level)]))
                else:
                    tbl = "按级别表"
                out["basis"] = "附件2 %s %s：%s（本次取第 %s 档）" % (
                    SUB2DIM.get(sub, ""), sub, tbl, tier)
            except KeyError:
                out["raw"] = None
                out["notes"].append("分值表无「%s / %s」，需人工核对" % (sub, level))

    # 集体折算
    if out["raw"] is not None and sub not in {"学术科研", "学术论文", "发明专利", "技能证书", "团学活动"}:
        n_m = re.search(r"(\d+)\s*人", text)
        team = bool(re.search(r"团队|集体|小组|成员|队", text)) or bool(n_m)
        if team:
            n = int(n_m.group(1)) if n_m else None
            lead = bool(re.search(r"负责人|队长|主持|第一作者|排名第一", text))
            if n:
                out["team"] = {"n": n, "lead": lead, "score": collective(sub, out["raw"], n, lead)}
            else:
                out["team"] = {"n": None, "lead": lead,
                               "le5": out["raw"] / 2.0,
                               "gt5": out["raw"] / 2.0 if lead else 0.0}
    out["score"] = out["team"]["score"] if out["team"] and out["team"].get("n") else out["raw"]

    # 统数口径
    if level or tier is not None:
        ts = tongshu_view(ev, level, tier, text)
        if ts["tier"] == 0:
            ts["score"] = out["raw"] if out["raw"] is not None else None
        elif ts["level"] and ts["level"] != "不加分" and ts["tier"] and sub:
            try:
                if sub == "体育赛事":
                    ts["score"] = score_of(sub, ts["level"], tier=rank or ts["tier"])
                elif sub == "学术科研":
                    ts["score"] = score_of(sub, ts["level"], tier=ts["tier"])
                else:
                    ts["score"] = score_of(sub, ts["level"], tier=max(1, min(4, ts["tier"])))
            except KeyError:
                ts["score"] = None
        elif ts["level"] == "不加分":
            ts["score"] = 0.0
        else:
            ts["score"] = None
        if out["team"] and out["team"].get("n") and ts.get("score") is not None:
            ts["score"] = collective(sub, ts["score"], out["team"]["n"], out["team"]["lead"])
        out["tongshu"] = ts

    if tongshu and out["tongshu"]:
        out["main"] = "tongshu"
    else:
        out["main"] = "school"
    return out


def _f(x):
    if x is None:
        return "—"
    s = "%.2f" % float(x)
    return s.rstrip("0").rstrip(".")


def format_judge(r, tongshu=False):
    L = ["─" * 48, "输入：%s" % r["input"]]
    if r["event"]:
        L.append("【赛事】%s（命中“%s”）" % (r["event"], r["alias"]))
    else:
        L.append("【赛事】未收录；按关键词归类为「%s」" % (r["sub"] or "未识别"))
    if not r["level"]:
        L.append("【级别】未能确定 —— %s" % r["level_src"])
        L.append("【结论】暂不给分。请补充证书落款（颁奖）单位，或说明是国赛/省赛/校赛/院赛。")
        if r["event"]:
            L.append("【提示】赛事名称本身带“全国/中国”不等于国家级，附表说明 7 要求以落款单位为准。")
        return "\n".join(L)
    L.append("【级别】%s（依据：%s）· 置信度：%s" % (r["level"], r["level_src"], r["conf"]))
    if r["award"]:
        if r["sub"] == "体育赛事" and r["rank"]:
            L.append("【奖项】第 %s 名 → 按名次档取分" % r["rank"])
        elif r["tier"] == 0:
            L.append("【奖项】%s → 成功参赛档（0 分）" % r["award"])
        else:
            L.append("【奖项】%s → 第 %s 档" % (r["award"], r["tier"] if r["tier"] else "—"))
    elif r["sub"] == "学术科研":
        L.append("【奖项】未写申报排序，按“第一负责人”估算；若为成员请说明排序（学术科研按申报排序取档）")
    else:
        L.append("【奖项】未写奖项等级，按三等奖档估算（附表说明 5：不分等级按三等奖）")
    L.append("【归属】%s → %s" % (r["sub"], SUB2DIM.get(r["sub"], "?")))
    if r["raw"] is None:
        L.append("【加分】无法给出（分值表缺项，需人工核对）")
    else:
        L.append("【加分】校发口径 %s 分" % _f(r["score"] if r["score"] is not None else r["raw"]))
        if r["basis"]:
            L.append("【依据】%s" % r["basis"])
    if r["team"]:
        t = r["team"]
        if t.get("n"):
            L.append("【集体折算】%d 人%s → %s 分/人" % (t["n"], "（负责人）" if t["lead"] else "（非负责人）", _f(t["score"])))
        else:
            L.append("【集体折算】未写人数：≤5 人各 %s 分；>5 人仅负责人 %s 分、其他 0" % (_f(t["le5"]), _f(t["gt5"])))
    if r["conf"] == "中":
        L.append("【需核对】名称像高级别，但可能只是校内选拔/分赛区；最终以证书落款单位级别为准。")
    ts = r.get("tongshu")
    if ts:
        head = "【统数口径】"
        if ts["uncertain"]:
            L.append(head + ts["note"])
        elif ts["level"] == "不加分":
            L.append(head + ts["note"] + " → 0 分")
        else:
            L.append(head + ts["note"] + " → %s%s %s 分" % (ts["level"], "第 %s 档" % ts["tier"] if ts["tier"] else "", _f(ts["score"])))
        if tongshu:
            L.append("【本次结论】按统数口径：%s 分" % _f(ts["score"]))
    L.append("【提醒】等级以证书落款（颁奖）单位为准（附表说明 7）；同一成果不重复计分。")
    return "\n".join(L)


def judge_file(path, tongshu=False):
    out = []
    with open(path, encoding="utf-8-sig") as fh:
        for line in fh:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            r = judge(s, tongshu)
            sc = r["tongshu"]["score"] if (tongshu and r["tongshu"]) else r["score"]
            lv = r["level"] or "待定级"
            if tongshu and r["tongshu"] and r["tongshu"]["level"] and r["tongshu"]["level"] not in ("不加分", r["level"]):
                lv = "%s→%s" % (r["level"], r["tongshu"]["level"])
            out.append("%s\t%s\t%s\t%s\t%s" % (s, lv, r["award"] or "—", _f(sc), r["conf"]))
    return "输入\t级别\t奖项\t加分\t置信度\n" + "\n".join(out)


def draft(lines, tongshu=False):
    """口语描述 → calc 可用的「成果」JSON 条目（每行一条）。
    能定级定奖的直接给全字段（含档位，避免二次解析歧义）；
    缺证据的用「_待补充」标出缺口，回填后即可接 calc。"""
    items = []
    for s in lines:
        r = judge(s, tongshu)
        ts = r.get("tongshu") or {}
        it = {"名称": r["input"], "子类": r["sub"] or "待定"}
        lvl, tier = r["level"], r["tier"]
        if tongshu and ts.get("level") in LEVELS:
            lvl, tier = ts["level"], ts.get("tier", tier)
        if lvl:
            it["级别"] = lvl
        else:
            it["_待补充"] = "级别（按证书落款/主办单位：国家级、省级、校级、院级）"
        if r["tier"] == 0:
            it["未获奖参与"] = True
            it["经选拔推荐"] = bool(re.search(r"选拔|推荐|代表", s))
        else:
            # 奖项按原输入还原：parse_award 对金银铜会补默认名次，不能反写
            if re.search(r"第\s*\d+\s*名", s) and r["rank"]:
                it["奖项"] = "第%d名" % r["rank"]
            elif r["award"]:
                it["奖项"] = r["award"]
            if tier:
                it["档位"] = tier
        if r["team"] and r["team"].get("n"):
            it["人数"] = r["team"]["n"]
            it["主要负责人"] = bool(r["team"]["lead"])
        if not r["sub"]:
            it["_待补充"] = (it.get("_待补充", "") + "；子类（学术竞赛/技能竞赛/文艺赛事…）").lstrip("；")
        sc = ts.get("score") if tongshu else r["score"]
        if sc is not None:
            it["_判定"] = "%s口径 %s 分（置信度 %s）" % ("统数" if tongshu else "校发", _f(sc), r["conf"])
        items.append(it)
    return items


def calc(p):
    warns = []
    # F1 基本素质：四分项各基准 25，减分后不低于 0
    dec = p.get("减分", {})
    f1 = {k: max(0.0, 25.0 - float(dec.get(k, 0))) for k in F1_ITEMS}
    f1_total = sum(f1.values())

    # F2 知识水平：学分加权，取首次成绩；重修刷分不算进步
    courses = p.get("课程") or []
    if not courses:
        raise ValueError("缺少「课程」明细，知识水平（F2）无法计算")
    credits = 0.0
    weighted = 0.0
    for i, c in enumerate(courses, 1):
        for fld in ("学分", "首次成绩"):
            if fld not in c:
                raise ValueError("第 %d 门课程缺「%s」字段" % (i, fld))
        cr, sc = float(c["学分"]), float(c["首次成绩"])
        if cr < 0:
            raise ValueError("第 %d 门课学分为负：%r" % (i, c["学分"]))
        if not 0 <= sc <= 100:
            warns.append("第 %d 门课成绩 %g 超出 0-100，请核对是否百分制" % (i, sc))
        credits += cr
        weighted += cr * sc
    if credits <= 0:
        raise ValueError("课程学分合计为 0，知识水平（F2）无法计算")
    f2 = weighted / credits

    raw_items, part = [], {}
    for idx, it in enumerate(p.get("成果", []), 1):
        sub = it.get("子类")
        dim = SUB2DIM.get(sub)
        if not dim:
            raise ValueError("第 %d 条成果的子类未知或缺失：%r（须为 %s 之一）"
                             % (idx, sub, "、".join(SUB2DIM)))
        if it.get("指标") and it["指标"] != dim:
            raise ValueError("子类 %s 应归 %s，与声明的 %s 冲突" % (sub, dim, it["指标"]))

        if it.get("未获奖参与"):
            # 竞赛类必须有选拔推荐；报名即参赛不予加分
            if sub in SELECTED_ONLY and not it.get("经选拔推荐"):
                continue
            if sub in PROOF_ONLY and not it.get("有参加证明"):
                continue
            part[dim] = part.get(dim, 0.0) + PARTICIPATION_UNIT
            continue

        cat = it.get("类别")
        lvl = it.get("级别")
        if not lvl:
            raise ValueError("成果「%s」（%s）缺少「级别」字段"
                             % (it.get("名称") or "第 %d 条" % idx, sub))
        if it.get("档位"):
            tier = int(it["档位"])
        elif sub == "学术论文":
            tier = author_pos(it.get("位次", ""))
        elif sub == "学术科研":
            tier = rank_pos(it.get("位次", ""))
        elif sub == "体育赛事":
            tier = sport_pos(it.get("奖项", "") or it.get("位次", ""))
        else:
            tier = tier_of(it.get("奖项", ""))
        raw = score_of(sub, lvl, tier, cat)
        raw = collective(sub, raw, it.get("人数", 1), it.get("主要负责人", False))
        raw_items.append({"子类": sub, "指标": dim, "名称": it.get("名称", ""), "分": raw,
                          "级别": lvl, "类别": cat or "", "档位": tier})
        if not it.get("名称"):
            warns.append("第 %d 条成果（%s %s）未填「名称」，无法按附表说明(3) 判重，按独立成果累计"
                         % (idx, sub, lvl))

    # 附表说明(3)：同项目同类别重复获奖取最高；不同类别 / 不同项目 累加。
    # 没有名称的成果判不了“同一项目”，各算各的（上面已告警），不并入同名键。
    best = {}
    for r in raw_items:
        k = (r["指标"], r["子类"], r["名称"]) if r["名称"] else id(r)
        if k not in best or r["分"] > best[k]["分"]:
            best[k] = r
    kept = list(best.values())

    b = {d: 0.0 for d in WEIGHTS}
    for r in kept:
        b[r["指标"]] += r["分"]
    for dim, v in part.items():
        b[dim] += min(v, PARTICIPATION_CAP)

    capped = {k: min(v, CAP) for k, v in b.items()}
    f3 = sum(capped[k] * w for k, w in WEIGHTS.items())
    total = (f1_total * TOTAL_W["基本素质"] + f2 * TOTAL_W["知识水平"]
             + f3 * TOTAL_W["能力评价"])
    return {"f1": f1, "f1_total": f1_total, "f2": f2, "raw": b, "capped": capped,
            "f3": f3, "total": total, "items": kept, "参与分": part, "warnings": warns}


def report(p):
    r = calc(p)
    for it in r["items"]:
        tag = " %s" % it["类别"] if it["类别"] else ""
        print("    + %6.2f  %s / %s%s  %s" % (it["分"], it["指标"], it["子类"], tag, it["名称"]))
    if r["参与分"]:
        print("    + 参与分 %s" % r["参与分"])
    if r["warnings"]:
        for w in r["warnings"]:
            print("    ⚠ %s" % w)
    print()
    for k in F1_ITEMS:
        print("  F1 %-10s %6.2f" % (k, r["f1"][k]))
    print("  F1 基本素质 = %.2f" % r["f1_total"])
    print("  F2 知识水平 = %.4f  （%d 门课）" % (r["f2"], len(p["课程"])))
    for k in WEIGHTS:
        flag = "  ← 已封顶，再加分不涨" if r["raw"][k] > CAP else ""
        print("  F3 %-10s 原始 %7.2f → 计 %6.2f%s" % (k, r["raw"][k], r["capped"][k], flag))
    print("  F3 能力评价 = %.4f" % r["f3"])
    print("  综合评价 = %.2f×0.15 + %.4f×0.55 + %.4f×0.30 = %.4f"
          % (r["f1_total"], r["f2"], r["f3"], r["total"]))
    return r


# ────────────────────────────── 自检 ──────────────────────────────
def _courses(score, n=10, credit=3):
    return [{"学分": credit, "首次成绩": score} for _ in range(n)]


def selftest():
    ok = bad = 0

    def chk(name, got, want, tol=1e-6):
        nonlocal ok, bad
        if isinstance(got, str) or isinstance(want, str):
            good = got == want
        else:
            good = abs(float(got) - float(want)) <= tol
        if good:
            ok += 1
        else:
            bad += 1
            print("  ✗ %-50s 得 %s 应 %s" % (name, got, want))

    print("【1】权重结构（S2 第八/十一/十三条）")
    chk("基本素质", TOTAL_W["基本素质"], .15)
    chk("知识水平", TOTAL_W["知识水平"], .55)
    chk("能力评价", TOTAL_W["能力评价"], .30)
    chk("五分项权重之和", sum(WEIGHTS.values()), 1.0)
    for dim, w in [("B1科研创新", .35), ("B2专业技能", .15), ("B3文体特长", .15),
                   ("B4社会工作", .10), ("B5社会实践", .25)]:
        chk("权重 " + dim, WEIGHTS[dim], w)
    chk("F1 四分项基准合计", 25 * len(F1_ITEMS), 100)

    print("【2】F1 减分 / F2 学分加权 / 综合评价公式")
    r = calc({"减分": {"A3组织纪律": 4}, "课程": _courses(86.4)})
    chk("F1 扣 4 分", r["f1_total"], 96)
    chk("F2 单值", r["f2"], 86.4)
    chk("综合 = 96*.15+86.4*.55", r["total"], 96 * .15 + 86.4 * .55)
    r = calc({"减分": {"A1思想政治": 999}, "课程": _courses(80)})
    chk("F1 单分项最低 0", r["f1"]["A1思想政治"], 0)
    r = calc({"课程": [{"学分": 4, "首次成绩": 90}, {"学分": 2, "首次成绩": 60}]})
    chk("F2 学分加权 (4*90+2*60)/6", r["f2"], 80)

    print("【3】附表说明(4) 三句话必须分开算")
    chk("学术竞赛 5人内成员 校级二等 8→4", collective("学术竞赛", 8, 5, False), 4)
    chk("学术竞赛 6人非负责人 省级一等 → 0", collective("学术竞赛", 20, 6, False), 0)
    chk("学术竞赛 6人负责人 省级一等 20→10", collective("学术竞赛", 20, 6, True), 10)
    chk("文艺赛事 6人非负责人 校级三等 6→3", collective("文艺赛事", 6, 6, False), 3)
    chk("体育赛事 8人非负责人 校级第3名 7→3.5", collective("体育赛事", 7, 8, False), 3.5)
    chk("学术科研 5人主持人 省级结项 15（不减半）", collective("学术科研", 15, 5, True), 15)
    chk("学术科研 5人第二人 省级结项 10（不减半）", collective("学术科研", 10, 5, False), 10)
    chk("文化知识竞赛 6人非负责人 → 0（不是减半）", collective("文化知识竞赛", 6, 6, False), 0)
    chk("学术论文 二作 二类 15（不减半）", collective("学术论文", 15, 3, False), 15)
    chk("团学活动 不适用集体折算", collective("团学活动", 30, 6, False), 30)

    print("【4】附表说明(5) 奖项写法 → 档位")
    for award, want in [("一等奖", 1), ("第1名", 1), ("金奖", 1), ("冠军", 1),
                        ("二等奖", 2), ("第3名", 2), ("银奖", 2),
                        ("三等奖", 3), ("第5名", 3), ("铜奖", 3), ("季军", 3), ("不分等级", 3),
                        ("优秀奖", 4), ("第9名", 4), ("优胜奖", 3), ("未分等级", 3)]:
        chk("「%s」→ %d" % (award, want), tier_of(award), want)

    print("【5】分值表取值（对 S3 正文逐行）")
    chk("学术竞赛 国 一等", score_of("学术竞赛", "国家级", 1), 30)
    chk("学术竞赛 国 二等", score_of("学术竞赛", "国家级", 2), 25)
    chk("学术竞赛 国 三等", score_of("学术竞赛", "国家级", 3), 22)
    chk("学术竞赛 国 优秀奖", score_of("学术竞赛", "国家级", 4), 20)
    chk("学术竞赛 省 三等", score_of("学术竞赛", "省级", 3), 12)
    chk("学术竞赛 院 优秀奖", score_of("学术竞赛", "院级", 4), 1)
    chk("学术论文 一类 独撰", score_of("学术论文", "一类", author_pos("独撰")), 30)
    chk("学术论文 一类 第一作者", score_of("学术论文", "一类", author_pos("第一作者")), 20)
    chk("学术论文 一类 第二作者", score_of("学术论文", "一类", author_pos("第二作者")), 15)
    chk("学术论文 一类 第三以后", score_of("学术论文", "一类", author_pos("第三作者以后")), 8)
    chk("学术论文 二类 独撰", score_of("学术论文", "二类", author_pos("独撰")), 20)
    chk("学术论文 二类 第三以后", score_of("学术论文", "二类", author_pos("第三作者以后")), 5)
    chk("发明专利 实用新型", score_of("发明专利", "实用新型", 1), 4)
    chk("学术科研 省级 第一负责人", score_of("学术科研", "省级", rank_pos("第一负责人")), 15)
    chk("学术科研 省级 第二", score_of("学术科研", "省级", rank_pos("第二")), 10)
    chk("学术科研 省级 第三以后", score_of("学术科研", "省级", rank_pos("第三以后")), 5)
    chk("体育赛事 校级 第3名", score_of("体育赛事", "校级", 3), 7)
    chk("体育赛事 国家级 第5名", score_of("体育赛事", "国家级", 4), 15)
    chk("体育赛事 国家级 第8名", score_of("体育赛事", "国家级", 8), 10)
    chk("技能证书 高级", score_of("技能证书", "高级", 1), 10)
    chk("团学 优秀学生干部 国家级", score_of("团学活动", "国家级", cat="优秀学生干部"), 30)
    chk("团学 主要负责人 院级", score_of("团学活动", "院级", cat="优秀学生组织主要负责人"), 3)
    chk("团学 团学先进个人 省级", score_of("团学活动", "省级", cat="团学先进个人"), 15)
    chk("志愿 优秀团队 校级", score_of("志愿服务", "校级", cat="优秀团队"), 10)
    chk("实践 调查报告 国家级", score_of("社会实践", "国家级", cat="调查报告"), 25)
    chk("实践 团队 院级", score_of("社会实践", "院级", cat="团队"), 5)

    print("【6】附表说明(1)(2)(3) 封顶 / 累加 / 去重")
    p = {"课程": _courses(86), "成果": [
        {"名称": "国赛", "子类": "学术竞赛", "级别": "国家级", "档位": 1},
        {"名称": "国赛", "子类": "学术竞赛", "级别": "省级", "档位": 1},   # 同项目同类别 → 取最高
        {"名称": "省赛", "子类": "学术竞赛", "级别": "省级", "档位": 1},   # 不同项目 → 累加
    ]}
    chk("同项目取最高 + 不同项目累加 = 30+20", calc(p)["raw"]["B1科研创新"], 50)
    p = {"课程": _courses(86), "成果": [
        {"名称": "论文%d" % i, "子类": "学术论文", "级别": "一类", "档位": 1} for i in range(5)]}
    r = calc(p)
    chk("B1 原始 150 → 封顶 100", r["capped"]["B1科研创新"], 100)
    chk("封顶后 F3 贡献 = 100*.35", r["f3"], 35)
    p = {"课程": _courses(86), "成果": [
        {"名称": "A", "子类": "技能证书", "级别": "高级"},
        {"名称": "B", "子类": "技能证书", "级别": "中级", "类别": "外语水平类"}]}
    chk("不同证书累加 10+5", calc(p)["raw"]["B2专业技能"], 15)

    print("【7】未获奖参与分（附表说明前的行注）")
    p = {"课程": _courses(86), "成果": [
        {"名称": "参赛%d" % i, "子类": "学术竞赛", "级别": "校级",
         "未获奖参与": True, "经选拔推荐": True} for i in range(6)]}
    chk("6 次选拔参赛 封顶 2", calc(p)["raw"]["B1科研创新"], 2)
    p = {"课程": _courses(86), "成果": [
        {"名称": "报名即参赛", "子类": "学术竞赛", "级别": "校级", "未获奖参与": True}]}
    chk("报名即参赛不给分", calc(p)["raw"]["B1科研创新"], 0)
    p = {"课程": _courses(86), "成果": [
        {"名称": "志愿%d" % i, "子类": "志愿服务", "类别": "先进个人", "级别": "校级",
         "未获奖参与": True, "有参加证明": True} for i in range(5)]}
    chk("5 次志愿 封顶 2", calc(p)["raw"]["B4社会工作"], 2)

    print("【8】复现《黄金测试题集》B 类 1-11 题（答案必须与题集一致）")
    chk("B01 数模国赛国家二等奖", score_of("学术竞赛", "国家级", tier_of("二等奖")), 25)
    chk("B02 省级挑战杯三等奖", score_of("学术竞赛", "省级", tier_of("三等奖")), 12)
    chk("B03 二类独撰", score_of("学术论文", "二类", author_pos("独撰")), 20)
    chk("B03 二类第一作者", score_of("学术论文", "二类", author_pos("第一作者")), 15)
    chk("B03 二类第二作者", score_of("学术论文", "二类", author_pos("第二作者")), 10)
    chk("B03 二类第三以后", score_of("学术论文", "二类", author_pos("第三以后")), 5)
    chk("B04 发明专利", score_of("发明专利", "国家发明专利", 1), 20)
    chk("B04 实用新型", score_of("发明专利", "实用新型", 1), 4)
    chk("B05 省级结项主持人", collective("学术科研", score_of("学术科研", "省级", rank_pos("主持人")), 5, True), 15)
    chk("B06 校运会400米第3名", score_of("体育赛事", "校级", sport_pos("第3名")), 7)
    chk("B06 不是按三等奖 6 分", 0 if score_of("体育赛事", "校级", sport_pos("第3名")) == 6 else 1, 1)
    chk("B07 六级按认定级别（高级10）", score_of("技能证书", "高级", 1), 10)
    chk("B08 五人团队校级学术竞赛二等成员 8→4",
        collective("学术竞赛", score_of("学术竞赛", "校级", tier_of("二等奖")), 5, False), 4)
    chk("B09 省级社会实践团队 6人普通成员 → 0",
        collective("社会实践", score_of("社会实践", "省级", cat="团队"), 6, False), 0)
    chk("B09 省级社会实践团队 6人负责人 20→10",
        collective("社会实践", score_of("社会实践", "省级", cat="团队"), 6, True), 10)
    chk("B10 优胜奖→三等（不是优秀奖）", score_of("学术竞赛", "校级", tier_of("优胜奖")), 6)
    chk("B10 优秀奖→第四档", score_of("学术竞赛", "校级", tier_of("优秀奖")), 5)
    p = {"课程": _courses(86), "成果": [
        {"名称": "挑战杯", "子类": "学术竞赛", "级别": "校级", "奖项": "二等奖"},
        {"名称": "挑战杯", "子类": "学术竞赛", "级别": "省级", "奖项": "三等奖"}]}
    chk("B11 同项目校省都获奖取最高（省三等12）", calc(p)["raw"]["B1科研创新"], 12)

    print("【9】与官方原文三方对账（S3 正文 ↔ 内置表）")
    src = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                                       "03 知识库", "校发-附件2-本科学生能力评价测评计分标准.txt"))
    _alt = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                                        "知识库待上传", "03-附件2-能力评价测评计分标准.txt"))
    if not os.path.exists(src) and os.path.exists(_alt):
        src = _alt
    if os.path.exists(src):
        txt = open(src, encoding="utf-8").read().replace("\n", "").replace(" ", "")
        pairs = [
            ("学术竞赛 国家级", "国家级竞赛（一二三等、优秀奖）30/25/22/20"),
            ("学术竞赛 院级", "院级竞赛（一二三等、优秀奖）5/3/2/1"),
            ("学术论文 一类", "一类期刊论文（独撰/合著第一/第二/第三以后作者）30/20/15/8"),
            ("学术论文 一般", "一般期刊论文（正式刊号）（独撰/合著第一/第二/第三以后作者）5/3/2/1"),
            ("发明专利", "国家发明专利/实用新型专利/外观设计专利20/4/2"),
            ("学术科研 省级", "省级结项（第一、二及第三以后）15/10/5"),
            ("技能证书", "外语水平类（高级、中级、初级）10/5/3"),
            ("文艺赛事 省级", "省级文艺赛事（一二三等、优秀奖）20/15/12/10"),
            ("体育赛事 国家级", "国家级体育赛事（一二三四五六七八名）30/25/20/15/15/10/10/10"),
            ("体育赛事 院级", "院级体育赛事（一二三四五六七八名）7/6/4/3/3/1/1/1"),
            ("文化知识竞赛 校级", "校级竞赛（一二三等、优秀奖）10/8/6/5"),
            ("团学 优秀学生干部", "获国家/省/校/院荣誉称号的优秀学生干部30/20/10/5"),
            ("团学 主要负责人", "获国家/省/校/院表彰的优秀学生组织主要负责人（5人以内）15/10/6/3"),
            ("团学 先进个人", "获国家/省/校/院表彰的团学先进个人20/15/8/4"),
            ("志愿 先进个人", "志愿服务先进个人国家级/省级/校级/院级表彰30/20/10/5"),
            ("志愿 优秀团队", "志愿服务优秀团队国家级/省级/校级/院级表彰30/20/10/5"),
            ("实践 先进个人", "社会实践先进个人国家级/省级/校级/院级表彰30/20/10/5"),
            ("实践 团队", "社会实践团队国家级/省级/校级/院级表彰30/20/10/5"),
            ("实践 调查报告", "社会实践调查报告国家级/省级/校级/院级表彰25/15/8/4"),
            ("附表说明(1)", "能力评价各指标测评总得分最高不超过100分"),
            ("附表说明(3)", "同一项目在同一类别下重复获奖，以最高分计"),
            ("附表说明(4)通用句", "集体或合作项目所获奖项，5人以内的，各成员根据对应级别标准减半加分"),
            ("附表说明(4)文体句", "体育赛事及文艺赛事，集体或合作项目所获奖项，各成员根据对应级别标准减半加分"),
            ("附表说明(4)科研句", "结项后项目主持人参照第一项目负责人加分"),
            ("附表说明(5)", "若所获奖项不分等级，按三等奖计入加分"),
            ("附表说明(5)名次", "第2-3名按二等奖计入加分，第4-6名按三等奖计入加分，第7名及以后按优秀奖计入加分"),
            ("附表说明(7)", "各类奖项的等级认定严格依据获奖证书落款单位（颁奖单位）级别进行"),
            ("附表说明(8)", "以表彰或真实证书、奖状标注的时间或论文作品发表时间为准"),
        ]
        for label, frag in pairs:
            chk("原文含 %s" % label, 1 if frag.replace(" ", "") in txt else 0, 1)
        chk("原文含 报名即参赛不予加分",
            1 if "报名即参赛且未获奖者，不予加分" in txt else 0, 1)
    else:
        print("  ⚠ 未找到官方原文，跳过对账")

    print("\n【10】比赛定级（--judge）")
    cases = [
        ("全国大学生数学建模竞赛 国家级二等奖", 25.0),
        ("数学建模 省二等奖", 15.0),
        ("挑战杯校赛一等奖", 10.0),
        ("互联网+ 金奖（校赛）", 10.0),
        ("美赛 M 奖", 25.0),
        ("院运动会 第3名", 4.0),
        ("挑战杯 国家级三等奖 团队 5 人", 11.0),
        ("大创 国家级 结项 负责人", 20.0),
        ("数学建模 省赛 选拔推荐参赛未获奖", 0.5),
        ("数学建模 省赛 报名即参赛未获奖", 0.0),
        ("数模省二 队长 8 人队", 7.5),
        ("国二 挑战杯", 25.0),
        ("省一等奖 蓝桥杯", 20.0),
    ]
    for text, want in cases:
        chk("judge: " + text, judge(text)["score"], want)
    chk("judge: 未定级不给分", 1 if judge("某某杯 一等奖")["score"] is None else 0, 1)
    chk("judge: 名称含全国但无级别→中置信", 1 if judge("挑战杯 一等奖")["conf"] == "中" else 0, 1)
    chk("judge: 省二缩写→省级", 1 if judge("数模省二")["level"] == "省级" else 0, 1)
    chk("judge: 大创未写排序默认第一负责人", judge("大创 国家级 结项")["score"], 20.0)
    chk("judge: 美赛S为0分档", judge("美赛 S 奖")["tier"], 0)
    ts_cases = [
        ("美赛 M 奖", 15.0),
        ("美赛 S 奖", 0.0),
        ("亚太杯 国家级二等奖", 8.0),
        ("东方财富杯 省赛一等奖", 20.0),
        ("全国大学生英语翻译大赛 国家级二等奖", 15.0),
        ("数学建模 省二等奖", 15.0),
    ]
    for text, want in ts_cases:
        r = judge(text, tongshu=True)
        chk("judge统数: " + text, r["tongshu"]["score"], want)

    print("\n【11】口径修复回归（特等/优胜档位、无名判重、未知级别、数字位次、别名定级、美赛全称、draft）")
    chk("tier_of 特等奖 → 1（特等按一等档）", tier_of("特等奖"), 1)
    chk("tier_of 佳作奖 → 3（未列等级按三等）", tier_of("佳作奖"), 3)
    chk("parse_award 优胜奖 → 3（附表说明5，不是优秀奖档）", parse_award("优胜奖")[0], 3)
    chk("parse_award 入围奖 → 3", parse_award("入围奖")[0], 3)
    chk("judge 优胜奖按三等档给分", judge("挑战杯 省级 优胜奖")["score"], 12.0)
    chk("judge 特等奖按一等档给分", judge("挑战杯 国家级 特等奖")["score"], 30.0)

    p = {"课程": _courses(86), "成果": [
        {"子类": "技能证书", "级别": "高级", "类别": "外语水平类"},
        {"子类": "技能证书", "级别": "中级", "类别": "外语水平类"}]}
    r = calc(p)
    chk("无名证书各自累计 10+5", r["raw"]["B2专业技能"], 15)
    chk("无名成果产生判重告警", 1 if r["warnings"] else 0, 1)
    p = {"课程": _courses(86), "成果": [
        {"名称": "CET", "子类": "技能证书", "级别": "高级", "类别": "外语水平类"},
        {"名称": "CET", "子类": "技能证书", "级别": "中级", "类别": "外语水平类"}]}
    chk("同名证书仍取最高 10", calc(p)["raw"]["B2专业技能"], 10)

    try:
        score_of("社会实践", "县级", 1, cat="先进个人")
        chk("形状B县级应报错而不是按校级", 0, 1)
    except KeyError:
        chk("形状B县级应报错而不是按校级", 1, 1)

    chk("第2作者 → 档位3", author_pos("第2作者"), 3)
    chk("第3作者 → 档位4", author_pos("第3作者"), 4)
    chk("第1作者 → 档位2", author_pos("第1作者"), 2)

    r = judge("校运会 第3名")
    chk("校运会 别名回退定校级", r["level"], "校级")
    chk("校运会 校级第3名 7 分", r["score"], 7.0)
    chk("校运会 回退置信度为中", r["conf"], "中")
    chk("院运会 → 院级", judge("院运会 第1名")["level"], "院级")

    chk("美赛 Meritorious → M", _mcm_letter("MCM Meritorious Winner"), "M")
    chk("美赛 Outstanding → O", _mcm_letter("Outstanding Winner"), "O")
    chk("judge 美赛 Honorable Mention 档位3", judge("美赛 Honorable Mention")["tier"], 3)

    items = draft(["挑战杯校赛金奖", "某某杯 一等奖"])
    chk("draft 条目含子类", items[0]["子类"], "学术竞赛")
    chk("draft 条目含档位", items[0].get("档位"), 1)
    chk("draft 未定级条目标待补充", 1 if "_待补充" in items[1] else 0, 1)
    d = draft(["数模省二 队长 8 人队"])
    chk("draft 集体条目带人数", d[0].get("人数"), 8)
    chk("draft 集体条目带负责人", 1 if d[0].get("主要负责人") else 0, 1)
    p = {"课程": _courses(86), "成果": draft(["挑战杯校赛金奖"])}
    chk("draft 产物可直接进 calc（校级一等 10 分）", calc(p)["raw"]["B1科研创新"], 10.0)
    chk("成绩105产生告警", 1 if calc({"课程": [{"学分": 3, "首次成绩": 105}]})["warnings"] else 0, 1)
    try:
        calc({"课程": []})
        chk("空课程应报错", 0, 1)
    except ValueError:
        chk("空课程应报错", 1, 1)
    try:
        calc({"课程": _courses(86), "成果": [{"子类": "志愿服务", "类别": "先进个人"}]})
        chk("缺级别应报错", 0, 1)
    except ValueError:
        chk("缺级别应报错", 1, 1)

    print("\n结果：%d 项通过，%d 项失败" % (ok, bad))
    return bad == 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    if "--judge-file" in sys.argv:
        i = sys.argv.index("--judge-file")
        print(judge_file(sys.argv[i + 1], "--tongshu" in sys.argv))
        sys.exit(0)
    if "--judge" in sys.argv:
        args = [a for a in sys.argv[1:] if not a.startswith("--")]
        ts = "--tongshu" in sys.argv
        if args:
            print(format_judge(judge(args[-1], ts), ts))
        else:
            for line in sys.stdin:
                if line.strip():
                    print(format_judge(judge(line.strip(), ts), ts))
                    print()
        sys.exit(0)
    if "--dump-table" in sys.argv:
        for (sub, lv), v in TIERED.items():
            print("A %-10s %-14s %s" % (sub, lv, v))
        for (sub, cat), v in LEVEL_KEYED.items():
            print("B %-10s %-22s %s（国家级→院级）" % (sub, cat, v))
        sys.exit(0)
    if "--draft-file" in sys.argv:
        i = sys.argv.index("--draft-file")
        path = sys.argv[i + 1]
        with open(path, encoding="utf-8-sig") as fh:
            lines = [l.strip() for l in fh if l.strip() and not l.startswith("#")]
        print(json.dumps(draft(lines, "--tongshu" in sys.argv), ensure_ascii=False, indent=2))
        sys.exit(0)
    if "--draft" in sys.argv:
        args = [a for a in sys.argv[1:] if not a.startswith("--")]
        print(json.dumps(draft(args, "--tongshu" in sys.argv), ensure_ascii=False, indent=2))
        sys.exit(0)
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    try:
        with open(sys.argv[1], encoding="utf-8") as fh:
            p = json.load(fh)
    except FileNotFoundError:
        print("找不到文件：%s（示例见 _demo1.json）" % sys.argv[1])
        sys.exit(2)
    except json.JSONDecodeError as e:
        print("JSON 格式错误：%s" % e)
        sys.exit(2)
    try:
        report(p)
    except (ValueError, KeyError) as e:
        print("输入有误：%s" % e)
        sys.exit(2)
