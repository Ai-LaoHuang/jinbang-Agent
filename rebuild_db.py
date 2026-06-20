#!/usr/bin/env python3
"""
高考录取数据库 — 完全重建
逐省独立解析，统一Schema，AI可查询
"""
import os, sys, re, sqlite3, gzip, shutil, time
import xlrd, openpyxl

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_BASE = r'E:\桌面\高考志愿填报\26年最新\全国31省市投档分数线（24年）'
DB_PATH = os.path.join(HERE, 'admission_clean.db')

PROVINCES = ['北京','天津','上海','重庆','河北','山西','辽宁','吉林','黑龙江',
             '江苏','浙江','安徽','福建','江西','山东','河南','湖北','湖南',
             '广东','广西','海南','四川','贵州','云南','西藏','陕西','甘肃',
             '青海','宁夏','新疆','内蒙古']

# ============================================================
# 辅助函数
# ============================================================
def clean_cell(v):
    """清理单元格值"""
    if v is None: return ''
    if isinstance(v, float):
        if v == int(v): return str(int(v))
        return str(v)
    return str(v).strip()

def detect_category(filename, row_text, province):
    """检测科类：物理类/历史类/理科/文科/艺术类/体育类/综合"""
    text = filename + ' ' + row_text
    if any(kw in text for kw in ['物理类','物理科目','物理等科目','物理学科组','理工类','理科']):
        return '物理类'
    if any(kw in text for kw in ['历史类','历史科目','历史等科目','历史学科组','文史类','文科']):
        return '历史类'
    if any(kw in text for kw in ['艺术','美术','音乐','舞蹈','播音','编导','表演','书法','服表']):
        return '艺术类'
    if any(kw in text for kw in ['体育','体理','体文']):
        return '体育类'
    if province in ['浙江','上海','北京','天津','山东','海南']:
        return '综合'
    return ''  # unknown

# ============================================================
# 各省解析器
# ============================================================

def parse_zhejiang():
    """浙江 — 完美数据源：学校+专业+分数+位次"""
    results = []
    prov_dir = os.path.join(DATA_BASE, '浙江')
    if not os.path.isdir(prov_dir): return results

    # 普通类第一段 (main batch)
    f1 = os.path.join(prov_dir, '浙江省2024年普通高校招生普通类第一段平行投档分数线表.xls')
    if os.path.exists(f1):
        results.extend(_parse_zj_common(f1, '浙江', 2024, '普通类第一段'))

    # 普通类第二段
    f2 = os.path.join(prov_dir, '浙江省2024年普通高校招生普通类第二段平行投档分数线表.xls')
    if os.path.exists(f2):
        results.extend(_parse_zj_common(f2, '浙江', 2024, '普通类第二段'))

    # 艺术类统考批第一段
    f3 = os.path.join(prov_dir, '浙江省2024年普通高校招生艺术类统考批第一段平行投档分数线表.xls')
    if os.path.exists(f3):
        results.extend(_parse_zj_art(f3, '浙江', 2024, '艺术类第一段'))

    # 艺术类统考批第二段
    f4 = os.path.join(prov_dir, '浙江省2024年普通高校招生艺术类统考批第二段平行投档分数线表.xls')
    if os.path.exists(f4):
        results.extend(_parse_zj_art(f4, '浙江', 2024, '艺术类第二段'))

    # 体育类
    f5 = os.path.join(prov_dir, '浙江省2024年普通高校招生体育类第一段平行投档分数线表.xls')
    if os.path.exists(f5):
        results.extend(_parse_zj_sport(f5, '浙江', 2024, '体育类第一段'))

    return results

