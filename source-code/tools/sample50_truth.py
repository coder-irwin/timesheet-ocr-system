"""Build data/_sample50/truth.json from the v32 manifest + the hand-grade overrides in grades.md.
Truth per readable page: day -> list of acceptable statuses (first = protocol/strict, rest = sheet convention).
'' = the row is blank/struck on paper (empty output is right). Days not listed are not on the paper (spurious if emitted).
Overrides transcribed from data/_sample50/grades.md (D-045). Run once; re-run only if grades.md changes."""
import json
M={m['i']:m for m in json.load(open('data/_sample50/manifest.json'))}
REFUSED={0,18,19,21,23,27,29,30,31,32}; UNREADABLE={35,41}
def rng(a,b): return list(range(a,b+1))
OV={  # page -> {day: acceptable list}; 'N' = days on paper; 'empty' = days that are blank/struck on paper
  2:{3:['P','W'],10:['P','W'],17:['P','W'],24:['P','W'],4:['L'],5:['L'],31:['W'],'N':31},
  3:{7:['P'],'N':31},
  4:{3:['W'],10:['W'],17:['W'],24:['W'],31:['W'],7:['C'],22:['C'],25:['C'],'N':31},
  5:{31:['P'],'N':31,'empty':rng(1,16)},
  6:{9:['P'],16:['P'],22:['W'],23:['P'],28:['P'],29:['W'],30:['P'],'N':30},
  7:{26:['W'],31:['P'],'N':31},
  8:{4:['W'],5:['W'],11:['W'],17:['W'],18:['W'],24:['W'],25:['W'],12:['W'],'N':31},
  9:{1:['H'],2:['W'],9:['W'],10:['W'],16:['W'],17:['W'],24:['W'],30:['W'],3:['W'],23:['W'],31:['W'],'N':31},
  10:{3:['P','W'],10:['P','W'],17:['P','W'],'N':31},
  12:{3:['P','W'],31:['P','W'],'N':31},
  13:{20:['C'],22:['C'],'N':30},
  14:{26:['P','W'],'N':30},
  16:{'N':31,'empty':[1,2,4,5,6,7,8,9]},
  17:{25:['W'],26:['P'],'N':30},
  20:{1:['P'],3:['P'],9:['P'],5:['W'],'N':30,'empty':rng(23,30)},
  22:{28:['L'],31:['P','W'],'N':31},
  24:{31:['P'],'N':31},
  26:{6:['H'],28:['W'],29:['P'],30:['P'],31:['P'],'N':31},
  28:{'N':30,'empty':rng(1,14)},
  38:{'N':30}, 44:{'N':30},
  40:{**{d:['P'] for d in rng(1,4)+rng(6,11)+[13,14]+rng(16,18)+rng(20,22)+rng(27,30)},
      5:['P','W'],19:['P','W'],12:['W'],15:['H','W'],23:['H'],24:['C'],25:['C'],26:['W'],'N':30},
  43:{31:['P'],'N':31},
  49:{1:['P'],19:['W'],'N':30},
}
truth={}
for i,m in M.items():
    if i in REFUSED or i in UNREADABLE: continue
    ov=OV.get(i,{}); days={}
    got={d['day']:(d.get('status') or '') for d in m['days']}
    N=ov.get('N') or max(got)
    for d in range(1,N+1):
        if d in ov.get('empty',[]): days[d]=['']
        elif d in ov and d!='N': days[d]=ov[d]
        elif d in got: days[d]=[got[d]]
        else: raise SystemExit(f"s{i:02d} day {d}: no truth")
    truth[i]={'N':N,'days':{str(d):v for d,v in days.items()},'img':m['img']}
json.dump(truth,open('data/_sample50/truth.json','w'),indent=0)
print("truth pages:",len(truth),"rows:",sum(t['N'] for t in truth.values()))
