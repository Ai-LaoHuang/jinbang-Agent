#!/usr/bin/env python3
"""金榜Agent — 单文件服务器：HTML UI + API + 数据库查询"""
import os, sys, re, json, sqlite3, gzip, shutil, urllib.request, urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler

if getattr(sys, 'frozen', False):
    HERE = sys._MEIPASS
else:
    HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, 'admission_clean.db')
GZ_PATH = os.path.join(HERE, 'admission_clean.db.gz')
if not os.path.exists(DB_PATH) and os.path.exists(GZ_PATH):
    with gzip.open(GZ_PATH, 'rb') as gz:
        with open(DB_PATH, 'wb') as f:
            shutil.copyfileobj(gz, f)

HAS_DB = os.path.exists(DB_PATH)

# ===== 自动更新 =====
VERSION_FILE = os.path.join(HERE, 'db_version.json')
UPDATE_REPO = 'Ai-LaoHuang/金榜Agent'
UPDATE_BRANCH = 'master'
_encoded_repo = urllib.parse.quote(UPDATE_REPO, safe='/')
UPDATE_VERSION_URL = f'https://raw.githubusercontent.com/{_encoded_repo}/{UPDATE_BRANCH}/db_version.json'
UPDATE_DB_URL = f'https://raw.githubusercontent.com/{_encoded_repo}/{UPDATE_BRANCH}/admission_clean.db.gz'

