#!/usr/bin/env python3
"""SkillScope V4: source-grounded GitHub Skills discovery, using only Python stdlib.

Use as: GITHUB_TOKEN=... python scripts/collect.py
         python scripts/collect.py --demo   # fully offline diagnostic run

Candidate discovery does NOT imply installation, security audit or compatibility.
"""
import argparse
import base64
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "catalog.json"
NOW = lambda: dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

SOURCES = [
    {"owner":"anthropics", "repo":"skills", "type":"Skill", "provider":"Anthropic 官方"},
    {"owner":"openai", "repo":"plugins", "type":"插件", "provider":"OpenAI 官方"},
    {"owner":"vercel-labs", "repo":"agent-skills", "type":"Skill", "provider":"Vercel 官方"},
    {"owner":"microsoft", "repo":"skills", "type":"Skill", "provider":"Microsoft 官方"},
    {"owner":"vercel-labs", "repo":"skills", "type":"Skill", "provider":"Vercel 社区"},
]

# Match keywords to the seven user-selected sectors. Designed for fast initial triage only.
TOPICS = [
    ("经营与财务分析", "数据分析", r"financial|finance|account|budget|forecast|profit|revenue|cost|kpi|metric|model.audit|valuation|spreadsheet.analysis|data.quality|dashboard|analytics|business.analysis|commercial"),
    ("PPT / Word / Excel", "办公文档", r"pptx|powerpoint|slide|presentation|docx|word|excel|xlsx|spreadsheet|document|pdf|report|office|memo|deck|formatting"),
    ("行业研究与商业情报", "行业研究", r"research|market|competitive|intelligence|investigat|industry|search|web.research|trends|news|company|due.diligence|benchmark"),
    ("浏览器与工作流自动化", "浏览器自动化", r"browser|playwright|automation|automate|workflow|scrap|crawler|selenium|integration|gmail|calendar|notion|n8n|zapier|webhook"),
    ("编程、网站与 AI Agent", "软件开发", r"code|coding|develop|agent|mcp|frontend|backend|react|nextjs|website|deploy|testing|debug|github|typescript|python|api|design.system"),
    ("视频与视觉设计", "视觉设计", r"video|image|design|graphic|creative|visual|illustrat|render|animation|figma|brand|photo|cinematic|storyboard"),
    ("有趣的创新型 Skills", "AI生产力", r"idea|brainstorm|creativ|skill.creator|find.skills|innov|prototype|experiment|prompt|simulation|generat"),
]
EXCLUDE = re.compile(r"(^|/)(node_modules|vendor|test|tests|fixtures|examples|__pycache__|\.git|\.venv|dist|build)(/|$)", re.I)
WEAK = re.compile(r"(^|[-_/])(java|swift|ruby|kotlin|rust|go|php|android|ios|terraform|sqlserver|azure.sdk|aws.sdk)([-_/]|$)", re.I)
MAX_TOTAL = 420
NEW_PER_RUN = 35
BLOB_READS_PER_RUN = 35
TIMEOUT = 18


def api(endpoint: str):
    url = 'https://api.github.com' + endpoint
    headers = {'Accept':'application/vnd.github+json', 'User-Agent':'SkillScope-collector/4.0', 'X-GitHub-Api-Version':'2022-11-28'}
    token = os.environ.get('GITHUB_TOKEN')
    if token:
        headers['Authorization'] = 'Bearer ' + token
    req = Request(url, headers=headers)
    for attempt in range(2):
        try:
            with urlopen(req, timeout=TIMEOUT) as response:
                return json.loads(response.read(8*1024*1024))
        except HTTPError as error:
            detail = error.read(1000).decode('utf-8', errors='replace')
            if error.code in (403, 429):
                raise RuntimeError(f'GitHub API rate/permission limit HTTP {error.code}: {detail[:250]}')
            if attempt == 0 and error.code in (500,502,503,504):
                time.sleep(2); continue
            raise RuntimeError(f'GitHub API HTTP {error.code}: {detail[:250]}')
        except (URLError, TimeoutError) as error:
            if attempt == 0:
                time.sleep(2); continue
            raise RuntimeError(f'GitHub network error: {error}')


def titleize(s):
    return re.sub(r'[-_]+', ' ', s).strip().title()


def parse_frontmatter(content):
    """Extract name and description from small YAML frontmatter without executing it."""
    if not content.startswith('---'):
        return {}
    lines = content.splitlines()
    try:
        end = next(i for i, line in enumerate(lines[1:150], 1) if line.strip() == '---')
    except StopIteration:
        return {}
    out = {}
    for ix, line in enumerate(lines[1:end], 1):
        m = re.match(r'^(name|description)\s*:\s*(.*)$', line, re.I)
        if not m:
            continue
        key = m.group(1).lower()
        value = m.group(2).strip().strip("\"'")
        if value in ('|','>','|-','>-'):
            text=[]
            for following in lines[ix+1:end]:
                if following and not following.startswith((' ', '\t')):
                    break
                if following.strip():
                    text.append(following.strip())
            value = ' '.join(text)
        if value:
            out[key] = value[:450]
    return out