def _parse_zj_common(filepath, province, year, batch):
    """浙江普通类: 学校代号|学校名称|专业代号|专业名称|计划数|分数线|位次"""
    results = []
    try:
        wb = xlrd.open_workbook(filepath)
        ws = wb.sheet_by_index(0)
        for r in range(1, ws.nrows):
            vals = [clean_cell(ws.cell_value(r, c)) for c in range(7)]
            if not vals[1] or len(vals[1]) < 2: continue
            # vals: [school_code, school_name, major_code, major_name, quota, score, rank]
            try:
                score = int(float(vals[5])) if vals[5] else None
                rank = int(float(vals[6])) if vals[6] else None
            except: score = rank = None
            if not score and not rank: continue
            results.append({
                'province': province, 'year': year, 'category': '综合',
                'batch': batch, 'school_name': vals[1],
                'major_name': vals[3], 'score': score, 'rank': rank,
                'quota': int(float(vals[4])) if vals[4] and vals[4].replace('.','').isdigit() else None,
                'source_file': os.path.basename(filepath)
            })
        wb.release_resources()
    except Exception as e:
        print(f'  [WARN] {os.path.basename(filepath)}: {e}')
    return results

def _parse_zj_art(filepath, province, year, batch):
    """浙江艺术类: 科类代码|科类名称|院校代号|院校名称|专业代号|专业名称|计划数|综合分"""
    results = []
    try:
        wb = xlrd.open_workbook(filepath)
        ws = wb.sheet_by_index(0)
        for r in range(1, ws.nrows):
            vals = [clean_cell(ws.cell_value(r, c)) for c in range(8)]
            if not vals[3] or len(vals[3]) < 2: continue
            try:
                score = int(float(vals[7])) if vals[7] else None
            except: score = None
            if not score: continue
            results.append({
                'province': province, 'year': year, 'category': f'艺术类-{vals[1]}',
                'batch': batch, 'school_name': vals[3],
                'major_name': vals[5], 'score': score, 'rank': None,
                'quota': int(float(vals[6])) if vals[6] else None,
                'source_file': os.path.basename(filepath)
            })
        wb.release_resources()
    except Exception as e:
        print(f'  [WARN] {os.path.basename(filepath)}: {e}')
    return results

def _parse_zj_sport(filepath, province, year, batch):
    """浙江体育类"""
    results = []
    try:
        wb = xlrd.open_workbook(filepath)
        ws = wb.sheet_by_index(0)
        for r in range(1, ws.nrows):
            vals = [clean_cell(ws.cell_value(r, c)) for c in range(7)]
            if not vals[1] or len(vals[1]) < 2: continue
            try:
                score = int(float(vals[5])) if vals[5] else None
            except: score = None
            if not score: continue
            results.append({
                'province': province, 'year': year, 'category': '体育类',
                'batch': batch, 'school_name': vals[1],
                'major_name': vals[3], 'score': score, 'rank': None,
                'quota': int(float(vals[4])) if vals[4] else None,
                'source_file': os.path.basename(filepath)
            })
        wb.release_resources()
    except Exception as e:
        print(f'  [WARN] {os.path.basename(filepath)}: {e}')
    return results


def parse_shandong():
    """山东 — 有位次无分数，列: [空,专业,院校,计划数,最低位次]"""
    results = []
    prov_dir = os.path.join(DATA_BASE, '山东')
    if not os.path.isdir(prov_dir): return results

    for fname in os.listdir(prov_dir):
        if not fname.endswith('.xls'): continue
        fp = os.path.join(prov_dir, fname)
        if '常规批第1次' in fname: cat='综合'; batch='常规批第1次'
        elif '常规批第2次' in fname: cat='综合'; batch='常规批第2次'
        elif '常规批第3次' in fname: cat='综合'; batch='常规批第3次'
        else: continue

        try:
            wb = xlrd.open_workbook(fp)
            ws = wb.sheet_by_index(0)
            for r in range(2, ws.nrows):
                major_raw = clean_cell(ws.cell_value(r, 1))
                school_raw = clean_cell(ws.cell_value(r, 2))
                quota_str = clean_cell(ws.cell_value(r, 3))
                rank_str = clean_cell(ws.cell_value(r, 4))

                if not school_raw or len(school_raw) < 2: continue
                # Remove school code prefix like "A001"
                school = re.sub(r'^[A-Z]\d+\s*', '', school_raw).strip()
                if not school: school = school_raw
                # Clean major: remove leading number
                major = re.sub(r'^\d+\s*', '', major_raw).strip()

                # Parse rank (handle "前50" = top 50)
                rank = None
                try:
                    if '前' in rank_str:
                        rank = int(re.sub(r'[^0-9]', '', rank_str) or '0')
                    else:
                        rank = int(float(rank_str))
                except: pass
                if not rank: continue

                quota = None
                try: quota = int(float(quota_str)) if quota_str else None
                except: pass

                results.append({
                    'province': '山东', 'year': 2024, 'category': cat,
                    'batch': batch, 'school_name': school,
                    'major_name': major, 'score': None, 'rank': rank,
                    'quota': quota, 'source_file': fname
                })
            wb.release_resources()
        except Exception as e:
            print(f'  [WARN] {fname}: {e}')
    return results

