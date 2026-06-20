#!/usr/bin/env python3
"""
高考志愿顾问 Agent — 模型无关、支持实时搜索、结构化槽位采集。
Usage:
  python agent.py                    # 交互式对话
  python agent.py --model qwen-plus # 指定模型
  python agent.py --no-search        # 禁用搜索
"""

import os, sys, json, re, urllib.request, urllib.parse, urllib.error
from openai import OpenAI

# 高考数据模块
try:
    from gaokao_data import query_admission, format_admission_info
    HAS_DATA_MODULE = True
except ImportError:
    HAS_DATA_MODULE = False

def query_real_data(province=None, school_keyword=None, major_keyword=None, max_rank=None, limit=20):
    """查询真实录取数据库 — 修复版"""
    if not HAS_REAL_DATA:
        return None
    try:
        curs = REAL_DB.cursor()
        conditions = []
        params = []

        # 省份模糊匹配
        if province:
            conditions.append("province LIKE ?")
            params.append(f'%{province}%')

        # 学校模糊匹配
        if school_keyword:
            conditions.append("school LIKE ?")
            params.append(f'%{school_keyword}%')

        # 专业模糊匹配
        if major_keyword:
            conditions.append("major LIKE ?")
            params.append(f'%{major_keyword}%')

        # 位次范围
        if max_rank:
            conditions.append("rank >= ? AND rank <= ?")
            params.append(max_rank)
            params.append(max_rank + 80000)

        # 至少要有省份或学校
        if not conditions:
            return None

        where = " AND ".join(conditions)
        query_sql = f"SELECT school, major, score, rank, province, year FROM admission WHERE {where} ORDER BY year DESC, rank ASC LIMIT ?"
        params.append(limit)

        curs.execute(query_sql, params)
        rows = curs.fetchall()
        if rows:
            return [
                {'school': r[0], 'major': r[1], 'score': r[2], 'rank': r[3], 'province': r[4], 'year': r[5]}
                for r in rows
            ]
        return None
    except Exception as e:
        return None

def read_clipboard():
    """读取 Windows 剪贴板文本。"""
    try:
        import win32clipboard
        win32clipboard.OpenClipboard()
        if win32clipboard.IsClipboardFormatAvailable(13):  # CF_UNICODETEXT
            data = win32clipboard.GetClipboardData(13)
            win32clipboard.CloseClipboard()
            return data
        win32clipboard.CloseClipboard()
    except:
        pass
    return None

# ── 加载 .env 文件 ──────────────────────────────────
def load_dotenv(path):
    """简单的 .env 加载器，不依赖第三方库。"""
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    key, val = key.strip(), val.strip()
                    if key not in os.environ:
                        os.environ[key] = val

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(HERE, ".env"))

# 真实录取数据库（在 HERE 定义后初始化）
HAS_REAL_DATA = False
REAL_DB = None
try:
    import sqlite3 as _sql
    _DB_PATH = os.path.join(HERE, 'admission_clean.db')
    _GZ_PATH = os.path.join(HERE, 'admission_clean.db.gz')
    # 自动解压
    if not os.path.exists(_DB_PATH) and os.path.exists(_GZ_PATH):
        import gzip, shutil
        with gzip.open(_GZ_PATH, 'rb') as gz:
            with open(_DB_PATH, 'wb') as f:
                shutil.copyfileobj(gz, f)
    if os.path.exists(_DB_PATH):
        REAL_DB = _sql.connect(_DB_PATH)
        HAS_REAL_DATA = True
except Exception:
    pass