def _load_local_version():
    if os.path.exists(VERSION_FILE):
        try:
            with open(VERSION_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {'version': '0', 'records': 0, 'updated': ''}

UPDATE_STATE = {
    'checking': False, 'downloading': False, 'progress': 0,
    'message': '', 'updated': False, 'error': '',
    'local_version': _load_local_version().get('version', '0'),
    'remote_version': '', 'remote_records': 0,
}

import threading
def _check_for_updates():
    UPDATE_STATE['checking'] = True
    UPDATE_STATE['message'] = '正在检查更新...'
    try:
        req = urllib.request.Request(UPDATE_VERSION_URL)
        req.add_header('Cache-Control', 'no-cache')
        resp = urllib.request.urlopen(req, timeout=15)
        remote = json.loads(resp.read().decode('utf-8'))
        UPDATE_STATE['remote_version'] = remote.get('version', '0')
        UPDATE_STATE['remote_records'] = remote.get('records', 0)
        local = _load_local_version()
        if remote['version'] != local.get('version', '0'):
            UPDATE_STATE['downloading'] = True
            UPDATE_STATE['message'] = f"发现新数据 {remote['version']}（{remote.get('records','?')}条），正在下载..."
            _download_update()
        else:
            UPDATE_STATE['message'] = '数据库已是最新'
    except Exception as e:
        UPDATE_STATE['error'] = str(e)
        UPDATE_STATE['message'] = '更新检查失败（网络不可达）'
    finally:
        UPDATE_STATE['checking'] = False

def _download_update():
    try:
        tmp_gz = GZ_PATH + '.tmp'
        urllib.request.urlretrieve(UPDATE_DB_URL, tmp_gz, _update_progress)
        # Atomic swap
        if os.path.exists(GZ_PATH):
            os.replace(GZ_PATH, GZ_PATH + '.bak')
        os.replace(tmp_gz, GZ_PATH)
        # Decompress new database
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
        with gzip.open(GZ_PATH, 'rb') as gz:
            with open(DB_PATH, 'wb') as f:
                shutil.copyfileobj(gz, f)
        # Save version
        remote_version = {'version': UPDATE_STATE['remote_version'],
                          'records': UPDATE_STATE['remote_records'],
                          'updated': __import__('datetime').datetime.now().isoformat()}
        with open(VERSION_FILE, 'w', encoding='utf-8') as f:
            json.dump(remote_version, f, ensure_ascii=False)
        # Reload coverage
        global DB_COVERAGE, HAS_DB
        HAS_DB = True
        DB_COVERAGE = load_db_coverage()
        UPDATE_STATE['updated'] = True
        UPDATE_STATE['message'] = f"更新完成！{UPDATE_STATE['remote_records']}条记录已加载"
        # Clean up backup
        if os.path.exists(GZ_PATH + '.bak'):
            os.remove(GZ_PATH + '.bak')
    except Exception as e:
        UPDATE_STATE['error'] = str(e)
        UPDATE_STATE['message'] = f'下载失败: {e}'
        # Restore backup
        if os.path.exists(GZ_PATH + '.bak'):
            os.replace(GZ_PATH + '.bak', GZ_PATH)

def _update_progress(count, block_size, total_size):
    if total_size > 0:
        pct = min(int(count * block_size * 100 / total_size), 100)
        UPDATE_STATE['progress'] = pct

# Start update check in background (delayed 1s to not block startup)
def _start_update_check():
    t = threading.Thread(target=_check_for_updates, daemon=True)
    t.start()

threading.Timer(1.0, _start_update_check).start()

def normalize_province(value):
    value = (value or '').strip().replace(' ', '')
    aliases = {'内蒙古自治区':'内蒙古','广西壮族自治区':'广西','宁夏回族自治区':'宁夏',
               '新疆维吾尔自治区':'新疆','西藏自治区':'西藏','香港特别行政区':'香港',
               '澳门特别行政区':'澳门'}
    if value in aliases:
        return aliases[value]
    return re.sub(r'(省|市|自治区)$', '', value)

def load_db_coverage():
    if not HAS_DB:
        return {}
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""SELECT province, COUNT(*),
        SUM(CASE WHEN score>0 THEN 1 ELSE 0 END),
        SUM(CASE WHEN rank>0 THEN 1 ELSE 0 END)
        FROM admission GROUP BY province""").fetchall()
    conn.close()
    return {r[0]: {'rows':r[1], 'score_rows':r[2] or 0, 'rank_rows':r[3] or 0} for r in rows}

DB_COVERAGE = load_db_coverage()

def estimate_rank_from_score(conn, province, score):
    """Estimate a candidate rank from the latest admission table for score-only input."""
    years = [r[0] for r in conn.execute(
        "SELECT DISTINCT year FROM admission WHERE province=? ORDER BY year DESC", (province,)
    ).fetchall()]
    for year in years:
        for delta in range(0, 6):
            rows = conn.execute(
                "SELECT rank FROM admission WHERE province=? AND year=? AND score BETWEEN ? AND ? AND rank>0 ORDER BY rank",
                (province, year, score-delta, score+delta)
            ).fetchall()
            if rows:
                values = [r[0] for r in rows]
                return values[len(values)//2], year, delta
    return 0, None, None

def dedupe_recommendations(items):
    seen, result = set(), []
    for item in items:
        key = (item.get('school'), item.get('major'))
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result

PROVINCES = ['北京','天津','上海','重庆','河北','山西','辽宁','吉林','黑龙江','江苏','浙江','安徽',
             '福建','江西','山东','河南','湖北','湖南','广东','广西','海南','四川','贵州','云南',
             '西藏','陕西','甘肃','青海','宁夏','新疆','内蒙古']

def query_db(province=None, school=None, major=None, limit=50):
    if not HAS_DB: return None
    conn = sqlite3.connect(DB_PATH)
    conds, params = [], []
    if province: conds.append("province LIKE ?"); params.append(f"%{province}%")
    if school: conds.append("school_name LIKE ?"); params.append(f"%{school}%")
    if major: conds.append("major_name LIKE ?"); params.append(f"%{major}%")
    if not conds: conn.close(); return None
    sql = f"SELECT province,year,school_name,major_name,score,rank FROM admission WHERE {' AND '.join(conds)} AND rank>100 ORDER BY year DESC,rank ASC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [{'province':r[0],'year':r[1],'school_name':r[2],'major_name':r[3],'score':r[4],'rank':r[5]} for r in rows]

def web_search(query, n=5):
    # Baidu scraping no longer works (blocked). Return hint to use Tavily.
    return ["搜索无结果。请在前端API设置中填入Tavily Key以启用联网搜索（tavily.com免费注册）。"]

class Handler(BaseHTTPRequestHandler):
    def _send(self, data, code=200):
        self.send_response(code)
        self.send_header('Content-Type','application/json;charset=utf-8')
        self.send_header('Access-Control-Allow-Origin','*')
        self.send_header('Cache-Control','no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma','no-cache')
        self.send_header('Expires','0')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin','*')
        self.send_header('Access-Control-Allow-Methods','GET,OPTIONS')
        self.send_header('Access-Control-Allow-Headers','*')
        self.end_headers()

    def do_GET(self):
        if self.path == '/ping':
            return self._send({'ok':True,'db':HAS_DB,'updating':UPDATE_STATE.get('downloading',False)})
        if self.path == '/update-status':
            return self._send(dict(UPDATE_STATE))
        if self.path.startswith('/query'):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            rows = query_db(qs.get('province',[''])[0], qs.get('school',[''])[0], qs.get('major',[''])[0])
            return self._send({'db':rows,'count':len(rows) if rows else 0})
        if self.path.startswith('/recommend'):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            prov = normalize_province(qs.get('province',[''])[0])
            major = qs.get('major',[''])[0]
            keyword = qs.get('keyword',[''])[0]
            try: rank = int(qs.get('rank',['0'])[0])
            except: rank = 0
            try: score = int(qs.get('score',['0'])[0])
            except: score = 0
            print(f"[RECOMMEND] prov={prov} rank={rank} score={score} kw={keyword[:30] if keyword else 'none'}")
            if prov and (rank > 0 or score > 0):
                coverage = DB_COVERAGE.get(prov)
                supported = sorted(DB_COVERAGE.keys())
                empty = {'rank':rank,'score':score,'chong':[],'wen':[],'bao':[],
                         'supported_provinces':supported}
                if not coverage:
                    empty.update(status='unsupported_province', message=f'本地数据库暂未覆盖{prov}。当前支持：' + '、'.join(supported))
                    return self._send(empty)
                if rank > 0 and not score and coverage['rank_rows'] == 0:
                    empty.update(status='score_required', message=f'{prov}现有录取数据不含位次字段，请改填高考分数后重试。')
                    return self._send(empty)
                if score > 0 and not rank and coverage['score_rows'] == 0:
                    empty.update(status='rank_required', message=f'{prov}现有录取数据不含分数字段，请改填全省位次后重试。')
                    return self._send(empty)
                conn = sqlite3.connect(DB_PATH)
                data_year = conn.execute(
                    "SELECT MAX(year) FROM admission WHERE province=?", (prov,)
                ).fetchone()[0]
                rank_estimated = False
                rank_estimate_year = None
                if score > 0 and rank == 0 and coverage['rank_rows'] > 0:
                    estimated, estimate_year, _ = estimate_rank_from_score(conn, prov, score)
                    if estimated:
                        rank = estimated
                        rank_estimated = True
                        rank_estimate_year = estimate_year
                base = "province LIKE ? AND year=? AND (score>0 OR rank>0)"
                bp = [f'%{prov}%', data_year]
                if major: base += " AND major_name LIKE ?"; bp.append(f'%{major}%')
                if keyword:
                    kws = [x.strip() for x in re.split(r'[,，、;；/\s]+', keyword) if x.strip()]
                    kw_conds = []
                    for kw in kws:
                        kw_conds.append("(major_name LIKE ? OR school_name LIKE ?)")
                        bp.append(f'%{kw}%'); bp.append(f'%{kw}%')
                    base += " AND (" + " OR ".join(kw_conds) + ")"

                chong = []; wen = []; bao = []

                # Try rank-based first, fall back to score-based
                if rank > 0:
                    chong = [{'school':r[0],'major':r[1],'score':r[2],'rank':r[3],'year':r[4]} for r in
                        conn.execute(f"SELECT school_name,major_name,score,rank,year FROM admission WHERE {base} AND rank>0 AND rank<? AND rank>=? ORDER BY rank ASC LIMIT 50",
                        bp+[rank, max(1,int(rank*0.85))]).fetchall()]
                    wen = [{'school':r[0],'major':r[1],'score':r[2],'rank':r[3],'year':r[4]} for r in
                        conn.execute(f"SELECT school_name,major_name,score,rank,year FROM admission WHERE {base} AND rank>0 AND rank>=? AND rank<=? ORDER BY rank ASC LIMIT 50",
                        bp+[rank, int(rank*1.3)]).fetchall()]
                    bao = [{'school':r[0],'major':r[1],'score':r[2],'rank':r[3],'year':r[4]} for r in
                        conn.execute(f"SELECT school_name,major_name,score,rank,year FROM admission WHERE {base} AND rank>0 AND rank>? AND rank<=? ORDER BY rank ASC LIMIT 50",
                        bp+[int(rank*1.3), int(rank*1.6)]).fetchall()]

                # If rank query returned nothing, try score-based
                if not (chong or wen or bao) and score > 0:
                    # First try with keyword
                    chong = [{'school':r[0],'major':r[1],'score':r[2],'rank':r[3],'year':r[4]} for r in
                        conn.execute(f"SELECT school_name,major_name,score,rank,year FROM admission WHERE {base} AND score>? AND score<=? ORDER BY score ASC LIMIT 50",
                        bp+[score, score+15]).fetchall()]
                    wen = [{'school':r[0],'major':r[1],'score':r[2],'rank':r[3],'year':r[4]} for r in
                        conn.execute(f"SELECT school_name,major_name,score,rank,year FROM admission WHERE {base} AND score>=? AND score<=? ORDER BY score DESC LIMIT 50",
                        bp+[score-10, score]).fetchall()]
                    bao = [{'school':r[0],'major':r[1],'score':r[2],'rank':r[3],'year':r[4]} for r in
                        conn.execute(f"SELECT school_name,major_name,score,rank,year FROM admission WHERE {base} AND score>=? AND score<? ORDER BY score DESC LIMIT 50",
                        bp+[score-30, score-10]).fetchall()]
                    # Without a professional filter, broaden the score window slightly.
                    if not (chong or wen or bao) and not keyword:
                        base2 = "province LIKE ? AND year=? AND score>0"
                        bp2 = [f'%{prov}%', data_year]
                        chong = [{'school':r[0],'major':r[1],'score':r[2],'rank':r[3],'year':r[4]} for r in
                            conn.execute(f"SELECT school_name,major_name,score,rank,year FROM admission WHERE {base2} AND score>? AND score<=? ORDER BY score DESC LIMIT 80",
                            bp2+[score, score+15]).fetchall()]
                        wen = [{'school':r[0],'major':r[1],'score':r[2],'rank':r[3],'year':r[4]} for r in
                            conn.execute(f"SELECT school_name,major_name,score,rank,year FROM admission WHERE {base2} AND score>=? AND score<=? ORDER BY score ASC LIMIT 50",
                            bp2+[score-10, score]).fetchall()]
                        bao = [{'school':r[0],'major':r[1],'score':r[2],'rank':r[3],'year':r[4]} for r in
                            conn.execute(f"SELECT school_name,major_name,score,rank,year FROM admission WHERE {base2} AND score>=? AND score<? ORDER BY score ASC LIMIT 50",
                            bp2+[score-30, score-10]).fetchall()]
                conn.close()
                chong = dedupe_recommendations(chong)
                wen = dedupe_recommendations(wen)
                bao = dedupe_recommendations(bao)
                result = {'rank':rank,'score':score,'rank_estimated':rank_estimated,
                          'rank_estimate_year':rank_estimate_year,'data_year':data_year,
                          'chong':chong,'wen':wen,'bao':bao,
                          'status':'ok','supported_provinces':supported}
                if not (chong or wen or bao):
                    result['status'] = 'no_match'
                    result['message'] = (f'{prov}有数据，但当前分数/位次区间内没有匹配“{keyword}”的专业。'
                                         '请尝试更宽泛的专业词，如“计算机”或“电子信息”。') if keyword else \
                                        f'{prov}有数据，但当前分数或位次附近没有录取记录，请检查输入是否正确。'
                return self._send(result)
            return self._send({'error':'need province and rank or score'},400)
        if self.path.startswith('/search'):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            q = qs.get('q',[''])[0]
            if q: return self._send({'results':web_search(q)})
            return self._send({'results':[]})

        # Serve image files
        for img in ['img_suit.png']:
            if self.path == '/'+img:
                ip = os.path.join(HERE, img)
                if os.path.exists(ip):
                    self.send_response(200)
                    self.send_header('Content-Type','image/png')
                    self.send_header('Cache-Control','max-age=3600')
                    self.end_headers()
                    with open(ip,'rb') as f: self.wfile.write(f.read())
                    return

        # Serve the main UI page
        self.send_response(200)
        self.send_header('Content-Type','text/html;charset=utf-8')
        self.send_header('Cache-Control','no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma','no-cache')
        self.send_header('Expires','0')
        self.end_headers()
        self.wfile.write(HTML_PAGE.encode('utf-8'))

    def log_message(self, format, *args):
        msg = format%args if args else format
        if '/recommend' in msg or '/query' in msg or '/ping' in msg or '/search' in msg:
            print(f"[REQ] {msg}")

# ========== 完整的 HTML 页面（内嵌 JS）==========
HTML_PAGE = r'''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>金榜Agent — 高考志愿工作台</title>
<style>
:root{
  --bg:#0b0b0f; --surface:#131318; --card:#1a1a22; --bdr:#252530; --txt:#e4e4e7; --t2:#717180;
  --accent:#f59e0b; --accent2:#ef4444; --accent3:#22c55e; --blue:#60a5fa;
  --shadow:0 2px 8px rgba(0,0,0,.5);
  --radius:12px; --radius-sm:8px;
  --font:'Inter','PingFang SC','Microsoft YaHei',system-ui,sans-serif;
}
.light{
  --bg:#f8f8fa; --surface:#fff; --card:#fff; --bdr:#e5e5ea; --txt:#1c1c1e; --t2:#8e8e98;
  --shadow:0 2px 8px rgba(0,0,0,.06);
}
*{margin:0;padding:0;box-sizing:border-box}
body{font:14px/1.6 var(--font);background:var(--bg);color:var(--txt);height:100vh;display:flex;flex-direction:column;overflow:hidden}

/* ========== TOP BAR ========== */
.topbar{height:48px;display:flex;align-items:center;padding:0 20px;background:var(--surface);border-bottom:1px solid var(--bdr);gap:12px;flex-shrink:0;z-index:10}
.topbar .brand{font-weight:800;font-size:15px;letter-spacing:-.02em;display:flex;align-items:center;gap:8px}
.topbar .brand .dot{width:7px;height:7px;border-radius:50%;background:var(--accent);box-shadow:0 0 8px var(--accent)}
.topbar .spacer{flex:1}
.btn-seg{display:flex;background:var(--bg);border-radius:8px;padding:2px}
.btn-seg button{padding:6px 14px;border:none;border-radius:6px;cursor:pointer;font-size:12px;font-weight:500;color:var(--t2);background:transparent;transition:all .15s}
.btn-seg button.on{background:var(--accent);color:#1a1a10;font-weight:600}
.btn-ghost{width:34px;height:34px;border:1px solid var(--bdr);border-radius:8px;background:transparent;cursor:pointer;font-size:16px;color:var(--txt);display:flex;align-items:center;justify-content:center;transition:all .15s;padding:0}
.btn-ghost:hover{border-color:var(--accent);background:var(--bg)}
.btn-primary{padding:7px 16px;border:none;border-radius:8px;cursor:pointer;font-size:12px;font-weight:600;color:#1a1a10;background:var(--accent);transition:all .15s}
.btn-primary:hover{filter:brightness(1.15)}

/* ========== HISTORY DRAWER ========== */
.history-overlay{position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:50;display:none}
.history-overlay.show{display:block}
.history-drawer{position:fixed;top:0;left:0;bottom:0;width:320px;background:var(--surface);border-right:1px solid var(--bdr);z-index:51;transform:translateX(-100%);transition:transform .25s cubic-bezier(.4,0,.2,1);display:flex;flex-direction:column;box-shadow:4px 0 24px rgba(0,0,0,.4)}
.history-drawer.open{transform:translateX(0)}
.history-drawer .hd-head{padding:16px 20px;border-bottom:1px solid var(--bdr);display:flex;align-items:center;justify-content:space-between}
.history-drawer .hd-head h3{font-size:13px;font-weight:600;color:var(--t2);text-transform:uppercase;letter-spacing:.04em}
.hd-list{flex:1;overflow-y:auto;padding:8px}
.hd-item{padding:12px 14px;border-radius:var(--radius-sm);cursor:pointer;margin-bottom:3px;transition:all .12s;display:flex;align-items:center;gap:10px}
.hd-item:hover{background:var(--card)}
.hd-item.on{background:var(--accent);color:#1a1a10}
.hd-item .hd-icon{width:34px;height:34px;border-radius:50%;background:var(--bg);display:flex;align-items:center;justify-content:center;font-size:15px;flex-shrink:0}
.hd-item.on .hd-icon{background:rgba(0,0,0,.15)}
.hd-item .hd-info{flex:1;min-width:0}
.hd-item .hd-name{font-size:13px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hd-item .hd-meta{font-size:11px;color:var(--t2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hd-item.on .hd-meta{color:rgba(0,0,0,.45)}
.hd-item .hd-del{opacity:0;transition:opacity .15s;font-size:18px;color:var(--t2);flex-shrink:0;width:26px;text-align:center;line-height:34px}
.hd-item:hover .hd-del{opacity:.5}.hd-item:hover .hd-del:hover{opacity:1;color:#ef4444}
.hd-new{margin:8px 12px 14px;padding:10px;text-align:center;border:1.5px dashed var(--bdr);border-radius:var(--radius-sm);cursor:pointer;font-size:13px;color:var(--t2);transition:all .15s}
.hd-new:hover{background:var(--card);border-color:var(--accent);color:var(--accent)}

/* ========== MAIN CONTENT ========== */
.main-area{flex:1;display:flex;flex-direction:column;overflow:hidden}

/* Query bar */
.query-bar{padding:14px 20px;display:flex;gap:10px;align-items:center;flex-shrink:0;border-bottom:1px solid var(--bdr);background:var(--surface);flex-wrap:wrap}
.query-bar input{padding:9px 14px;border:1.5px solid var(--bdr);border-radius:8px;font:inherit;font-size:13px;background:var(--bg);color:var(--txt);outline:none;width:110px;transition:border-color .15s}
.query-bar input:focus{border-color:var(--accent)}
.query-bar input.wide{width:160px}
.query-bar .qb-label{font-size:11px;color:var(--t2);font-weight:600;text-transform:uppercase;letter-spacing:.03em;margin-right:-4px}
.btn-search{padding:9px 22px;border:none;border-radius:8px;cursor:pointer;font-size:13px;font-weight:700;color:#1a1a10;background:var(--accent);transition:all .15s;white-space:nowrap}
.btn-search:hover{filter:brightness(1.15);box-shadow:0 2px 12px rgba(245,158,11,.3)}
.btn-search:disabled{opacity:.4;cursor:not-allowed}

/* Results area - 3 columns */
.results-area{flex:1;overflow:hidden;display:flex;flex-direction:column;position:relative}
.results-scroll{flex:1;overflow-y:auto;overflow-x:hidden;padding:16px 20px}
.results-scroll::-webkit-scrollbar{width:4px}.results-scroll::-webkit-scrollbar-thumb{background:var(--bdr);border-radius:4px}

.col-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;height:100%}
.col{display:flex;flex-direction:column;min-height:0}
.col-head{padding:10px 14px;border-radius:var(--radius-sm);font-weight:700;font-size:14px;margin-bottom:12px;display:flex;align-items:center;gap:8px}
.col-head.chong{background:rgba(239,68,68,.12);color:#f87171}
.col-head.wen{background:rgba(245,158,11,.12);color:var(--accent)}
.col-head.bao{background:rgba(34,197,94,.12);color:#4ade80}
.col-head .col-badge{font-size:11px;opacity:.7;font-weight:500}
.col-cards{flex:1;overflow-y:auto;padding-right:4px}
.col-cards::-webkit-scrollbar{width:3px}.col-cards::-webkit-scrollbar-thumb{background:var(--bdr);border-radius:3px}

.card{background:var(--card);border:1px solid var(--bdr);border-radius:var(--radius);padding:14px 16px;margin-bottom:10px;transition:all .15s;cursor:default;position:relative}
.card:hover{border-color:var(--accent);box-shadow:var(--shadow);transform:translateY(-2px)}
.card .card-school{font-weight:700;font-size:14px;margin-bottom:4px}
.card .card-major{font-size:12.5px;color:var(--accent);margin-bottom:8px;font-weight:500}
.card .card-stats{display:flex;gap:16px;font-size:11.5px;color:var(--t2)}
.card .card-stats span{display:flex;align-items:center;gap:3px}
.card .card-year{position:absolute;top:10px;right:14px;font-size:10px;color:var(--t2);background:var(--bg);padding:2px 8px;border-radius:10px}

.empty-state{text-align:center;padding:60px 20px;color:var(--t2)}
.empty-state .icon{font-size:48px;margin-bottom:12px;display:block}
.empty-state h3{font-size:16px;font-weight:600;margin-bottom:4px;color:var(--txt)}
.empty-state p{font-size:13px;line-height:1.6;max-width:380px;margin:0 auto}

/* ========== CHAT PANEL (bottom) ========== */
.chat-panel{border-top:1px solid var(--bdr);background:var(--surface);flex-shrink:0;display:flex;flex-direction:column;max-height:40vh;transition:max-height .25s}
.chat-panel.collapsed{max-height:52px}
.chat-panel-head{padding:8px 20px;display:flex;align-items:center;gap:8px;cursor:pointer;flex-shrink:0}
.chat-panel-head:hover{background:var(--card)}
.chat-panel-head .cp-title{font-size:12px;font-weight:600;color:var(--t2);text-transform:uppercase;letter-spacing:.04em}
.chat-panel-head .cp-arrow{font-size:10px;color:var(--t2);transition:transform .2s}
.chat-panel.collapsed .cp-arrow{transform:rotate(-90deg)}
.chat-msgs{flex:1;overflow-y:auto;padding:8px 20px;min-height:0}
.chat-msgs::-webkit-scrollbar{width:3px}.chat-msgs::-webkit-scrollbar-thumb{background:var(--bdr);border-radius:3px}

.cm-row{margin-bottom:8px;animation:fadeUp .25s ease}
@keyframes fadeUp{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:translateY(0)}}
.cm-row.user{text-align:right}
.cm-row .cm-who{font-size:9px;opacity:.4;margin-bottom:2px;font-weight:600;text-transform:uppercase;letter-spacing:.05em}
.cm-bubble{display:inline-block;max-width:75%;padding:8px 14px;border-radius:14px;font-size:12.5px;line-height:1.65;white-space:pre-wrap;word-break:break-word;text-align:left}
.cm-row.user .cm-bubble{background:var(--accent);color:#1a1a10;border-bottom-right-radius:4px}
.cm-row.assistant .cm-bubble{background:var(--card);border:1px solid var(--bdr);border-bottom-left-radius:4px}

.chat-input-row{display:flex;gap:8px;padding:8px 20px 14px;flex-shrink:0}
.chat-input-row input{flex:1;padding:9px 14px;border:1.5px solid var(--bdr);border-radius:20px;font:inherit;font-size:13px;background:var(--bg);color:var(--txt);outline:none;transition:border-color .15s}
.chat-input-row input:focus{border-color:var(--accent)}
.chat-input-row input::placeholder{color:var(--t2)}
.chat-input-row .btn-send-sm{padding:8px 18px;border:none;border-radius:20px;cursor:pointer;font-size:12px;font-weight:600;color:#1a1a10;background:var(--accent);transition:all .15s}
.chat-input-row .btn-send-sm:hover{filter:brightness(1.15)}

/* Typing */
.cm-typing{display:inline-flex;gap:4px;padding:10px 14px}
.cm-typing span{width:6px;height:6px;border-radius:50%;background:var(--t2);animation:td 1.2s infinite}
.cm-typing span:nth-child(2){animation-delay:.2s}.cm-typing span:nth-child(3){animation-delay:.4s}
@keyframes td{0%,60%,100%{transform:scale(.6);opacity:.3}30%{transform:scale(1);opacity:1}}

/* ========== MODAL ========== */
.modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:99;display:none;align-items:center;justify-content:center;backdrop-filter:blur(4px);-webkit-backdrop-filter:blur(4px)}
.modal{background:var(--surface);border-radius:var(--radius);padding:30px;width:460px;border:1px solid var(--bdr);box-shadow:0 12px 40px rgba(0,0,0,.6);animation:modalPop .25s ease}
@keyframes modalPop{from{opacity:0;transform:scale(.93) translateY(16px)}to{opacity:1;transform:scale(1) translateY(0)}}
.modal h3{font-size:17px;font-weight:700;margin-bottom:18px}
.modal label{display:block;font-size:10.5px;color:var(--t2);margin:12px 0 4px;font-weight:600;text-transform:uppercase;letter-spacing:.05em}
.modal label .tag{display:inline-block;background:var(--accent);color:#1a1a10;font-size:9px;padding:2px 7px;border-radius:10px;margin-left:6px;font-weight:700;vertical-align:middle}
.modal input{width:100%;padding:10px 13px;border:1.5px solid var(--bdr);border-radius:8px;font:inherit;font-size:13px;background:var(--bg);color:var(--txt);outline:none;transition:border-color .15s}
.modal input:focus{border-color:var(--accent)}
.modal .info-note{background:rgba(245,158,11,.06);border:1px solid rgba(245,158,11,.15);border-radius:8px;padding:10px 13px;margin:10px 0 12px;font-size:11px;line-height:1.7;color:var(--t2)}
.modal .info-note b{color:var(--txt)}
.modal .info-note a{color:var(--accent);font-weight:600}
.modal .modal-btns{display:flex;gap:10px;margin-top:20px}
.modal .modal-btns button{padding:10px 20px;border:1px solid var(--bdr);border-radius:8px;cursor:pointer;font-size:13px;font-weight:500;background:var(--card);color:var(--txt);transition:all .15s}
.modal .modal-btns button:hover{background:var(--bg)}
.modal .modal-btns .btn-ok{flex:1;background:var(--accent);color:#1a1a10;border-color:var(--accent);font-weight:600}
.modal .modal-btns .btn-ok:hover{filter:brightness(1.15)}
.status-msg{font-size:12px;margin-top:10px;text-align:center;font-weight:500}.status-msg.ok{color:var(--accent3)}.status-msg.err{color:var(--accent2)}

/* Workspace label */
.workspace-label{padding:7px 12px;border:1px solid var(--bdr);border-radius:10px;background:var(--card);color:var(--t2);font-size:11px;font-weight:700;letter-spacing:.04em}

/* Loading */
.loading-overlay{position:absolute;inset:0;background:rgba(0,0,0,.3);z-index:5;display:none;align-items:center;justify-content:center}
.loading-overlay.show{display:flex}
.loader{width:40px;height:40px;border:3px solid var(--bdr);border-top-color:var(--accent);border-radius:50%;animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}

/* ========== 2026 VISUAL REFRESH ========== */
:root{
  --bg:#0b1020;--surface:#11182a;--card:#182238;--bdr:#27344f;--txt:#f4f7fb;--t2:#91a0b9;
  --accent:#5b94f8;--accent2:#ff7272;--accent3:#44d19a;--shadow:0 18px 45px rgba(0,0,0,.28);
  --radius:18px;--radius-sm:12px
}
.light{--bg:#f3f6fb;--surface:#fff;--card:#fff;--bdr:#e2e8f2;--txt:#172033;--t2:#65738b;--accent:#356fe8;--shadow:0 18px 45px rgba(26,43,75,.1)}
body{-webkit-font-smoothing:antialiased;background:radial-gradient(circle at 50% -10%,rgba(59,130,246,.13),transparent 35%),var(--bg)}
.topbar{height:68px;padding:0 28px;background:rgba(17,24,42,.9);backdrop-filter:blur(18px);gap:14px}
.light .topbar{background:rgba(255,255,255,.9)}
.topbar .brand{font-size:17px;gap:11px}
.brand-mark{width:34px;height:34px;border-radius:11px;background:linear-gradient(145deg,#76b1ff,#3166db);display:grid;place-items:center;color:#fff;font-size:14px;box-shadow:0 8px 20px rgba(53,111,232,.3)}
.brand-copy{display:flex;flex-direction:column;line-height:1.1}
.brand-copy small{font-size:9px;color:var(--t2);font-weight:600;letter-spacing:.15em;margin-top:4px;text-transform:uppercase}
.btn-seg{background:var(--bg);border:1px solid var(--bdr);border-radius:12px;padding:3px}
.btn-seg button{padding:7px 15px;border-radius:9px;font-weight:600}
.btn-seg button.on{background:var(--card);color:var(--txt);box-shadow:0 6px 15px rgba(0,0,0,.16)}
.btn-ghost{width:auto;height:36px;padding:0 12px;border-radius:10px;font-size:12px;font-weight:600;gap:6px}
.btn-primary,.btn-search,.chat-input-row .btn-send-sm,.modal .modal-btns .btn-ok{color:#fff;background:linear-gradient(135deg,#679ffb,#356fe8);border-color:transparent}
.btn-primary{padding:9px 17px;border-radius:10px;box-shadow:0 8px 18px rgba(53,111,232,.24)}
.history-drawer{width:340px;box-shadow:var(--shadow)}
.hd-item.on{background:rgba(91,148,248,.14);color:var(--txt);box-shadow:inset 3px 0 0 var(--accent)}
.hd-item.on .hd-meta{color:var(--t2)}
.main-area{background:transparent}
.query-wrap{padding:18px 28px 0;flex-shrink:0}
.query-bar{max-width:1180px;margin:0 auto;padding:15px;display:grid;grid-template-columns:1fr 1fr 1fr 1.55fr auto;gap:10px;align-items:end;border:1px solid var(--bdr);background:var(--surface);border-radius:16px;box-shadow:0 8px 24px rgba(0,0,0,.12)}
.query-field{min-width:0}
.query-bar input,.query-bar input.wide{width:100%;padding:11px 13px;border:1px solid var(--bdr);border-radius:10px;background:var(--bg)}
.query-bar input:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(91,148,248,.12)}
.query-bar .qb-label{display:block;margin:0 0 6px 2px;font-size:10px;font-weight:700;letter-spacing:.06em}
.btn-search{height:43px;padding:0 23px;border-radius:10px;box-shadow:0 8px 18px rgba(53,111,232,.2)}
.btn-search:hover{filter:none;transform:translateY(-1px);box-shadow:0 10px 24px rgba(53,111,232,.3)}
.results-scroll{padding:22px 28px}
.col-grid{grid-template-columns:repeat(3,minmax(0,1fr));gap:18px;max-width:1180px;margin:0 auto}
.result-note{display:none;max-width:1180px;margin:0 auto 12px;padding:10px 14px;border:1px solid rgba(91,148,248,.3);border-radius:11px;background:rgba(91,148,248,.1);color:var(--t2);font-size:11.5px}
.col-head{padding:12px 14px;border-radius:12px}
.card{border-radius:15px;padding:16px;margin-bottom:11px}
.card:hover{border-color:rgba(91,148,248,.7);box-shadow:0 10px 28px rgba(0,0,0,.16)}
.card .card-school{font-size:14px;padding-right:55px}
.card .card-major{color:var(--accent);margin-bottom:11px}
.card .card-stats{padding-top:10px;border-top:1px solid var(--bdr)}
.empty-state{max-width:980px;margin:0 auto;padding:42px 10px}
.hero{text-align:center;margin-bottom:30px}
.hero-kicker{display:inline-flex;padding:6px 11px;border:1px solid var(--bdr);border-radius:999px;background:var(--surface);font-size:10px;font-weight:700;letter-spacing:.08em;color:var(--accent);margin-bottom:16px}
.hero h1{font-size:34px;line-height:1.25;letter-spacing:-.045em;color:var(--txt);margin-bottom:12px}
.hero h1 span{background:linear-gradient(100deg,#7eb6ff,#4d79ec);-webkit-background-clip:text;background-clip:text;color:transparent}
.hero p{font-size:14px;line-height:1.8;max-width:590px;margin:0 auto;color:var(--t2)}
.guide-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;text-align:left}
.guide-card{padding:18px;border:1px solid var(--bdr);border-radius:16px;background:rgba(17,24,42,.72);box-shadow:0 8px 24px rgba(0,0,0,.09)}
.light .guide-card{background:rgba(255,255,255,.82)}
.guide-num{width:28px;height:28px;border-radius:9px;background:rgba(91,148,248,.14);color:var(--accent);display:grid;place-items:center;font-size:11px;font-weight:800;margin-bottom:12px}
.guide-card h3{font-size:13px;color:var(--txt);margin-bottom:5px}
.guide-card p{font-size:11.5px;line-height:1.7;color:var(--t2)}
.trust-row{display:flex;justify-content:center;gap:28px;margin-top:25px;color:var(--t2);font-size:11px}
.chat-panel{margin:0 28px 20px;border:1px solid var(--bdr);border-radius:16px;background:var(--surface);max-height:38vh;box-shadow:0 8px 24px rgba(0,0,0,.1);overflow:hidden}
.chat-panel.collapsed{max-height:48px}
.chat-panel-head{padding:11px 16px;border-bottom:1px solid var(--bdr)}
.cm-bubble{padding:10px 14px;line-height:1.7}
.cm-row.user .cm-bubble{background:linear-gradient(135deg,#679ffb,#356fe8);color:#fff}
.chat-input-row input{border-radius:11px;background:var(--bg)}
.chat-input-row .btn-send-sm{border-radius:11px;font-weight:700}
.modal{border-radius:20px;width:480px;box-shadow:var(--shadow)}
@media(max-width:900px){
  .topbar{padding:0 14px}.brand-copy small,.btn-ghost .label{display:none}
  .query-wrap{padding:12px 14px 0}.query-bar{grid-template-columns:1fr 1fr}.query-field.keyword{grid-column:1/-1}.btn-search{grid-column:1/-1}
  .results-scroll{padding:18px 14px}.col-grid{grid-template-columns:1fr;height:auto}.chat-panel{margin:0 14px 14px}
  .guide-grid{grid-template-columns:1fr}.trust-row{gap:12px;flex-wrap:wrap}.hero h1{font-size:27px}
}
</style></head><body>

<!-- TOP BAR -->
<header class="topbar">
  <span class="brand"><span class="brand-mark">金</span><span class="brand-copy">金榜 Agent<small>Admission Studio · 由 Ai老黄 制作</small></span></span>
  <span class="workspace-label">志愿填报工作台</span>
  <span class="spacer"></span>
  <button class="btn-ghost" id="historyBtn" title="历史记录"><span>◫</span><span class="label">历史记录</span></button>
  <button class="btn-ghost" id="themeBtn" title="切换主题">明暗</button>
  <button class="btn-primary" id="apiBtn">API 设置</button>
</header>

<!-- HISTORY DRAWER -->
<div class="history-overlay" id="historyOverlay"></div>
<nav class="history-drawer" id="historyDrawer">
  <div class="hd-head"><h3>历史记录</h3><button class="btn-ghost" id="closeHistoryBtn" style="width:28px;height:28px;font-size:14px">✕</button></div>
  <div class="hd-list" id="historyList"></div>
  <div class="hd-new" id="newBtn">+ 新建查询</div>
</nav>

<!-- MAIN AREA -->
<div class="main-area" id="mainArea">
  <!-- Query Bar -->
  <div class="query-wrap"><div class="query-bar" id="queryBar">
    <div class="query-field"><label class="qb-label" for="qProvince">考生省份</label><input id="qProvince" placeholder="例如：浙江"></div>
    <div class="query-field"><label class="qb-label" for="qScore">高考分数</label><input id="qScore" placeholder="例如：650" type="number"></div>
    <div class="query-field"><label class="qb-label" for="qRank">全省位次</label><input id="qRank" placeholder="例如：3500" type="number"></div>
    <div class="query-field keyword"><label class="qb-label" for="qKeyword">专业偏好</label><input id="qKeyword" class="wide" placeholder="计算机、软件工程、人工智能"></div>
    <button class="btn-search" id="searchBtn">开始智能分析</button>
  </div></div>

  <!-- Results + Chat -->
  <div class="results-area" id="resultsArea">
    <div class="results-scroll" id="resultsScroll">
      <!-- Welcome / empty state -->
      <div class="empty-state" id="emptyState">
        <div class="hero">
          <div class="hero-kicker">本地录取数据库 · AI 辅助分析</div>
          <h1>把复杂的志愿信息，整理成<br><span>清晰可执行的选择</span></h1>
          <p>填写省份、分数或位次以及专业偏好。系统将结合本地录取数据，快速生成冲、稳、保三档院校建议。</p>
        </div>
        <div class="guide-grid">
          <div class="guide-card"><div class="guide-num">01</div><h3>先看位次，不只看分数</h3><p>位次比裸分更适合跨年度比较，建议优先填写准确的全省排名。</p></div>
          <div class="guide-card"><div class="guide-num">02</div><h3>明确专业方向</h3><p>可以同时输入多个关键词，系统会优先筛选专业匹配的录取记录。</p></div>
          <div class="guide-card"><div class="guide-num">03</div><h3>再向顾问追问</h3><p>生成结果后，可继续询问地域、就业、考研和专业取舍等问题。</p></div>
        </div>
        <div class="trust-row"><span>24.8 万条录取记录</span><span>14 省数据覆盖</span><span>数据与密钥保存在本机</span><span>由 Ai老黄 制作</span></div>
        <div id="debugStatus" style="margin-top:20px;font-size:12px;color:var(--t2);min-height:20px"></div>
      </div>
      <div id="updateBar" style="max-width:1180px;margin:0 auto 12px;padding:8px 16px;border-radius:10px;background:rgba(91,148,248,.08);border:1px solid rgba(91,148,248,.15);font-size:11.5px;color:var(--t2);display:none;align-items:center;gap:8px;justify-content:center">
        <span id="updateIcon"></span><span id="updateMsg"></span><span id="updateProgress"></span>
      </div>
      <!-- Results grid (hidden initially) -->
      <div class="result-note" id="resultNote"></div>
      <div class="col-grid" id="colGrid" style="display:none">
        <div class="col" id="colChong">
          <div class="col-head chong">冲一冲 <span class="col-badge" id="chongCount"></span></div>
          <div class="col-cards" id="chongCards"></div>
        </div>
        <div class="col" id="colWen">
          <div class="col-head wen">稳一稳 <span class="col-badge" id="wenCount"></span></div>
          <div class="col-cards" id="wenCards"></div>
        </div>
        <div class="col" id="colBao">
          <div class="col-head bao">保一保 <span class="col-badge" id="baoCount"></span></div>
          <div class="col-cards" id="baoCards"></div>
        </div>
      </div>
    </div>
    <div class="loading-overlay" id="loadingOverlay"><div class="loader"></div></div>
  </div>

  <!-- Chat Panel -->
  <div class="chat-panel collapsed" id="chatPanel">
    <div class="chat-panel-head" id="chatPanelHead">
      <span class="cp-title">继续向顾问追问</span>
      <span class="cp-arrow">▼</span>
    </div>
    <div class="chat-msgs" id="chatMsgs"></div>
    <div class="chat-input-row">
      <input id="chatInput" placeholder="对推荐结果有疑问？在这里追问...">
      <button class="btn-send-sm" id="chatSendBtn">发送</button>
    </div>
  </div>
</div>

<!-- MODAL -->
<div class="modal-overlay" id="apiModal"><div class="modal"><h3>API 设置</h3>
<label>Base URL</label><input id="sUrl" placeholder="https://api.deepseek.com">
<label>API Key</label><input type="password" id="sKey" placeholder="sk-...">
<label>Model</label><input id="sModel" placeholder="deepseek-chat">
<label>Tavily Key <span class="tag">强烈推荐</span></label><input type="password" id="sTav" placeholder="tvly-..."><div class="info-note"><b>联网搜索增强</b> — 填了之后自动搜索最新分数线、学校环境、王牌专业、就业薪资。免费额度每月1000次。<br>去 <a href="https://tavily.com" target="_blank">tavily.com</a> 注册，复制 tvly- 开头的 Key 即可。</div>
<div class="modal-btns"><button id="closeApiBtn">取消</button><button class="btn-ok" id="testApiBtn">保存并测试</button></div><div class="status-msg" id="apiStatus"></div></div></div>

<script>
// ==================== DATA MODEL ====================
var sessions, curId;
try{sessions=JSON.parse(localStorage.getItem('xf_data')||'{}');}catch(e){sessions={};localStorage.removeItem('xf_data');}
curId=localStorage.getItem('xf_cur')||'';
try{localStorage.removeItem('xf_mode');}catch(e){}

// ==================== PROMPTS ====================
var PG="现在是2026年6月，2026年高考已经结束，你正在帮助2027届考生进行志愿填报规划。你是资深高考志愿规划师，风格直爽接地气，点评犀利一针见血。\n\n【核心规则】\n1. 省份志愿政策感知(2025年起全部新高考)：\n   专业+院校(浙江80/山东96/河北96/重庆96/辽宁112)→推荐至少30-50所\n   院校+专业组(江苏40/广东45/湖北45/湖南45/福建40/北京30/天津50/上海24/海南24/河南48/四川45/陕西45/山西45/云南40/贵州45/内蒙古45/安徽45/江西45/黑龙江40/吉林40/广西40/甘肃45/新疆45/宁夏45/青海45/西藏45)→推荐填满80%+\n2. 冲稳保比例：冲20%稳50%保30%，保底至少3个\n3. 用户提供的数据（省份、分数、位次、选科、家庭背景等）默认准确，不质疑、不反问（你确定吗）。即使和数据库对不上，也按用户说的来，数据库只做参考。\n4. 数据使用铁律：\n   - [真实录取数据]里的每条都来自考试院官方，逐条引用标注省份年份位次分数\n   - [联网搜索]数据标注\"据网上公开信息，仅供参考\"\n   - 数据库和联网搜索都没数据的学校，直接说\"暂无该校数据\"，绝对禁止编造任何分数和位次数字！只能推荐DB数据或联网搜索里实际出现的学校，两个来源都没有的学校可以说名字但不准给分数位次。\n   - 【死命令】如果DB返回空+联网也没搜到具体位次，你只能说\"建议查省考试院官网\"，不准说'据网上公开信息约XXX分'来模糊编造。没有就是没有。\n4. 专业过滤铁律（极其重要！）：\n   - 用户说了想学什么专业，就只推荐这些专业或相关方向\n   - 用户明确排斥的专业（如生化环材/土木/护理等）一律过滤掉，提都不要提\n   - DB数据里混了不相关的专业（如用户要计算机结果DB返回了中医学），你必须手动筛掉\n   - 优先推荐专业对口的学校，即使它的位次稍远，也比专业不对口的学校强\n5. 普通家庭优先技术类(计算机/软件/电子/电气/自动化/机械)。无公检法资源慎选法学\n6. 生化环材土木护理等天坑专业主动提醒用户避开\n\n【回答结构】\n第1步:确认省份政策→\"你是XX省考生，XX模式，可填N个志愿...\"\n第2步:冲的学校——只推荐专业对口的，逐一列出DB数据或联网数据，没数据的跳过\n第3步:稳的学校——同上，优先专业对口的\n第4步:保的学校——同上\n第5步:补充建议\n\n重要:不要只给3-5所学校。DB数据的学校优先推荐。没有真实数据的学校不要瞎编分数位次。\n\n【追问规则】回答末尾必须检查这些信息是否清楚（不全就问，全就不问）：\n1.省份+文理科 2.分数+位次 3.选科 4.想学什么+排斥什么 5.家里在哪/想去哪 6.父母做什么+年收入 7.家里有没有公检法/电网/医疗/教育系统的资源 8.考研还是直接就业 9.要不要冲985211还是行业强校就行 10.接不接受调剂 11.学费接受范围（普通家庭中外合作慎推）。从缺失的信息里挑1-2个最关键的，用自然的口吻追问，给出提问模板。";

// ==================== HELPERS ====================
function $(id){return document.getElementById(id);}
function el(tag,cls,html){var e=document.createElement(tag);if(cls)e.className=cls;if(html)e.innerHTML=html;return e;}
function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function save(){try{localStorage.setItem('xf_data',JSON.stringify(sessions));localStorage.setItem('xf_cur',curId||'');}catch(e){}}
function getCfg(){return{url:localStorage.getItem('cf_url')||'https://api.deepseek.com',key:localStorage.getItem('cf_key')||'',model:localStorage.getItem('cf_model')||'deepseek-chat',tavily:localStorage.getItem('cf_tav')||''};}
function welcomeHTML(){return '<div class="hero"><div class="hero-kicker">本地录取数据库 · AI 辅助分析</div><h1>把复杂的志愿信息，整理成<br><span>清晰可执行的选择</span></h1><p>填写省份、分数或位次以及专业偏好。系统将结合本地录取数据，快速生成冲、稳、保三档院校建议。</p></div><div class="guide-grid"><div class="guide-card"><div class="guide-num">01</div><h3>先看位次，不只看分数</h3><p>位次比裸分更适合跨年度比较，建议优先填写准确的全省排名。</p></div><div class="guide-card"><div class="guide-num">02</div><h3>明确专业方向</h3><p>可以同时输入多个关键词，系统会优先筛选专业匹配的录取记录。</p></div><div class="guide-card"><div class="guide-num">03</div><h3>再向顾问追问</h3><p>生成结果后，可继续询问地域、就业、考研和专业取舍等问题。</p></div></div><div class="trust-row"><span>24.8 万条录取记录</span><span>14 省数据覆盖</span><span>数据与密钥保存在本机</span><span>由 Ai老黄 制作</span></div>';}

// ==================== SESSION MGMT ====================
function syncQueryForm(q){q=q||{};var p=$('qProvince'),s=$('qScore'),r=$('qRank'),k=$('qKeyword');if(p)p.value=q.province||'';if(s)s.value=q.score||'';if(r)r.value=q.rank||'';if(k)k.value=q.keyword||'';}
function newSession(){var id='s'+Date.now();sessions[id]={name:'新查询',mode:'gaokao',query:{},results:null,msgs:[]};curId=id;save();syncQueryForm({});renderAll();}
function delSession(id){delete sessions[id];if(curId===id){var ks=Object.keys(sessions);curId=ks.length?ks[ks.length-1]:null;if(!curId)newSession();}save();renderAll();}
function loadSession(id){curId=id;var s=sessions[id];syncQueryForm(s&&s.query);renderAll();save();}

// ==================== HISTORY DRAWER ====================
function toggleHistory(){var d=$('historyDrawer'),o=$('historyOverlay');var open=!d.classList.contains('open');d.classList.toggle('open',open);if(o)o.classList.toggle('show',open);}
function closeHistory(){$('historyDrawer').classList.remove('open');$('historyOverlay').classList.remove('show');}

// ==================== RENDER ALL ====================
function renderAll(){
  renderHistory();
  renderResults();
  renderChat();
}

function renderHistory(){
  var h='';
  Object.keys(sessions).forEach(function(id){
    var s=sessions[id];if(!s)return;
    var meta=s.query.province||'';if(s.query.rank)meta+=' 位次'+s.query.rank;else if(s.query.score)meta+=' '+s.query.score+'分';if(!meta)meta='空';
    var on=id===curId?' on':'';
    h+='<div class="hd-item'+on+'" data-sid="'+id+'"><div class="hd-icon">📋</div><div class="hd-info"><div class="hd-name">'+(s.name||'新查询')+'</div><div class="hd-meta">'+esc(meta)+'</div></div><span class="hd-del" data-del="'+id+'">×</span></div>';
  });
  var el=$('historyList');if(el)el.innerHTML=h;
}

function renderResults(){
  var es=$('emptyState'),cg=$('colGrid'),note=$('resultNote');
  if(!curId||!sessions[curId]||!sessions[curId].results){
    _debug('renderResults: no session/results');
    if(es){es.style.display='';es.innerHTML=welcomeHTML();}if(cg)cg.style.display='none';if(note)note.style.display='none';
    return;
  }
  var r=sessions[curId].results;
  if(!r||(!Array.isArray(r.chong)&&!Array.isArray(r.wen)&&!Array.isArray(r.bao))){
    _debug('renderResults: invalid results object');
    if(es){es.style.display='';es.innerHTML='<span class="icon">!</span><h3>无法生成推荐</h3><p>' + esc((r&&r.message)||'服务器返回的数据格式不正确，请重试。') + '</p>';}
    if(cg)cg.style.display='none';
    if(note)note.style.display='none';
    return;
  }
  var cl=(Array.isArray(r.chong)?r.chong.length:0);
  var wl=(Array.isArray(r.wen)?r.wen.length:0);
  var bl=(Array.isArray(r.bao)?r.bao.length:0);
  if(!cl&&!wl&&!bl){
    _debug('renderResults: all arrays empty');
    if(es){es.style.display='';es.innerHTML='<span class="icon">!</span><h3>'+(r.status==='no_match'?'暂未匹配到专业':'需要调整查询条件')+'</h3><p>'+esc(r.message||'该条件下数据库没有匹配的录取数据，请检查省份、分数或位次。')+'</p>';}
    if(cg)cg.style.display='none';
    if(note)note.style.display='none';
    return;
  }
  _debug('renderResults: 冲'+cl+' 稳'+wl+' 保'+bl);
  if(es)es.style.display='none';
  if(cg)cg.style.display='';
  if(note){if(r.rank_estimated){note.style.display='block';note.textContent='已根据 '+r.rank_estimate_year+' 年同分段数据估算位次 '+r.rank+'，并按位次分档；请以官方一分一段表为准。';}else{note.style.display='none';}}

  function cardHTML(d){
    return '<div class="card"><div class="card-school">'+esc(d.school||'')+'</div><div class="card-major">'+esc(d.major||'')+'</div><div class="card-stats"><span>录取分 '+(d.score||'?')+'</span><span>位次 '+(d.rank||'?')+'</span></div><div class="card-year">'+(d.year||'')+'年</div></div>';
  }

  var chong=r.chong||[],wen=r.wen||[],bao=r.bao||[];
  var cc=$('chongCards'),wc=$('wenCards'),bc=$('baoCards');
  var c1=$('chongCount'),c2=$('wenCount'),c3=$('baoCount');
  _debug('DOM: cc='+!!cc+' wc='+!!wc+' bc='+!!bc+' c1='+!!c1);

  if(cc)cc.innerHTML=chong.length?chong.slice(0,15).map(cardHTML).join(''):'<div style="padding:30px;text-align:center;color:var(--t2);font-size:12px">暂无</div>';
  if(wc)wc.innerHTML=wen.length?wen.slice(0,15).map(cardHTML).join(''):'<div style="padding:30px;text-align:center;color:var(--t2);font-size:12px">暂无</div>';
  if(bc)bc.innerHTML=bao.length?bao.slice(0,15).map(cardHTML).join(''):'<div style="padding:30px;text-align:center;color:var(--t2);font-size:12px">暂无</div>';
  if(c1)c1.textContent=chong.length+'所';
  if(c2)c2.textContent=wen.length+'所';
  if(c3)c3.textContent=bao.length+'所';
}

function renderChat(){
  var el=$('chatMsgs');if(!el)return;
  if(!curId||!sessions[curId]||!sessions[curId].msgs||!sessions[curId].msgs.length){el.innerHTML='';return;}
  var h='';var ms=sessions[curId].msgs;
  for(var i=0;i<ms.length;i++){
    var x=ms[i];if(!x)continue;
    var who=x.role==='user'?'你':'顾问';
    var cls=x.role==='user'?'user':'assistant';
    h+='<div class="cm-row '+cls+'"><div class="cm-who">'+who+'</div><div class="cm-bubble">'+esc(x.content||'')+'</div></div>';
  }
  el.innerHTML=h;el.scrollTop=el.scrollHeight;
}

// ==================== SEARCH / QUERY ====================
function _debug(msg){var el=$('debugStatus');if(el)el.textContent=msg;console.log('[XF]',msg);}
async function doSearch(){
  _debug('开始查询...');
  var prov=$('qProvince').value.trim(),score=parseInt($('qScore').value)||0,rank=parseInt($('qRank').value)||0,keyword=$('qKeyword').value.trim();
  if(!prov||(!rank&&!score)){_debug('缺少参数: province='+prov+' rank='+rank+' score='+score);return;}

  if(!curId||!sessions[curId]){_debug('创建新会话');newSession();}
  var s=sessions[curId];
  s.name=prov+(rank?'位次'+rank:score+'分')+(keyword?keyword.slice(0,8):'');
  s.query={province:prov,score:score,rank:rank,keyword:keyword};
  s.results=null;s.msgs=[];save();renderAll();

  var lb=$('loadingOverlay');if(lb)lb.classList.add('show');
  var btn=$('searchBtn');if(btn){btn.disabled=true;btn.textContent='查询中...';}

  try{
    _debug('调用API: recommend?province='+prov+'&rank='+rank+'&score='+score+'&keyword='+keyword);
    var j=await fetchRecommend(prov,score,rank,keyword);
    _debug('API返回: '+(j?JSON.stringify({chong:j.chong?j.chong.length:0,wen:j.wen?j.wen.length:0,bao:j.bao?j.bao.length:0}):'null'));
    var hasChong=j&&j.chong&&j.chong.length>0;
    var hasWen=j&&j.wen&&j.wen.length>0;
    var hasBao=j&&j.bao&&j.bao.length>0;
    if(hasChong||hasWen||hasBao){
      s.results=j;
      _debug('成功! 冲'+j.chong.length+' 稳'+j.wen.length+' 保'+j.bao.length);
      if(j.rank&&!rank){$('qRank').value=j.rank;s.query.rank=j.rank;}
      if(j.score&&!score){$('qScore').value=j.score;s.query.score=j.score;}
    }else{
      _debug('API返回了但数据为空');
      s.results=j||{chong:[],wen:[],bao:[],status:'error',message:'查询服务没有返回有效结果，请稍后重试。'};
    }
    save();renderAll();
    if(hasChong||hasWen||hasBao)doWebSummary(prov,score,rank,keyword);
  }catch(e){
    _debug('查询出错: '+e.message);
    s.results={chong:[],wen:[],bao:[],status:'error',message:'查询发生错误：'+e.message};
    save();renderAll();
  }
  if(lb)lb.classList.remove('show');
  if(btn){btn.disabled=false;btn.textContent='开始智能分析';}
}

async function fetchRecommend(prov,score,rank,keyword){
  var qp=['province='+encodeURIComponent(prov),'rank='+rank,'score='+score];
  if(keyword)qp.push('keyword='+encodeURIComponent(keyword));
  var url='recommend?'+qp.join('&');
  _debug('fetch: '+url);
  var resp=await fetch(url);
  _debug('HTTP status: '+resp.status);
  if(!resp.ok){_debug('HTTP error: '+resp.status);return null;}
  var j=await resp.json();
  _debug('JSON keys: '+Object.keys(j).join(','));
  if(j.error){_debug('Server error: '+j.error);return null;}
  if(!j.chong&&!j.wen&&!j.bao){_debug('No result arrays in response');return null;}
  return {
    rank:j.rank,score:j.score,status:j.status||'ok',message:j.message||'',supported_provinces:j.supported_provinces||[],
    rank_estimated:!!j.rank_estimated,rank_estimate_year:j.rank_estimate_year||null,data_year:j.data_year||null,
    chong:Array.isArray(j.chong)?j.chong.map(function(d){return{school:d.school,major:d.major,score:d.score,rank:d.rank,year:d.year};}):[],
    wen:Array.isArray(j.wen)?j.wen.map(function(d){return{school:d.school,major:d.major,score:d.score,rank:d.rank,year:d.year};}):[],
    bao:Array.isArray(j.bao)?j.bao.map(function(d){return{school:d.school,major:d.major,score:d.score,rank:d.rank,year:d.year};}):[]
  };
}

async function doWebSummary(prov,score,rank,keyword){
  var s=sessions[curId];if(!s)return;
  var cfg=getCfg();
  var queries=[];
  if(keyword)queries.push(prov+' 2025 '+keyword+'专业 录取分数 位次');
  queries.push(prov+' '+rank+'位次 2025 能报哪些大学');
  if(keyword)queries.push(keyword+'专业 2026 就业前景 薪资');

  var allResults=[];
  for(var i=0;i<queries.length;i++){
    var r=await searchWeb(queries[i],cfg,2);
    allResults=allResults.concat(r);
  }
  if(allResults.length){
    var summary='【联网搜索结果】\n';
    var seen={};
    for(var i=0;i<allResults.length;i++){
      var k=allResults[i].slice(0,60);
      if(!seen[k]){seen[k]=1;summary+='· '+allResults[i].slice(0,250)+'\n';}
    }
    s.msgs.push({role:'assistant',content:summary.slice(0,1500)});
    save();renderChat();
  }
}

async function searchWeb(query,cfg,n){
  n=n||3;var results=[];
  if(cfg.tavily){
    try{var ctrl=new AbortController();var to=setTimeout(function(){ctrl.abort();},12000);
    var r=await fetch('https://api.tavily.com/search',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+cfg.tavily},body:JSON.stringify({query:query,search_depth:'basic',include_answer:true,max_results:n}),signal:ctrl.signal});
    clearTimeout(to);
    if(r.ok){var d=await r.json();if(d.answer)results.push('[Tavily] '+d.answer);if(d.results)d.results.forEach(function(x){results.push(x.title+': '+x.content.slice(0,300));});}
    }catch(e){console.warn('Tavily:',e.message);}
  }
  if(!results.length){
    try{var r2=await fetch('/search?q='+encodeURIComponent(query));if(r2.ok){var d2=await r2.json();if(d2.results)d2.results.forEach(function(x){results.push(x);});}}catch(e){}
  }
  return results;
}

// ==================== CHAT ====================
async function sendChat(){
  var inp=$('chatInput');if(!inp)return;var t=inp.value.trim();if(!t)return;inp.value='';
  var cp=$('chatPanel');if(cp)cp.classList.remove('collapsed');
  if(!curId||!sessions[curId])newSession();var s=sessions[curId];
  s.msgs.push({role:'user',content:t});save();renderChat();

  // Typing indicator
  var cm=$('chatMsgs');var ty=el('div','cm-row assistant','<div class="cm-who">顾问</div><div class="cm-bubble"><div class="cm-typing"><span></span><span></span><span></span></div></div>');
  if(cm){cm.appendChild(ty);cm.scrollTop=cm.scrollHeight;}

  var cfg=getCfg();
  if(!cfg.key){s.msgs.push({role:'assistant',content:'请先点击右上角「API设置」填写 DeepSeek Key'});save();renderChat();return;}

  var prompt=PG;
  var ms=[{role:'system',content:prompt}];
  // Include results context
  if(s.results&&(s.results.chong||s.results.wen||s.results.bao)){
    var ctx='【当前查询结果摘要】省份:'+(s.query.province||'')+' 位次:'+(s.query.rank||'')+' 分数:'+(s.query.score||'')+'\n';
    if(s.results.chong&&s.results.chong.length)ctx+='冲('+s.results.chong.length+'所): '+s.results.chong.slice(0,5).map(function(d){return d.school+d.major;}).join(', ')+'\n';
    if(s.results.wen&&s.results.wen.length)ctx+='稳('+s.results.wen.length+'所): '+s.results.wen.slice(0,5).map(function(d){return d.school+d.major;}).join(', ')+'\n';
    if(s.results.bao&&s.results.bao.length)ctx+='保('+s.results.bao.length+'所): '+s.results.bao.slice(0,5).map(function(d){return d.school+d.major;}).join(', ')+'\n';
    ms.push({role:'system',content:ctx});
  }
  for(var i=Math.max(0,s.msgs.length-20);i<s.msgs.length;i++)ms.push({role:s.msgs[i].role,content:s.msgs[i].content});

  try{
    var r=await fetch(cfg.url.replace(/\/+$/,'')+'/v1/chat/completions',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+cfg.key},body:JSON.stringify({model:cfg.model||'deepseek-chat',messages:ms,temperature:0.7})});
    if(!r.ok){var e=await r.json().catch(function(){return{};});throw new Error(e.error&&e.error.message||'HTTP '+r.status);}
    var d=await r.json();s.msgs.push({role:'assistant',content:d.choices[0].message.content});
  }catch(e){s.msgs.push({role:'assistant',content:'出错：'+e.message});}
  save();renderChat();
}

// ==================== EXTRACT INFO (for auto-fill) ====================
function extractInfo(t){
  var info={province:'',rank:0,score:0,major:'',school:''};
  var provs=['北京','天津','上海','重庆','河北','山西','辽宁','吉林','黑龙江','江苏','浙江','安徽','福建','江西','山东','河南','湖北','湖南','广东','广西','海南','四川','贵州','云南','西藏','陕西','甘肃','青海','宁夏','新疆','内蒙古'];
  var bestIdx=t.length,bestProv='';
  for(var i=0;i<provs.length;i++){var idx=t.indexOf(provs[i]);if(idx>=0&&idx<bestIdx){bestIdx=idx;bestProv=provs[i];}}
  info.province=bestProv;
  var rm=t.match(/(\d{4,7})\s*[位名]/)||t.match(/[位名]次?\s*(\d{4,7})/)||t.match(/排[名行]\s*(\d{4,7})/);
  if(rm)info.rank=parseInt(rm[1])||parseInt(rm[2])||0;
  var sm=t.match(/(\d{3})\s*分/);if(sm)info.score=parseInt(sm[1]);
  var majors=['计算机','软件','电气','机械','自动化','土木','临床','口腔','法学','会计','金融','物联网','人工智能','大数据','电子','通信','材料','化工','生物','医学','护理','师范','英语','日语','新闻','设计','美术','音乐','体育','汉语言','思政','马克思','数学','化学','地理','航空航天','能源','交通','环境'];
  var neg=t.match(/(?:不学|不接受|不读|不选|别推荐|别学|拒绝|排斥|不想学|不考虑).*?(?:[。，,;\n]|$)/g)||[];
  var desc=t.match(/(?:英语|数学|语文|物理|化学|生物|历史|地理|政治).*?(?:一般|不好|不行|差|弱|烂|还行|凑合|勉强)/g)||[];
  var desc2=t.match(/(?:英语|数学|语文|物理|化学|生物|历史|地理|政治).*?(?:好|不错|擅长|强|可以|能行)/g)||[];
  var negStr=neg.join('')+desc.join('')+desc2.join('');
  var found=[];
  for(var i=0;i<majors.length;i++){if(t.indexOf(majors[i])>=0&&negStr.indexOf(majors[i])<0){found.push(majors[i]);}}
  if(found.length>0)info.major=found.join(',');
  var sch=t.match(/[一-鿿]{2,8}(大学|学院)/);if(sch)info.school=sch[0];
  return info;
}

// Attempt to auto-fill query bar from chat input
function autoFillFromChat(t){
  var info=extractInfo(t);
  if(info.province&&!$('qProvince').value){$('qProvince').value=info.province;}
  if(info.rank&&!$('qRank').value){$('qRank').value=info.rank;}
  else if(info.score&&!$('qScore').value){$('qScore').value=info.score;}
  if(info.major&&!$('qKeyword').value){$('qKeyword').value=info.major;}
}

// ==================== API MODAL ====================
function openApiModal(){$('apiModal').style.display='flex';var c=getCfg();$('sUrl').value=c.url;$('sKey').value=c.key;$('sModel').value=c.model;$('sTav').value=c.tavily;}
function closeApiModal(){$('apiModal').style.display='none';}
async function testApi(){
  var u=$('sUrl').value.trim(),k=$('sKey').value.trim(),m=$('sModel').value.trim(),tv=$('sTav').value.trim(),st=$('apiStatus');
  if(!u||!k){st.className='status-msg err';st.textContent='请填写 URL 和 Key';return;}
  localStorage.setItem('cf_url',u);localStorage.setItem('cf_key',k);localStorage.setItem('cf_model',m);
  if(tv)localStorage.setItem('cf_tav',tv);
  st.className='status-msg';st.textContent='测试中...';
  try{
    var r=await fetch(u.replace(/\/+$/,'')+'/v1/chat/completions',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+k},body:JSON.stringify({model:m||'deepseek-chat',messages:[{role:'user',content:'hi'}],max_tokens:5})});
    if(r.ok){st.className='status-msg ok';st.textContent='连接成功！';setTimeout(closeApiModal,800);}
    else{var e=await r.json().catch(function(){return{};});st.className='status-msg err';st.textContent=e.error&&e.error.message||'连接失败';}
  }catch(e){st.className='status-msg err';st.textContent=e.message;}
}

// ==================== EVENT BINDINGS ====================
function bind(id,ev,fn){var el=$(id);if(el)el['on'+ev]=fn;}

bind('historyBtn','click',toggleHistory);
bind('closeHistoryBtn','click',closeHistory);
bind('historyOverlay','click',closeHistory);
bind('newBtn','click',function(){newSession();closeHistory();});
bind('searchBtn','click',doSearch);
bind('chatSendBtn','click',sendChat);
bind('chatInput','keydown',function(e){if(e.key==='Enter'){e.preventDefault();sendChat();}});
bind('chatPanelHead','click',function(){$('chatPanel').classList.toggle('collapsed');});
bind('apiBtn','click',openApiModal);
bind('closeApiBtn','click',closeApiModal);
bind('testApiBtn','click',testApi);
bind('apiModal','click',function(e){if(e.target===this)closeApiModal();});
bind('themeBtn','click',function(){document.body.classList.toggle('light');localStorage.setItem('xf_light',document.body.classList.contains('light')?'1':'');});
bind('historyList','click',function(e){var el=e.target;if(el.dataset.del){e.stopPropagation();delSession(el.dataset.del);return;}var item=el.closest('.hd-item');if(item){loadSession(item.dataset.sid);closeHistory();}});

// Query bar: Enter key triggers search
['qProvince','qScore','qRank','qKeyword'].forEach(function(id){bind(id,'keydown',function(e){if(e.key==='Enter')doSearch();});});

// ==================== INIT ====================
try{
  if(localStorage.getItem('xf_light')==='1')document.body.classList.add('light');
  Object.keys(sessions).forEach(function(id){if(sessions[id])sessions[id].mode='gaokao';});
  if(!curId||!sessions[curId]){var nid='s'+Date.now();sessions[nid]={name:'新查询',mode:'gaokao',query:{},results:null,msgs:[]};curId=nid;}
  save();renderAll();
  // Load query params into query bar if they exist
  var s=sessions[curId];
  if(s&&s.query){
    if(s.query.province)$('qProvince').value=s.query.province;
    if(s.query.score)$('qScore').value=s.query.score;
    if(s.query.rank)$('qRank').value=s.query.rank;
    if(s.query.keyword)$('qKeyword').value=s.query.keyword;
  }
  // Auto-update polling
  pollUpdate();
}catch(e){console.warn('init error:',e.message);}

// ==================== AUTO UPDATE ====================
async function pollUpdate(){
  var bar=$('updateBar'),icon=$('updateIcon'),msg=$('updateMsg'),prog=$('updateProgress');
  try{
    var r=await fetch('/update-status');
    var d=await r.json();
    if(d.checking||d.downloading||d.updated||d.error){
      if(bar)bar.style.display='flex';
      if(d.downloading){
        if(icon)icon.textContent='⬇';
        if(msg)msg.textContent=d.message;
        if(prog)prog.textContent=d.progress+'%';
        setTimeout(pollUpdate,1500);
      }else if(d.checking){
        if(icon)icon.textContent='⏳';
        if(msg)msg.textContent=d.message;
        setTimeout(pollUpdate,2000);
      }else if(d.updated){
        if(icon)icon.textContent='✅';
        if(msg)msg.textContent=d.message;
        if(prog)prog.textContent='';
        setTimeout(function(){if(bar)bar.style.display='none';},5000);
      }else if(d.error){
        if(icon)icon.textContent='⚠';
        if(msg)msg.textContent=d.message;
        if(prog)prog.textContent='';
      }
    }
  }catch(e){}
}
</script></body></html>
'''

def main():
    port = 8765
    server = HTTPServer(('0.0.0.0', port), Handler)
    print(f'金榜Agent: http://127.0.0.1:{port}/')
    print(f'数据库: {"已加载" if HAS_DB else "未找到"}')
    try: server.serve_forever()
    except KeyboardInterrupt: server.shutdown(); print('\n已停止')

if __name__ == '__main__': main()