def parse_hebei():
    """河北 — 有分数无位次，但历史/物理分文件，有具体专业"""
    results = []
    prov_dir = os.path.join(DATA_BASE, '河北')
    if not os.path.isdir(prov_dir): return results

    for fname in os.listdir(prov_dir):
        if not fname.endswith('.xlsx'): continue
        fp = os.path.join(prov_dir, fname)

        # 判断科类
        if '历史' in fname: cat = '历史类'
        elif '物理' in fname: cat = '物理类'
        else: cat = ''

        # 判断批次
        if '本科批' in fname: batch = '本科批'
        elif '本科提前批' in fname: batch = '本科提前批'
        elif '专科批' in fname: batch = '专科批'
        else: batch = ''

        if not batch: continue

        try:
            wb = openpyxl.load_workbook(fp, data_only=True)
            ws = wb.active
            for row in ws.iter_rows(min_row=4, values_only=True):  # skip 3 header rows
                vals = [str(v).strip() if v else '' for v in row[:7]]
                school = vals[1] if len(vals) > 1 else ''
                major = vals[3] if len(vals) > 3 else ''
                score_str = vals[4] if len(vals) > 4 else ''
                if not school or not score_str: continue
                try:
                    score = int(float(score_str))
                except:
                    continue
                results.append({
                    'province': '河北', 'year': 2024, 'category': cat,
                    'batch': batch, 'school_name': school,
                    'major_name': major, 'score': score, 'rank': None,
                    'quota': None, 'source_file': fname
                })
            wb.close()
        except Exception as e:
            print(f'  [WARN] {fname}: {e}')
    return results


def parse_chongqing():
    """重庆 — 有科类/专业/分数/位次"""
    results = []
    prov_dir = os.path.join(DATA_BASE, '重庆')
    if not os.path.isdir(prov_dir): return results

    for fname in os.listdir(prov_dir):
        if not fname.endswith('.xlsx'): continue
        fp = os.path.join(prov_dir, fname)

        # 判断科类和批次
        fname_lower = fname.lower()
        if '历史' in fname: cat = '历史类'
        elif '物理' in fname: cat = '物理类'
        else: cat = ''

        if '本科批' in fname: batch = '本科批'
        elif '提前批' in fname: batch = '提前批'
        elif '专科' in fname: batch = '专科批'
        else: batch = ''

        try:
            wb = openpyxl.load_workbook(fp, data_only=True)
            ws = wb.active
            # Headers: 科类, 院校代号, 院校名称, 专业代号, 专业名称, 投档最低分, 位次之和, 备注
            for row in ws.iter_rows(min_row=3, values_only=True):
                vals = [str(v).strip() if v else '' for v in row[:9]]
                if not vals: continue
                school = vals[2] if len(vals) > 2 else ''
                major = vals[4] if len(vals) > 4 else ''
                score_str = vals[5] if len(vals) > 5 else ''
                rank_str = vals[6] if len(vals) > 6 else ''

                # 从第一列补充科类
                row_cat = cat
                if vals[0] in ['历史类','物理类','历史','物理']:
                    row_cat = vals[0].replace('历史','历史类').replace('物理','物理类')

                if not school: continue
                try:
                    score = int(float(score_str)) if score_str else None
                    rank = int(float(rank_str)) if rank_str and rank_str.replace('.','').isdigit() else None
                except:
                    score = rank = None
                if not score and not rank: continue

                results.append({
                    'province': '重庆', 'year': 2024, 'category': row_cat or cat,
                    'batch': batch, 'school_name': school,
                    'major_name': major, 'score': score, 'rank': rank,
                    'quota': None, 'source_file': fname
                })
            wb.close()
        except Exception as e:
            print(f'  [WARN] {fname}: {e}')
    return results


