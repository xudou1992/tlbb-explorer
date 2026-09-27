# -*- coding: utf-8 -*-
"""sfl_sem.py — READ-ONLY: (a) join binary records to plaintext property names,
(b) emit the 12-file random sample tables (chunk/field/type/value + offsets),
(c) texture-name join vs local tree + resources.db, (d) correlation vs map size.
Outputs: sfl_sem_out.txt, sfl_sample12.md (fragments for the report)."""
import struct, glob, os, re, collections, random, json, sqlite3

import sfl_fields as F

FILES = F.FILES
HERE = r'D:\TLGL\.scratch'

KF3 = re.compile(r'([\d.]+):\(([^)]*)\):\d+')
KF1 = re.compile(r'([\d.]+):(-?[\d.]+):\d+')

def parse_curves(s):
    vals = []
    for m in KF3.finditer(s):
        try:
            vals.append(tuple(float(x) for x in m.group(2).split(':')))
        except ValueError:
            pass
    for m in KF1.finditer(s):
        seg = s[max(0, m.start() - 2):m.end() + 3]
        if '(' not in s[m.start():m.end()]:
            vals.append((float(m.group(2)),))
    return vals

def near(a, b):
    return abs(a - b) <= 2e-4

def per_file_model(d):
    raw, so, strs, h77, h76, h40 = None, d['strtab'], d['strings'], d['h77'], d['h76'], d['h40']
    names, curves = [], {}
    last = None
    for s, hv in strs:
        if 0 < len(s) < 45 and re.match(r'^[A-Za-z][A-Za-z0-9 ]*$', s):
            last = s
            names.append(s)
        elif ':' in s and last and last in names:
            curves.setdefault(last, []).extend(parse_curves(s + ','))
    return names, curves

# ---------- (a) value join ----------
JOINOUT = open(os.path.join(HERE, 'sfl_sem_out.txt'), 'w', encoding='utf-8')
def log(*a):
    print(*a)
    print(*a, file=JOINOUT)

field_names = collections.defaultdict(collections.Counter)
field_names_sec = collections.defaultdict(collections.Counter)
scalar_field_names = collections.defaultdict(collections.Counter)
for f in FILES:
    try:
        d = F.parse_file(f)
    except Exception:
        continue
    names, curves = per_file_model(d)
    for sec, recs, words in (('77', d['recs77'], d['words77']), ('76', d['recs76'], d['words76']),
                            ('40', d['recs40'] or [], d['words40'] or ())):
        for i, c, fl, w in recs:
            pl = words[i + 1:i + 1 + w]
            if c in (6, 7, 8):
                v3 = tuple(F.f32(x) for x in pl[:3])
                cands = set()
                for nm, cv in curves.items():
                    for tv in cv:
                        if len(tv) >= 3 and all(near(x, y) for x, y in zip(v3, tv[:3])):
                            cands.add(nm)
                            break
                for nm in cands:
                    field_names[('%s' % sec, c, fl)][nm] += 1
                    field_names_sec[(sec, c, fl)][nm] += 1
            elif c in (1, 3, 16) and w == 1:
                v = F.f32(pl[0])
                cands = set()
                for nm, cv in curves.items():
                    for tv in cv:
                        if len(tv) == 1 and near(v, tv[0]):
                            cands.add(nm)
                            break
                for nm in cands:
                    scalar_field_names[(sec, c, fl)][nm] += 1
log('=== record field -> property-name evidence (color/vec3 matches) ===')
for k in sorted(field_names, key=lambda k: (k[0], k[1], k[2])):
    log('%-14s -> %s' % ('%s/cls%d/fld%d' % k, dict(field_names[k].most_common(3))))
log('')
log('=== scalar record field -> candidate property names (multi=ambiguous) ===')
for k in sorted(scalar_field_names, key=lambda k: (k[0], k[1], k[2])):
    log('%-14s -> %s' % ('%s/cls%d/fld%d' % k, dict(scalar_field_names[k].most_common(6))))
JOINOUT.close()