def classify(name, desc=''):
    s = (name + ' ' + desc).lower()
    scores = [len(re.findall(p, s, re.I)) for _,_,p in TOPICS]
    best = max(range(len(scores)), key=lambda i:scores[i])
    if scores[best] == 0:
        return '有趣的创新型 Skills', 'AI生产力', 0
    return TOPICS[best][0], TOPICS[best][1], scores[best]


def is_path_candidate(path, typ):
    if EXCLUDE.search(path): return False
    if path.startswith(('.github/workflows/', 'docs/','templates/')): return False
    if typ == 'Skill':
        return path.endswith('/SKILL.md') or path == 'SKILL.md'
    return path.endswith('/SKILL.md') or path.endswith('/.claude-plugin/plugin.json')


def key_for(repo, path):
    return hashlib.sha256((repo.lower()+'|'+path.lower()).encode()).hexdigest()[:20]


def extract_dir(path):
    if path.endswith('/.claude-plugin/plugin.json'):
        return path[:-len('/.claude-plugin/plugin.json')]
    if path.endswith('/SKILL.md'):
        return path[:-len('/SKILL.md')]
    return path.rsplit('/',1)[0] if '/' in path else ''


def slug_for(path):
    directory=extract_dir(path)
    return directory.rsplit('/',1)[-1] or path.split('/')[-1]


def discover(source):
    owner, repo = source['owner'], source['repo']
    info = api(f'/repos/{owner}/{repo}')
    branch = info.get('default_branch') or 'main'
    tree = api(f'/repos/{owner}/{repo}/git/trees/{quote(branch,safe="")}?recursive=1')
    if tree.get('truncated'):
        raise RuntimeError(f'{owner}/{repo} tree truncated; skip to avoid incomplete results')
    rows=[];seen=set()
    for item in tree.get('tree', []):
        p=item.get('path','')
        if item.get('type') != 'blob' or not is_path_candidate(p,source['type']): continue
        # Prefer SKILL.md when both plugin manifest and skill are present in same directory.
        key=owner+'/'+repo+'/'+p
        if key in seen: continue
        seen.add(key)
        slug=slug_for(p)
        if slug.startswith('.') or len(slug)>100: continue
        cat, subtype, hits=classify(slug+' '+p)
        if WEAK.search(slug) and hits<=1: continue
        if not hits: continue
        rows.append({'path':p,'sha':item.get('sha',''),'slug':slug,'cat':cat,'subtype':subtype,'hits':hits,'source':source,'branch':branch})
    return rows


def read_blob(owner, repo, sha):
    result=api(f'/repos/{owner}/{repo}/git/blobs/{quote(sha,safe="")}')
    raw=result.get('content','')
    if result.get('encoding')!='base64': return ''
    return base64.b64decode(raw).decode('utf-8','replace')[:55000]


def make_record(candidate, previous=None, fetch_description=True):
    src=candidate['source']; owner,repo=src['owner'],src['repo']
    path=candidate['path']; directory=extract_dir(path)
    slug=candidate['slug']; meta={}; blob_error=''
    if fetch_description:
        try:
            content=read_blob(owner,repo,candidate['sha'])
            meta=parse_frontmatter(content) if path.endswith('SKILL.md') else {}
            if path.endswith('plugin.json'):
                j=json.loads(content)
                if isinstance(j,dict):
                    meta={'name':str(j.get('name',slug)),'description':str(j.get('description',''))[:450]}
        except Exception as error:
            blob_error=str(error)[:200]
    else:
        if previous:
            meta={'name':previous.get('name',slug), 'description':previous.get('description','')}
    label=(meta.get('name') or titleize(slug))[:130]
    description=(meta.get('description') or '已发现官方/可信仓库中的技能文件，具体功能和依赖需查看来源说明。')[:450]
    cat,subcategory,hits=classify(slug+' '+path, description)
    url=f'https://github.com/{owner}/{repo}/tree/{quote(candidate["branch"],safe="")}/{quote(directory,safe="/")}' if directory else f'https://github.com/{owner}/{repo}'
    prev=previous or {}
    record={
        'id':'AUTO-'+key_for(owner+'/'+repo,path), 'name':label,'type':src['type'] if not path.endswith('SKILL.md') else 'Skill',
        'subtype':('Agent Skill' if path.endswith('SKILL.md') else 'Codex/Claude 插件'),
        'category':subcategory,'group':cat,'description':description,
        'scenario':f'适用领域：{cat}。仅为目录发现结果，使用前需阅读 SKILL.md、依赖与权限说明。',
        'provider':src['provider'],'platform':'视来源仓库与本地客户端而定，未进行兼容性实测',
        'url':url,'priority':'P1' if hits>=2 else 'P2', 'stage':'待审核',
        'verified':'自动核验公开仓库文件存在；安全/兼容性/安装均未实测',
        'risk':'第三方技能可能访问本地文件、凭证或外部网络；安装前审查代码、权限与依赖。',
        'install':f'请在源仓库 {owner}/{repo} 对应目录阅读 README 和 SKILL.md，按所用客户端的官方安装方法操作；尚未验证通用安装命令。',
        'action':'先审阅源码、权限和所需客户端，再在隔离测试环境实测。',
        'score':0,'added':prev.get('added',NOW()[:10]),
        'sourceRepo':f'{owner}/{repo}', 'sourcePath':path, 'blobSha':candidate['sha'],
        'lastSeenAt':NOW(), 'discoveredAt':prev.get('discoveredAt',NOW()),
        'githubUpdated': '', 'checkedAt':NOW(), 'updatedAt':NOW() if not prev or prev.get('blobSha')!=candidate['sha'] else prev.get('updatedAt',NOW()),
    }
    if blob_error: record['notes']='元信息读取失败，已保留为待审核：'+blob_error
    return record