def parse_hubei():
    """湖北 — 有科类/专业组/分数/位次之和"""
    results = []
    prov_dir = os.path.join(DATA_BASE, '湖北')
    if not os.path.isdir(prov_dir): return results

    for fname in os.listdir(prov_dir):
        if not fname.endswith(('.xls','.xlsx')): continue
        if '一分一段' in fname: continue
        fp = os.path.join(prov_dir, fname)

        # 判断科类
        if '历史' in fname: cat = '历史类'
        elif '物理' in fname: cat = '物理类'
        else: cat = ''

        # 判断批次
        if '本科批' in fname or '普通类本科' in fname: batch = '本科批'
        elif '提前批' in fname: batch = '提前批'
        elif '专科' in fname: batch = '专科批'
        elif '艺术' in fname: cat = '艺术类'; batch = '艺术批'
        elif '体育' in fname: cat = '体育类'; batch = '体育批'
        else: batch = ''

        try:
            if fname.endswith('.xls'):
                wb = xlrd.open_workbook(fp)
                ws = wb.sheet_by_index(0)
                # Headers: 科类, 计划类别, 院校代号, 院校名称, 专业组代号, 专业组名称, 投档线
                for r in range(3, ws.nrows):
                    vals = [clean_cell(ws.cell_value(r, c)) for c in range(8)]
                    school = vals[3] if len(vals) > 3 else ''
                    major_group = vals[5] if len(vals) > 5 else ''
                    score_str = vals[6] if len(vals) > 6 else ''
                    if not school: continue
                    try: score = int(float(score_str)) if score_str else None
                    except: score = None
                    if not score: continue
                    results.append({
                        'province': '湖北', 'year': 2024, 'category': cat,
                        'batch': batch, 'school_name': school,
                        'major_name': major_group, 'score': score, 'rank': None,
                        'quota': None, 'source_file': fname
                    })
                wb.release_resources()
            else:
                wb = openpyxl.load_workbook(fp, data_only=True)
                ws = wb.active
                for row in ws.iter_rows(min_row=3, values_only=True):
                    vals = [str(v).strip() if v else '' for v in row[:8]]
                    school = vals[3] if len(vals) > 3 else ''
                    major_group = vals[5] if len(vals) > 5 else ''
                    score_str = vals[6] if len(vals) > 6 else ''
                    if not school: continue
                    try: score = int(float(score_str)) if score_str else None
                    except: score = None
                    if not score: continue
                    results.append({
                        'province': '湖北', 'year': 2024, 'category': cat,
                        'batch': batch, 'school_name': school,
                        'major_name': major_group, 'score': score, 'rank': None,
                        'quota': None, 'source_file': fname
                    })
                wb.close()
        except Exception as e:
            print(f'  [WARN] {fname}: {e}')
    return results


def parse_jiangsu():
    """江苏 — 有分数无位次，学校+专业组级别"""
    results = []
    prov_dir = os.path.join(DATA_BASE, '江苏')
    if not os.path.isdir(prov_dir): return results

    for fname in os.listdir(prov_dir):
        fp = os.path.join(prov_dir, fname)
        if not fname.endswith('.xls'): continue
        if '一分一段' in fname: continue

        # 判断科类
        if '历史' in fname: cat = '历史类'
        elif '物理' in fname: cat = '物理类'
        else: cat = ''

        # 判断批次
        if '本科批次' in fname and '提前' not in fname: batch = '本科批'
        elif '提前批次' in fname or '提前批' in fname: batch = '提前批'
        elif '专科' in fname: batch = '专科批'
        elif '艺术' in fname: cat = '艺术类'; batch = '艺术批'
        elif '体育' in fname: cat = '体育类'; batch = '体育批'
        else: batch = ''

        try:
            wb = xlrd.open_workbook(fp)
            ws = wb.sheet_by_index(0)
            for r in range(4, ws.nrows):
                vals = [clean_cell(ws.cell_value(r, c)) for c in range(5)]
                school_code = vals[0]
                school_major = vals[1]  # contains both school and major group
                score_str = vals[2]
                if not school_major: continue
                try: score = int(float(score_str)) if score_str else None
                except: score = None
                if not score: continue

                # Parse school and major group from combined field
                # Format: "院校名称专业组号(选科要求)" or similar
                school = school_major
                major = ''
                if '(' in school_major:
                    parts = school_major.split('(', 1)
                    school = parts[0]
                    major = '(' + parts[1] if len(parts) > 1 else ''

                results.append({
                    'province': '江苏', 'year': 2024, 'category': cat,
                    'batch': batch, 'school_name': school[:80],
                    'major_name': major[:200], 'score': score, 'rank': None,
                    'quota': None, 'source_file': fname
                })
            wb.release_resources()
        except Exception as e:
            print(f'  [WARN] {fname}: {e}')
    return results


