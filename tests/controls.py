"""Eight named negative / infeasibility controls, not eight new workloads."""
from __future__ import annotations
import copy
import json
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from checker import point_check,frontier_check,verify_plane,demand
from synthesis import run_case


def rejected(fn):
    try:fn()
    except ValueError as error:return str(error)
    raise AssertionError('A malformed object was accepted')


def run(directory=Path('results')):
    cases=json.loads(Path('inputs/cases.json').read_text());out=[]
    for ident,q,n,allowed in [('C01',2,2,['00','01','10']),('C02',3,1,['0','1','2'])]:
        spec=dict(id=ident,q=q,n=n,k=2,allowed=allowed,purpose='codeword-capacity infeasibility',radius=1,gate_cap=24,connection_cap=48)
        r=run_case(spec,directory)
        demand(r['candidate_designs']==0 and r['frontier']==[],'capacity control failed')
        out.append({'id':ident,'kind':'infeasible specification','passed':True,'reason':'fewer than four allowed words for four distinct messages'})
    spec=next(s for s in cases if s['id']=='B01')
    result=json.loads((directory/'B01.json').read_text());point=result['frontier'][0]
    w=copy.deepcopy(point);w['decoder_table'][w['encoder_rows'][0]]^=1
    out.append({'id':'C03','kind':'inverse mutation','passed':True,'rejection':rejected(lambda:point_check(spec,w))})
    t=next(s for s in cases if s['id']=='T02')
    wp=copy.deepcopy(json.loads((directory/'T02.json').read_text())['frontier'][0]);wp['error']=1
    out.append({'id':'C04','kind':'understated total-error bound','passed':True,'rejection':rejected(lambda:point_check(t,wp))})
    w=copy.deepcopy(point)
    done=False
    for term in w['encoder_plane']['terms']:
        for j,c in enumerate(term['cube']):
            if c!='*':
                term['cube']=term['cube'][:j]+str(1-int(c))+term['cube'][j+1:];done=True;break
        if done:break
    demand(done,'no mutable literal in chosen witness')
    out.append({'id':'C05','kind':'encoder literal mutation','passed':True,'rejection':rejected(lambda:point_check(spec,w))})
    w=copy.deepcopy(point);w['gates']-=1
    out.append({'id':'C06','kind':'understated gate cost','passed':True,'rejection':rejected(lambda:point_check(spec,w))})
    changed=copy.deepcopy(result);changed['frontier']=[]
    out.append({'id':'C07','kind':'deleted frontier witness','passed':True,'rejection':rejected(lambda:frontier_check(changed))})
    nonminimal={'table':[0,0,1,1],'products':2,'terms':[{'cube':'10','outputs':1},{'cube':'11','outputs':1}]}
    out.append({'id':'C08','kind':'functional but nonminimal cover','passed':True,'rejection':rejected(lambda:verify_plane(nonminimal,(0,1,2,3),2,1))})
    demand(len(out)==8 and all(x['passed'] for x in out),'control campaign incomplete')
    (directory/'controls.json').write_text(json.dumps(out,indent=2)+'\n')
    return out
if __name__=='__main__':
    r=run();print('Eight named controls passed; six are malformed-certificate controls.')
