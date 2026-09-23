"""Batch-run IDA MCP calls in one session (idac.py re-initialises on every call)."""
import json
import sys

sys.path.insert(0, r'D:\TLGL\.scratch')
import idac


def main():
    idac.session()
    spec = json.loads(open(sys.argv[1], encoding='utf-8').read())
    out = open(sys.argv[2], 'w', encoding='utf-8')
    for i, (tool, args) in enumerate(spec):
        r, _ = idac.post('tools/call', {'name': tool, 'arguments': args}, mid=i + 3)
        txt = '\n'.join(c.get('text', '') for c in r.get('result', {}).get('content', [])) \
            if 'error' not in r else json.dumps(r['error'])
        print('#### %s %s' % (tool, json.dumps(args, ensure_ascii=False)[:200]), file=out)
        print(txt[:20000], file=out)
    out.close()
    print('wrote', sys.argv[2])


if __name__ == '__main__':
    main()