def parse_hunan():
    """湖南 — 有科类/专业组/投档线"""
    results = []
    prov_dir = os.path.join(DATA_BASE, '湖南')
    if not os.path.isdir(prov_dir): return results

    for fname in os.listdir(prov_dir):
        if not fname.endswith(('.xls','.xlsx')): continue
        if '一分一段' in fname or '对口' in fname: continue
        fp = os.path.join(prov_dir, fname)

        if '历史' in fname: cat = '历史类'
        elif '物理' in fname: cat = '物理类'
        else: cat = ''

        if '本科批' in fname: batch = '本科批'
        elif '提前批' in fname: batch = '提前批'
        elif '专科' in fname: batch = '专科批'
        elif '艺术' in fname: cat = '艺术类'; batch = '艺术批'
        else: batch = ''

        try:
            if fname.endswith('.xls'):
                wb = xlrd.open_workbook(fp)
                ws = wb.sheet_by_index(0)
                for r in range(3, ws.nrows):
                    vals = [clean_cell(ws.cell_value(r, c)) for c in range(8)]
                    row_cat = vals[0] if len(vals) > 0 else cat
                    school = vals[3] if len(vals) > 3 else ''
                    major_group = vals[5] if len(vals) > 5 else ''
                    score_str = vals[6] if len(vals) > 6 else ''
                    if not school: continue
                    try: score = int(float(score_str)) if score_str else None
                    except: score = None
                    if not score: continue
                    results.append({
                        'province': '湖南', 'year': 2024, 'category': row_cat or cat,
                        'batch': batch, 'school_name': school,
                        'major_name': major_group, 'score': score, 'rank': None,
                        'quota': None, 'source_file': fname
                    })
                wb.release_resources()
            else:
                wb = openpyxl.load_workbook(fp, data_only=True)
                ws = wb.active
                for row in ws.iter_rows(min_row=3, values_only=True):
                    vals = [str(v).strip() if v else '' for v in row[:8]]
                    school = vals[3] if len(vals) > 3 else ''
                    major_group = vals[5] if len(vals) > 5 else ''
                    score_str = vals[6] if len(vals) > 6 else ''
                    if not school: continue
                    try: score = int(float(score_str)) if score_str else None
                    except: score = None
                    if not score: continue
                    results.append({
                        'province': '湖南', 'year': 2024, 'category': cat,
                        'batch': batch, 'school_name': school,
                        'major_name': major_group, 'score': score, 'rank': None,
                        'quota': None, 'source_file': fname
                    })
                wb.close()
        except Exception as e:
            print(f'  [WARN] {fname}: {e}')
    return results


def parse_neimenggu():
    """内蒙古 — B批次仅有分数无位次无专业"""
    results = []
    prov_dir = os.path.join(DATA_BASE, '内蒙古')
    if not os.path.isdir(prov_dir): return results

    for fname in os.listdir(prov_dir):
        if not fname.endswith('.xlsx'): continue
        fp = os.path.join(prov_dir, fname)

        try:
            wb = openpyxl.load_workbook(fp, data_only=True)
            ws = wb.active
            # Headers: 院校代号, 院校名称, 科类, 投档最低分, 备注
            for row in ws.iter_rows(min_row=2, values_only=True):
                vals = [str(v).strip() if v else '' for v in row[:5]]
                school = vals[1] if len(vals) > 1 else ''
                cat_raw = vals[2] if len(vals) > 2 else ''
                score_str = vals[3] if len(vals) > 3 else ''
                note = vals[4] if len(vals) > 4 else ''

                cat = '文科' if '文' in cat_raw else ('理科' if '理' in cat_raw else '')

                if not school: continue
                try: score = int(float(score_str)) if score_str else None
                except: score = None
                if not score: continue

                results.append({
                    'province': '内蒙古', 'year': 2024, 'category': cat,
                    'batch': '本科一批B' if '一批B' in fname else '本科二批B',
                    'school_name': school,
                    'major_name': note, 'score': score, 'rank': None,
                    'quota': None, 'source_file': fname
                })
            wb.close()
        except Exception as e:
            print(f'  [WARN] {fname}: {e}')
    return results


