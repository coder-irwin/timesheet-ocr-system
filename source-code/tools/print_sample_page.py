import json, sys
M={m['i']:m for m in json.load(open('data/_sample50/manifest.json'))}
for i in (int(x) for x in sys.argv[1:]):
    m=M[i]; s=m.get('summary') or {}
    print(f"=== s{i:02d} {m['dataset']} {m['verdict']} | name={m.get('name')!r} code={m.get('code')!r} period={m.get('period')!r} | status={m['status']} rows={m['row_summary']}")
    print(f"    summary P={s.get('total_present_days')} A={s.get('total_absent_days')} L={s.get('total_leave_days')} W={s.get('total_weekly_off')} H={s.get('total_public_holiday')} C={s.get('total_comp_off')} manhrs={s.get('total_man_hours')}")
    line=[f"{d['day']}:{d.get('status') or '·'}{ {'must_fix':'!','review':'?','ok':''}.get(d.get('_review'),'') }[{str(d.get('in_time') or '')[:5]}-{str(d.get('out_time') or '')[:5]}|{str(d.get('normal_hours') or '')[:4]}|{str(d.get('remarks') or '')[:8]}]" for d in m['days']]
    for k in range(0,len(line),5): print("    "+"  ".join(line[k:k+5]))
    print(f"    image: {m['img']}")