# ── 常见模型预设 ────────────────────────────────────
# 用户只需设置 LLM_PROVIDER，系统自动填充 base_url 和 model
PRESETS = {
    "deepseek":  {"base_url": "https://api.deepseek.com",    "model": "deepseek-chat"},
    "qwen":      {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus"},
    "glm":       {"base_url": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-4"},
    "moonshot":  {"base_url": "https://api.moonshot.cn/v1",   "model": "moonshot-v1-8k"},
    "openai":    {"base_url": "https://api.openai.com/v1",    "model": "gpt-4o"},
    "ollama":    {"base_url": "http://localhost:11434/v1",    "model": "qwen2.5:7b"},
}

def resolve_config():
    """解析配置：支持 LLM_PROVIDER 快捷切换 或 手工指定三项。"""
    provider = os.getenv("LLM_PROVIDER", "").lower()
    if provider in PRESETS:
        preset = PRESETS[provider]
        return {
            "base_url": os.getenv("LLM_BASE_URL", preset["base_url"]),
            "api_key": os.getenv("LLM_API_KEY", ""),
            "model": os.getenv("LLM_MODEL", preset["model"]),
            "max_tokens": None,  # 不限制回复长度，让模型自由发挥
            "temperature": 0.7,
            "enable_search": True,
        }
    return {
        "base_url": os.getenv("LLM_BASE_URL", "https://api.deepseek.com"),
        "api_key": os.getenv("LLM_API_KEY", ""),
        "model": os.getenv("LLM_MODEL", "deepseek-chat"),
        "max_tokens": None,  # 不限制回复长度，让模型自由发挥
        "temperature": 0.7,
        "enable_search": True,
    }

CONFIG = resolve_config()
SEARCH_ENGINE = "https://www.baidu.com/s?wd="

# ── 加载知识库 ──────────────────────────────────────
KNOWLEDGE_BASE_PATH = os.path.join(HERE, "knowledge_base.md")
SYSTEM_PROMPT_PATH = os.path.join(HERE, "system_prompt.md")

def load_file(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return ""

# ── 槽位管理器 ───────────────────────────────────────
SLOTS = {
    "province":     {"label": "省份", "filled": False, "value": ""},
    "score_rank":   {"label": "分数/位次", "filled": False, "value": ""},
    "subject":      {"label": "选科", "filled": False, "value": ""},
    "interest":     {"label": "专业兴趣/厌恶", "filled": False, "value": ""},
    "region":       {"label": "地域偏好", "filled": False, "value": ""},
    "family":       {"label": "家庭资源", "filled": False, "value": ""},
    "goal":         {"label": "核心诉求", "filled": False, "value": ""},
}

def filled_slots():
    return {k: v for k, v in SLOTS.items() if v["filled"]}

def missing_slots():
    return [k for k, v in SLOTS.items() if not v["filled"]]

def slots_summary():
    lines = []
    for k, v in SLOTS.items():
        status = "[OK]" if v["filled"] else "[ ]"
        lines.append(f"  {status} {v['label']}: {v['value'] if v['filled'] else '(未填)'}")
    return "\n".join(lines)

def extract_slots_from_message(msg):
    """从用户消息中自动提取槽位信息。"""
    updated = []
    msg_lower = msg.lower()

    # 省份检测
    provinces = [
        "北京", "天津", "上海", "重庆", "河北", "山西", "辽宁", "吉林",
        "黑龙江", "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南",
        "湖北", "湖南", "广东", "海南", "四川", "贵州", "云南", "陕西",
        "甘肃", "青海", "台湾", "内蒙古", "广西", "西藏", "宁夏", "新疆",
    ]
    for p in provinces:
        if p in msg and not SLOTS["province"]["filled"]:
            SLOTS["province"]["value"] = p
            SLOTS["province"]["filled"] = True
            updated.append(f"省份→{p}")

    # 分数/位次检测
    score_match = re.search(r'(\d{3})\s*分', msg)
    rank_match = re.search(r'(\d{4,7})\s*[位名]', msg)
    if score_match and not SLOTS["score_rank"]["filled"]:
        SLOTS["score_rank"]["value"] = score_match.group(1) + "分"
        SLOTS["score_rank"]["filled"] = True
        updated.append(f"分数→{score_match.group(1)}分")
    if rank_match and not SLOTS["score_rank"]["filled"]:
        SLOTS["score_rank"]["value"] = "位次" + rank_match.group(1)
        SLOTS["score_rank"]["filled"] = True
        updated.append(f"位次→{rank_match.group(1)}")
    if rank_match and SLOTS["score_rank"]["filled"]:
        SLOTS["score_rank"]["value"] += " / 位次" + rank_match.group(1)

    # 选科检测
    for subj in ["物理", "历史", "物化生", "物化地", "物化政", "物生政",
                  "史政地", "史政生", "史地生", "理科", "文科"]:
        if subj in msg and not SLOTS["subject"]["filled"]:
            SLOTS["subject"]["value"] = subj
            SLOTS["subject"]["filled"] = True
            updated.append(f"选科→{subj}")
            break

    # 地域检测
    for r in ["省内", "本省", "离家近", "北上广", "江浙沪", "北京", "上海",
               "深圳", "广州", "杭州", "成都", "武汉", "南京", "西安"]:
        if r in msg and not SLOTS["region"]["filled"]:
            SLOTS["region"]["value"] = r
            SLOTS["region"]["filled"] = True
            updated.append(f"地域→{r}")
            break

    # 家庭资源检测
    for fw in ["电力", "电网", "铁路", "医生", "教师", "老师", "做生意",
                "公务员", "烟草", "石油", "普通家庭", "没资源"]:
        if fw in msg and not SLOTS["family"]["filled"]:
            SLOTS["family"]["value"] = fw
            SLOTS["family"]["filled"] = True
            updated.append(f"家庭→{fw}")
            break

    # 诉求检测
    for g in ["就业", "考公", "考研", "稳定", "高薪", "赚钱", "深造", "出国"]:
        if g in msg and not SLOTS["goal"]["filled"]:
            SLOTS["goal"]["value"] = g
            SLOTS["goal"]["filled"] = True
            updated.append(f"诉求→{g}")
            break

    return updated

def is_consultation_intent(msg):
    """判断用户是否有志愿咨询意图。"""
    keywords = [
        "高考", "志愿", "选专业", "报学校", "报志愿", "填志愿", "选科",
        "分科", "考研", "选学校", "大学", "专业", "就业", "考公",
        "能报", "能上", "推荐", "建议", "帮忙看", "帮我选",
    ]
    return any(kw in msg for kw in keywords)

# ── 搜索功能 ─────────────────────────────────────────
def web_search(query, max_results=5):
    """搜索并抓取网页。百度搜索→提取URL→抓取正文。"""
    results = []
    try:
        url = SEARCH_ENGINE + urllib.parse.quote(query)
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        urls = re.findall(r'href="(https?://[^"]+)"', html)
        valid_urls = [u for u in urls if 'baidu.com' not in u and len(u) > 30][:max_results + 3]

        for target_url in valid_urls:
            if len(results) >= max_results:
                break
            try:
                page_req = urllib.request.Request(target_url, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                })
                with urllib.request.urlopen(page_req, timeout=8) as page_resp:
                    page_html = page_resp.read().decode("utf-8", errors="ignore")
                clean = re.sub(r'<script[^>]*>.*?</script>', '', page_html, flags=re.DOTALL)
                clean = re.sub(r'<style[^>]*>.*?</style>', '', clean, flags=re.DOTALL)
                clean = re.sub(r'<[^>]+>', ' ', clean)
                clean = re.sub(r'\s+', ' ', clean).strip()
                if len(clean) > 100:
                    results.append(clean[:600])
            except:
                continue

        if not results:
            snippets = re.findall(r'<span class="content-right_[^"]*">(.*?)</span>', html)
            for s in snippets[:max_results]:
                clean = re.sub(r'<[^>]+>', '', s).strip()
                if len(clean) > 20:
                    results.append(clean)

        return results if results else [f"(搜索无结果)"]
    except Exception as e:
        return [f"(搜索异常: {e})"]

def should_search(msg):
    """判断是否需要联网搜索——更积极触发。"""
    triggers = [
        "今年", "最新", "2026", "2025", "最近", "现在",
        "分数线", "录取分", "投档线", "招生计划", "录取",
        "政策", "变化", "改革", "新规",
        "就业率", "就业前景", "薪资", "月薪", "年薪",
        "排名", "第几名", "怎么样", "好不好",
        "能上", "能报", "能进", "稳不稳", "冲不冲",
        "多少分", "什么专业", "一本", "二本", "985", "211",
        "王牌专业", "优势", "缺点", "劣势", "值得", "推荐吗",
        "怎么样", "好不好", "评价", "口碑", "好不好考", "难不难",
    ]
    return any(t in msg for t in triggers)

# ── LLM 对话 ─────────────────────────────────────────
def cleanup_format(text):
    """去掉 AI 模型可能会漏的 Markdown 格式，确保输出像真人聊天。"""
    if not text:
        return text
    # 去掉 **粗体**
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    # 去掉 ### 标题
    text = re.sub(r'^#{1,6}\s*', '', text, flags=re.MULTILINE)
    # 去掉行首 - 列表标记
    text = re.sub(r'^\s*[-*]\s+', '', text, flags=re.MULTILINE)
    # 去掉行首数字编号 1. 2. 等
    text = re.sub(r'^\s*\d+[\.\、]\s*', '', text, flags=re.MULTILINE)
    return text.strip()

class GaokaoAdvisor:
    def __init__(self):
        self.client = OpenAI(base_url=CONFIG["base_url"], api_key=CONFIG["api_key"])
        self.knowledge_base = load_file(KNOWLEDGE_BASE_PATH)
        self.system_prompt = load_file(SYSTEM_PROMPT_PATH)
        self.conversation = []

    def _build_system_message(self):
        """构建系统消息，包含 system prompt + 知识库摘要 + 当前槽位状态。"""
        # 加载完整知识库，不做截断
        kb = self.knowledge_base if self.knowledge_base else ""
        kb_summary = kb  # 全量加载，不限制
        slots_status = slots_summary()
        search_note = ""
        if CONFIG["enable_search"]:
            search_note = "\n\n【联网搜索已启用。遇到最新政策/分数线/就业数据等问题时，请在回答中说明需要搜索最新信息，或使用搜索工具查询。】"

        full_system = f"""{self.system_prompt}

{search_note}

【知识库参考】
{kb_summary}

【当前用户信息采集状态】
{slots_status}

请在回答时：
1. 如果用户信息不全，追问缺失的槽位（用自然的方式，不要像填表）。
2. 如果信息已经足够（至少省份+分数/位次+核心诉求），给出冲稳保推荐。
3. 遇到需要最新数据时，提示用户"建议查XX官方渠道"，或主动搜索。
4. 保持直爽、接地气的风格。"""
        return full_system

    def chat(self, user_msg):
        """处理一轮对话。返回 assistant 的回复。"""
        # 检查意图
        if is_consultation_intent(user_msg):
            # 提取槽位
            updates = extract_slots_from_message(user_msg)
        else:
            updates = []

        # 构建消息
        system_msg = self._build_system_message()
        messages = [{"role": "system", "content": system_msg}]
        # 添加历史（最近10轮=20条消息）
        for h in self.conversation:  # 不限制轮数，保留全部对话
            messages.append(h)
        messages.append({"role": "user", "content": user_msg})

        # 如果有槽位更新，追加提示
        if updates:
            hint = f"(系统自动识别到: {', '.join(updates)}。请在回复中确认并追问缺失信息。)"
            messages.append({"role": "system", "content": hint})

        # 第一步：查真实数据库（优先级最高）
        search_results = None
        if HAS_REAL_DATA:
            # 省份从用户消息和槽位提取
            prov_match = re.findall(r'(北京|天津|上海|重庆|河北|山西|辽宁|吉林|黑龙江|江苏|浙江|安徽|福建|江西|山东|河南|湖北|湖南|广东|广西|海南|四川|贵州|云南|陕西|甘肃|青海|西藏|宁夏|新疆|内蒙古)', user_msg)
            # 学校名：直接从数据库搜——把消息中的每个2-8字片段扔进DB匹配
            school = None
            if HAS_REAL_DATA:
                # 提取所有可能的大学/学院关键词
                for m in re.finditer(r'(?:大学|学院)', user_msg):
                    end = m.end()
                    for start in range(max(0, end-12), end-1):
                        candidate = user_msg[start:end]
                        if len(candidate) >= 3 and any('一' <= c <= '鿿' for c in candidate):
                            test = query_real_data(None, candidate, None, None, 1)
                            if test:
                                school = candidate
                                break
                    if school:
                        break
                # 降级：用纯正则
                if not school:
                    fallback = re.findall(r'[一-鿿]{2,8}(?:大学|学院)', user_msg)
                    if fallback:
                        school = fallback[-1]  # 取最后一个
            rank_match = re.search(r'(\d{4,7})\s*[位名]', user_msg)

            # 省份优先从槽位取
            prov = prov_match[0] if prov_match else SLOTS.get('province', {}).get('value', '')
            rank = int(rank_match.group(1)) if rank_match else None

            # 专业关键词
            major_keywords = ['计算机','软件','电气','机械','土木','临床','口腔','法学','会计','金融',
                            '物联网','人工智能','大数据','电子','通信','自动化','材料','化工','生物',
                            '医学','护理','师范','英语','日语','新闻','设计','美术','音乐','体育',
                            '汉语言','思政','马克思','数学','物理','化学','历史','地理']
            major_kw = None
            for kw in major_keywords:
                if kw in user_msg:
                    major_kw = kw
                    break

            if prov or school:
                real_data = query_real_data(prov, school, major_kw, rank, limit=30)
                if not real_data and school:
                    real_data = query_real_data(None, school, major_kw, rank, limit=30)
                if not real_data and school and major_kw:
                    real_data = query_real_data(prov, school, None, rank, limit=30)
                if not real_data and school:
                    real_data = query_real_data(None, school, None, rank, limit=30)
                    # 跨省搜索——可能别的省有这个学校的数据
                    real_data = query_real_data(None, school, None, rank, limit=50)
                if real_data:
                    data_prov = real_data[0].get('province', prov) if real_data else prov
                    lines = [f"【真实录取数据 · {data_prov}】"]
                    for d in real_data:
                        extras = []
                        if d.get('year'): extras.append(f"{d['year']}年")
                        if d.get('score') and d['score'] > 1: extras.append(f"最低{d['score']}分")
                        if d.get('rank'): extras.append(f"位次{d['rank']}")
                        extra_str = ' / '.join(extras)
                        major_str = f" · {d['major']}" if d['major'] and d['major'] != d['school'] else ''
                        lines.append(f"· {d['school']}{major_str} — {extra_str}")
                    search_hint = '\n'.join(lines[:20])
                    if prov and prov not in str(data_prov):
                        search_hint += f'\n\n⚠ 注意：以上为{data_prov}省数据（{prov}暂无该学校数据），位次参考需根据各省差异调整。'
                    # 格式化数据摘要 + 跨省警告
                    data_summary = '\n'.join(lines[:15])
                    if prov and prov not in str(data_prov):
                        data_summary += f'\n\n⚠ {prov}暂无该学校录取数据，以上为{data_prov}省数据，仅作参考。'
                    messages.append({"role": "user", "content": f"【真实数据/跨省参考】\n{data_summary}\n\n如果显示跨省警告，必须首先告诉用户'该省暂无数据，以下为XX省参考'。如果完全没有数据，直接说'数据库暂无记录，建议查官网'，不准编造。"})
                    search_results = "real_data_used"
                    try:
                        print(f'\n  [数据] {lines[0]} ({len(lines)-1}条)')
                    except: pass

        # 第二步：网上搜索（有数据也搜补充，没数据全靠搜）
        web_info = None
        if CONFIG["enable_search"] and should_search(user_msg):
            search_query = user_msg[:120]
            # 搜两轮：权威来源+宽泛
            web_results1 = web_search(search_query + " 录取 位次 site:gaokao.cn OR site:eol.cn", max_results=5)
            web_results2 = web_search(search_query + " 分数线 教育考试院 OR 招生网", max_results=5)
            all_web = (web_results1 or []) + (web_results2 or [])
            # 去重
            seen = set()
            unique_web = []
            for r in all_web:
                key = r[:50]
                if key not in seen and len(r) > 30:
                    seen.add(key)
                    unique_web.append(r)
            if unique_web:
                web_info = "\n".join(f"· {r[:250]}" for r in unique_web[:8])
                if web_info:
                    messages.append({"role": "system", "content": f"【网上搜索到的信息·综合{len(unique_web)}条】\n{web_info}\n\n你根据以上多条网上信息交叉验证，给出综合分析。必须明确标注'根据网上公开信息综合分析'。不准把模糊信息说成确定数字。如果多条信息矛盾，要指出。"})
                    if not search_results:
                        search_results = "web_only"

        # 最终没数据时，明确禁止编造
        if not search_results:
            messages.append({"role": "system", "content": "【死命令】数据库和搜索均未找到该学校/专业在该省的录取数据。你必须明确告诉用户没有数据，建议查省考试院官网。禁止编造任何数字。"})

        # 调用 LLM
        try:
            kwargs = dict(
                model=CONFIG["model"],
                messages=messages,
                temperature=CONFIG["temperature"],
            )
            if CONFIG["max_tokens"] is not None:
                kwargs["max_tokens"] = CONFIG["max_tokens"]
            resp = self.client.chat.completions.create(**kwargs)
            reply = resp.choices[0].message.content
        except Exception as e:
            reply = f"出错了：{e}\n请检查 API 配置（base_url, api_key, model 是否正确）。"

        # 清理格式
        reply = cleanup_format(reply)

        # 数据先行注入回复
        if search_results == "real_data_used":
            search_hint_clean = re.sub(r'【[^】]+】', '', search_hint)[:800]
            reply = f"[真实录取数据]\n{search_hint_clean}\n\n[AI分析]\n{reply}"
        elif search_results == "web_only":
            web_clean = (web_info or '')[:600]
            if web_clean:
                reply = f"[网上公开信息·仅供参考]\n{web_clean}\n\n[AI分析]\n{reply}"
            web_clean = web_info[:600]
            reply = f"[网上公开信息·仅供参考]\n{web_clean}\n\n[AI分析]\n{reply}"

        # 保存对话历史
        self.conversation.append({"role": "user", "content": user_msg})
        self.conversation.append({"role": "assistant", "content": reply})

        return reply

    def reset(self):
        """重置对话和槽位。"""
        self.conversation = []
        for k in SLOTS:
            SLOTS[k]["filled"] = False
            SLOTS[k]["value"] = ""

# ── CLI 界面 ─────────────────────────────────────────
def test_connection():
    """测试 API 连接是否正常。"""
    try:
        client = OpenAI(base_url=CONFIG["base_url"], api_key=CONFIG["api_key"])
        resp = client.chat.completions.create(
            model=CONFIG["model"],
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=5,
        )
        return True, resp.choices[0].message.content
    except Exception as e:
        return False, str(e)

def main():
    import textwrap

    print("=" * 60)
    print("  高考志愿顾问 Agent")
    print(f"  模型: {CONFIG['model']}")
    print(f"  搜索: {'开' if CONFIG['enable_search'] else '关'}")
    print("=" * 60)

    if not CONFIG["api_key"]:
        print("\n❌ 未检测到 API Key！")
        print("   请复制 .env.example 为 .env 并填入你的 API Key。")
        print("   或者设置环境变量 LLM_API_KEY=你的key")
        print()
        print("   快速开始（任选一种）：")
        print("   · DeepSeek:  set LLM_PROVIDER=deepseek && set LLM_API_KEY=sk-xxx")
        print("   · 通义千问:  set LLM_PROVIDER=qwen && set LLM_API_KEY=sk-xxx")
        print("   · 智谱GLM:   set LLM_PROVIDER=glm && set LLM_API_KEY=xxx")
        input("\n   按回车退出...")
        return

    # 测试连接
    print("  正在测试 API 连接...", end=" ", flush=True)
    ok, msg = test_connection()
    if ok:
        print("[OK] 连接成功")
    else:
        print(f"[X] 连接失败: {msg[:200]}")
        print()
        # 智能诊断
        if "401" in msg or "Authentication" in msg:
            print("   → Key 无效或格式错误。检查：")
            print("   1. Key 是不是 sk- 完整开头？前后有没有空格？")
            print("   2. 去 API 平台确认 Key 状态是'有效'")
            print("   3. 试试只留两行：LLM_PROVIDER=deepseek + LLM_API_KEY=你的key")
        elif "402" in msg or "Insufficient" in msg or "Balance" in msg:
            print("   → 账户余额不足！去 API 平台充值，或换通义千问（有免费额度）")
        elif "403" in msg or "Forbidden" in msg:
            print("   → Key 没有权限。检查 Key 是否开通了 chat/completions 接口")
        elif "404" in msg or "Not Found" in msg:
            print("   → 接口地址不对。试试 BASE_URL 末尾加 /v1")
        elif "timeout" in msg.lower() or "connect" in msg.lower():
            print("   → 网络连不上 API 服务器。检查网络/代理")
        else:
            print("   检查 .env 中 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL")
        input("\n   按回车退出...")
        return

    print("=" * 60)
    print("  命令: /paste 粘贴 | /slots 信息 | /reset 重置 | /quit 退出")
    print("  直接描述你的情况，我会帮你分析。")
    print("=" * 60)
    print()

    advisor = GaokaoAdvisor()

    while True:
        try:
            user_input = input("\n[You] 你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if not user_input:
            continue

        if user_input == "/quit":
            print("再见！")
            break
        elif user_input == "/reset":
            advisor.reset()
            print("[OK] 已重置对话和信息采集")
            continue
        elif user_input == "/slots":
            print(slots_summary())
            continue
        elif user_input == "/paste":
            cb = read_clipboard()
            if cb and cb.strip():
                user_input = " ".join(cb.strip().split("\n"))
                print(f"📋 剪贴板已读取 ({len(user_input)}字)")
                print(f"📋 内容: {user_input[:100]}...")
            else:
                print("📋 剪贴板为空或无法读取")
                continue

        print("\n🤖 顾问: ", end="", flush=True)
        reply = advisor.chat(user_input)
        print(reply)

if __name__ == "__main__":
    main()