def parse_jilin_heilongjiang():
    """吉林+黑龙江 — 仅有招生计划，无录取分/位次，不可用"""
    # These provinces only have admission plans (招生计划) with quota/tuition,
    # not actual admission scores/ranks. Skip for now.
    return []


# ============================================================
# 主建库流程
# ============================================================
def build_database():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DROP TABLE IF EXISTS admission")
    conn.execute("""
        CREATE TABLE admission (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            province TEXT NOT NULL,
            year INTEGER NOT NULL,
            category TEXT,
            batch TEXT,
            school_name TEXT NOT NULL,
            major_name TEXT,
            score INTEGER,
            rank INTEGER,
            quota INTEGER,
            source_file TEXT
        )
    """)

    # Indexes for AI queries
    conn.execute("CREATE INDEX idx_adm_province ON admission(province)")
    conn.execute("CREATE INDEX idx_adm_year ON admission(year)")
    conn.execute("CREATE INDEX idx_adm_category ON admission(category)")
    conn.execute("CREATE INDEX idx_adm_school ON admission(school_name)")
    conn.execute("CREATE INDEX idx_adm_major ON admission(major_name)")
    conn.execute("CREATE INDEX idx_adm_score ON admission(score)")
    conn.execute("CREATE INDEX idx_adm_rank ON admission(rank)")
    conn.execute("CREATE INDEX idx_adm_prov_rank ON admission(province, rank)")
    conn.execute("CREATE INDEX idx_adm_prov_score ON admission(province, score)")

    parsers = [
        ('浙江', parse_zhejiang),
        ('山东', parse_shandong),
        ('河北', parse_hebei),
        ('重庆', parse_chongqing),
        ('湖北', parse_hubei),
        ('江苏', parse_jiangsu),
        ('湖南', parse_hunan),
        ('内蒙古', parse_neimenggu),
    ]

    total = 0
    for name, parser in parsers:
        print(f'\n[{name}] 解析中...')
        results = parser()
        if results:
            for r in results:
                conn.execute(
                    """INSERT INTO admission(province, year, category, batch, school_name, major_name, score, rank, quota, source_file)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (r['province'], r['year'], r.get('category',''), r.get('batch',''),
                     r['school_name'], r.get('major_name',''), r.get('score'), r.get('rank'),
                     r.get('quota'), r.get('source_file',''))
                )
            total += len(results)
            print(f'  -> {len(results)} 条记录')
        else:
            print(f'  -> 无数据')

    conn.commit()

    # Stats
    prov_count = conn.execute("SELECT COUNT(DISTINCT province) FROM admission").fetchone()[0]
    school_count = conn.execute("SELECT COUNT(DISTINCT school_name) FROM admission").fetchone()[0]
    total_rows = conn.execute("SELECT COUNT(*) FROM admission").fetchone()[0]
    has_rank = conn.execute("SELECT COUNT(*) FROM admission WHERE rank IS NOT NULL").fetchone()[0]
    has_score = conn.execute("SELECT COUNT(*) FROM admission WHERE score IS NOT NULL").fetchone()[0]

    print(f'\n===== 建库完成 =====')
    print(f'省份: {prov_count}  学校: {school_count}  总行数: {total_rows}')
    print(f'有分数: {has_score}  有位次: {has_rank}')

    conn.close()
    return total_rows


if __name__ == '__main__':
    t0 = time.time()
    build_database()
    print(f'\n耗时: {time.time()-t0:.0f}秒')
