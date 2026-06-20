#!/usr/bin/env python3
"""清洗录取数据库——去脏数据，保留真实记录"""
import sqlite3, sys; sys.stdout.reconfigure(encoding='utf-8')

SRC = r'E:\桌面\张雪峰agent\all_provinces.db'
DST = r'E:\桌面\张雪峰agent\admission_clean.db'
PROVINCE_NAMES = ['北京','天津','上海','重庆','河北','山西','辽宁','吉林','黑龙江','江苏','浙江','安徽','福建','江西','山东','河南','湖北','湖南','广东','广西','海南','四川','贵州','云南','西藏','陕西','甘肃','青海','宁夏','新疆','内蒙古']

src = sqlite3.connect(SRC)
# 先看结构
cols = [c[1] for c in src.execute('PRAGMA table_info(admission)').fetchall()]
print(f'Columns: {cols}')

# 复制表结构到新库
dst = sqlite3.connect(DST)
dst.execute('DROP TABLE IF EXISTS admission')
col_defs = []
for c in cols:
    if c in ('province','school','major','source'):
        col_defs.append(f'"{c}" TEXT')
    else:
        col_defs.append(f'"{c}" INTEGER')
dst.execute(f'CREATE TABLE admission ({", ".join(col_defs)})')

# 过滤条件
# 1. 学校名必须含"大学"或"学院"
school_filter = "(school LIKE '%大学%' OR school LIKE '%学院%')"
# 2. 学校名不能是垃圾文本
bad_school = ['化学专业是一种','学分','科目','不限','选考','必选','首选','再选','科目要求','专业组']
for bs in bad_school:
    school_filter += f" AND school NOT LIKE '%{bs}%'"
# 3. 专业名不是省名且不是纯数字/字母
major_filter = ' AND '.join([f"major != '{p}'" for p in PROVINCE_NAMES])
major_filter += " AND major != '本科' AND major != '' AND major GLOB '*[一-鿿]*'"  # 专业名至少含一个汉字
# 4. 位次>100（顶尖学校位次就是几百）且排除高频重复值（行号冒充位次）
valid_filter = f"({school_filter}) AND ({major_filter}) AND (rank > 100 OR (score >= 300 AND score <= 750))"

# 先统计各省
print('\n=== 清洗前各省分布 ===')
for row in src.execute(f'SELECT province, COUNT(*) FROM admission GROUP BY province ORDER BY COUNT(*) DESC').fetchall():
    bad = src.execute(f'SELECT COUNT(*) FROM admission WHERE province=? AND NOT ({valid_filter})', (row[0],)).fetchone()[0]
    good = row[1] - bad
    print(f'{row[0]:8s} 总{row[1]:10,d}  脏{bad:10,d}  净{good:10,d}')

# 执行清洗
print('\n清洗中...')
total = 0
placeholders = ",".join("?" * len(cols))
for row in src.execute(f'SELECT {",".join(cols)} FROM admission WHERE {valid_filter}'):
    dst.execute(f'INSERT INTO admission VALUES ({placeholders})', row)
    total += 1
    if total % 1000000 == 0:
        print(f'  {total:,d} records...')

dst.commit()

# 验证
print(f'\n=== 清洗后 ===')
prov_count = dst.execute('SELECT COUNT(DISTINCT province) FROM admission').fetchone()[0]
total_final = dst.execute('SELECT COUNT(*) FROM admission').fetchone()[0]
rank_count = dst.execute('SELECT COUNT(*) FROM admission WHERE rank > 0').fetchone()[0]
score_count = dst.execute('SELECT COUNT(*) FROM admission WHERE score > 0').fetchone()[0]
school_count = dst.execute('SELECT COUNT(DISTINCT school) FROM admission').fetchone()[0]

print(f'省份: {prov_count}')
print(f'总记录: {total_final:,d}')
print(f'有位次: {rank_count:,d}')
print(f'有分数: {score_count:,d}')
print(f'学校数: {school_count:,d}')

# 各省清洗后
print('\n各省清洗后:')
for row in dst.execute('SELECT province, COUNT(*), SUM(CASE WHEN rank>0 THEN 1 ELSE 0 END), MIN(rank), MAX(rank), MIN(year), MAX(year) FROM admission GROUP BY province ORDER BY COUNT(*) DESC').fetchall():
    print(f'{row[0]:8s} {row[1]:10,d}条  rank:{row[2]:10,d}  范围{row[3]}-{row[4]}  {row[5]}-{row[6]}')

# 缺了哪些省
all_29 = ['河南','河北','山东','贵州','浙江','安徽','广西','山西','江西','广东','湖南','云南','重庆','甘肃','四川','内蒙古','黑龙江','陕西','福建','江苏','湖北','辽宁','吉林','新疆','海南','宁夏','天津','上海','北京']
existing = {r[0] for r in dst.execute('SELECT DISTINCT province FROM admission').fetchall()}
missing = [p for p in all_29 if not any(p in e for e in existing)]
print(f'\n缺失省份: {missing}')

dst.close()
src.close()
print(f'\n清洗完成: {DST}')
