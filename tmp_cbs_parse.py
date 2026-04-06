import json, re, sys
import requests

url='https://www.cbsnews.com/live-updates/iran-war-us-trump-warns-more-coming-oil-gas-strait-hormuz/'
html=requests.get(url,timeout=30).text
m=re.search(r'__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
print('nextdata_found', bool(m))
if not m:
    sys.exit(1)

j=json.loads(m.group(1))

# recursive search for plausible liveblog post arrays

def find_lists(obj, path=''):
    if isinstance(obj, dict):
        for k,v in obj.items():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                # heuristics: keys like headline/title/body/date
                keys=set(v[0].keys())
                if {'headline','body'}.intersection(keys) and {'datePublished','published'}.intersection(keys):
                    yield path+'/'+k, v
            yield from find_lists(v, path+'/'+k)
    elif isinstance(obj, list):
        for i,v in enumerate(obj):
            yield from find_lists(v, path+f'[{i}]')

found=list(find_lists(j))
print('candidate_lists', len(found))
for path,lst in found[:10]:
    print('path', path, 'len', len(lst), 'keys0', list(lst[0].keys())[:12])

# Try to locate entry with headline containing 'cryptically'

def walk(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v)
    else:
        return

# brute-force scan through dicts

def scan_dicts(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from scan_dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from scan_dicts(v)

match=[]
for d in scan_dicts(j):
    h=d.get('headline') or d.get('title')
    if isinstance(h,str) and 'cryptic' in h.lower():
        match.append(d)

print('matches', len(match))
if match:
    d=match[0]
    # print key fields
    for k in ['id','_id','slug','url','canonicalUrl','headline','title','datePublished','published','dateModified','byline']:
        if k in d:
            print(k, d[k])
    # find any url-ish values
    for k,v in d.items():
        if isinstance(v,str) and v.startswith('http'):
            print('urlfield', k, v)

# also print any strings around post-update79 in raw html for locating anchor
idx=html.find('post-update79')
print('raw_idx', idx)
if idx!=-1:
    seg=html[idx:idx+4000]
    # find first 5 "url":"..." in seg
    urls=re.findall(r'"url":"(https:[^"]+)"', seg)
    print('seg_urls', urls[:5])
    print('seg_snip', seg[:600])
