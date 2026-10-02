"""Equal-candidate-pool weighted scalarization audit; not a solver-speed trial."""
import json
from pathlib import Path

WEIGHTS=((1,25),(1,8),(1,2),(1,1),(2,1),(8,1),(25,1))

def run():
    cases=json.loads(Path('inputs/cases.json').read_text());out=[]
    for s in cases:
        r=json.loads(Path('results',s['id']+'.json').read_text())
        pairs={(p['error'],p['gates']) for p in r['histogram']}
        recovered=set();records=[]
        for wa,wg in WEIGHTS:
            best=min(pairs,key=lambda p:(wa*p[0]+wg*p[1],p[0],p[1]))
            recovered.add(best);records.append({'weights':[wa,wg],'selected':list(best)})
        front={(p['error'],p['gates']) for p in r['frontier']}
        out.append({'case':s['id'],'candidate_pool_size':r['candidate_designs'],
                    'weights_and_selections':records,'frontier_size':len(front),
                    'recovered_frontier':sorted(front&recovered),'missed_frontier':sorted(front-recovered)})
    report={'protocol':'Both methods receive the same fully enumerated canonical-cost candidate pool. Histogram aggregation is lossless for strictly positive weighted objectives. No independent SAT baseline or runtime speedup is measured.','weights':WEIGHTS,'cases':out,
            'total_missed':sum(len(x['missed_frontier']) for x in out)}
    Path('results/scalarization.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Weighted scalarization missed',report['total_missed'],'frontier points in the locked pool.')
    return report
if __name__=='__main__':run()
