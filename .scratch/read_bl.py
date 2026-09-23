import json

p = r'D:\TLGL\.scratch\baseline_now.json'
d = json.load(open(p, encoding='utf-8'))

print('groups      ', d['totals']['groups'])
print('image_sources', [(c['key'], c['n']) for c in d['image_sources']])
print('grades      ', [(c['key'], c['n']) for c in d['grades']])
print('coverage    ', d['grade_coverage'])
print('named       ', d['named'])
print('notes       ', d.get('notes'))