def run(offline=False):
    before={}
    if OUTPUT.exists():
        loaded=json.loads(OUTPUT.read_text(encoding='utf-8'))
        for r in loaded.get('resources',[]):
            if isinstance(r,dict) and r.get('id'):before[r['id']]=r
    collected=[];errors=[];successful=[]
    if offline:
        src=SOURCES[0]
        demo=[{'path':'skills/pptx/SKILL.md','sha':'demo-sha-1','slug':'pptx','cat':'PPT / Word / Excel','subtype':'办公文档','hits':2,'source':src,'branch':'main'}, {'path':'skills/finance-forecast/SKILL.md','sha':'demo-sha-2','slug':'finance-forecast','cat':'经营与财务分析','subtype':'数据分析','hits':2,'source':src,'branch':'main'}]
        collected=demo;successful=['anthropics/skills (offline demo)']
    else:
        for src in SOURCES:
            try:
                found=discover(src)
                collected.extend(found)
                successful.append(f'{src["owner"]}/{src["repo"]} ({len(found)})')
            except Exception as err:
                errors.append(f'{src["owner"]}/{src["repo"]}: {err}')
    # high signal first; stable ordering
    collected.sort(key=lambda x:(-x['hits'], x['source']['owner'], x['source']['repo'], x['path']))
    result=dict(before);added=0;updated=0;fetched=0
    for c in collected:
        rid='AUTO-'+key_for(c['source']['owner']+'/'+c['source']['repo'],c['path'])
        old=result.get(rid)
        if old and old.get('blobSha')==c['sha']:
            continue
        if not old and (added>=NEW_PER_RUN or len(result)>=MAX_TOTAL): continue
        wants_blob=fetched<BLOB_READS_PER_RUN and not offline
        if old and not wants_blob:
            # An updated source must be reread before we change its last verified SHA.
            continue
        if wants_blob:fetched+=1
        record=make_record(c, old, wants_blob)
        if old:updated+=1
        else:added+=1
        result[rid]=record
    now=NOW()
    last_write=before and loaded.get('last_checked')
    try: hours=(dt.datetime.fromisoformat(now.replace('Z','+00:00')) - dt.datetime.fromisoformat(last_write.replace('Z','+00:00'))).total_seconds()/3600 if last_write else 999
    except (TypeError,ValueError):hours=999
    if not before or added or updated or hours>=12:
        payload={'schema_version':1,'generator':'SkillScope V4 GitHub Collector', 'last_checked':now,'sources_scanned':successful,'source_errors':errors,
                 'resource_count':len(result),'new_count':added,'updated_count':updated,
                 'resources':sorted(result.values(), key=lambda r:(r.get('group',''),r.get('name','').lower()))}
        OUTPUT.parent.mkdir(parents=True,exist_ok=True)
        OUTPUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        changed=True
    else:changed=False
    print(json.dumps({'checked':now,'source_success':successful,'errors':errors,'new':added,'updated':updated,'total':len(result),'file_written':changed},ensure_ascii=False))
    if errors and not successful:
        # all sources failing must surface as red workflow status; do not commit a false success.
        return 1
    return 0


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--demo',action='store_true');a=ap.parse_args()
    sys.exit(run(a.demo))
if __name__=='__main__':main()
