"""Independent finite replay. This module does not import the producer.

The lower-bound checker searches all covers of size at most p-1, with no
producer dominance pruning. It checks every stored circuit and then repeats
all encoder / total-decoder choices. This is executable finite verification,
not a formally verified checker and not SAT/DRAT proof replay.
"""
from __future__ import annotations
import argparse
import itertools
import json
import resource
import signal
import time
from functools import lru_cache
from pathlib import Path


def demand(condition, message):
    if not condition:
        raise ValueError(message)


def representations(q,n):
    domain=[]
    for value in range(q**n):
        digits=[]; a=value
        for _ in range(n): digits.append(a%q);a//=q
        digits=tuple(reversed(digits))
        bits=''.join(str(d) if q==2 else ('00','01','11')[d] for d in digits)
        domain.append((digits,int(bits,2)))
    return domain


def plane_value(terms, inp, width, outputs):
    value=0
    seen=set()
    for term in terms:
        cube=term['cube'];mask=term['outputs']
        demand(isinstance(cube,str) and len(cube)==width and set(cube)<=set('01*'),'invalid cube')
        demand(cube not in seen,'duplicate cube')
        seen.add(cube)
        demand(type(mask) is int and 0<mask<(1<<outputs),'invalid output mask')
        binary=format(inp,f'0{width}b')
        if all(c=='*' or c==v for c,v in zip(cube,binary)):
            value |= mask
    return value


def verify_plane(record, domain, width, outputs):
    table=record['table'];terms=record['terms'];claimed=record['products']
    demand(type(claimed) is int and claimed>=0 and claimed==len(terms),'wrong cost')
    demand(len(table)==len(domain),'wrong row count')
    demand(all(type(v) is int and 0<=v<(1<<outputs) for v in table),'bad output value')
    demand([plane_value(terms,v,width,outputs) for v in domain]==table,'circuit truth mismatch')
    rows=len(domain)
    target=sum(1<<(r*outputs+b) for r,v in enumerate(table) for b in range(outputs) if (v>>b)&1)
    covers=set()
    # Independently enumerate cubes as a care mask plus every legal bit value.
    for care in range(1<<width):
        value=care
        while True:
            matching=[r for r,v in enumerate(domain) if (v&care)==value]
            if matching:
                admissible=[b for b in range(outputs) if all((table[r]>>b)&1 for r in matching)]
                cover=sum(1<<(r*outputs+b) for r in matching for b in admissible)
                if cover: covers.add(cover)
            if value==0:break
            value=(value-1)&care
    if not target:
        demand(claimed==0,'nonminimal constant zero')
        return 1
    covers=tuple(sorted(covers))
    choices={b:tuple(c for c in covers if c&(1<<b)) for b in range(rows*outputs) if target&(1<<b)}
    visits=0

    @lru_cache(None)
    def cover_exists(rem, slots):
        nonlocal visits
        visits+=1
        if rem==0:return True
        if slots<=0:return False
        maximum=max((c&rem).bit_count() for c in covers)
        if (rem.bit_count()+maximum-1)//maximum>slots:return False
        bit=(rem&-rem).bit_length()-1
        # All options remain; order differs from the generator's rarest-cell DP.
        return any(cover_exists(rem&~c,slots-1) for c in choices[bit])

    demand(not cover_exists(target,claimed-1),'claimed cost is not minimal')
    return visits


def point_check(spec, witness):
    q,n,k=(spec[t] for t in ('q','n','k'))
    vals=representations(q,n)
    width=n*(1 if q==2 else 2)
    enc=witness['encoder_rows'];dec=witness['decoder_table']
    demand(len(enc)==1<<k and len(set(enc))==len(enc),'noninjective encoder')
    allowed={tuple(map(int,s)) for s in spec['allowed']}
    demand(all(type(c) is int and 0<=c<len(vals) and vals[c][0] in allowed for c in enc),'invalid codeword')
    demand(len(dec)==len(vals) and all(type(z) is int and 0<=z<1<<k for z in dec),'decoder range')
    ep=witness['encoder_plane'];dp=witness['decoder_plane']
    demand(ep['products']==len(ep['terms']) and dp['products']==len(dp['terms']),'product cost mismatch')
    for x,c in enumerate(enc):
        demand(plane_value(ep['terms'],x,k,width)==vals[c][1],'encoder implementation mismatch')
        demand(dec[c]==x,'inverse relation failure')
    for y,(_,v) in enumerate(vals):
        demand(plane_value(dp['terms'],v,width,k)==dec[y],'decoder implementation mismatch')
    actual=max((dec[y]^x).bit_count() for x,c in enumerate(enc) for y in range(len(vals))
               if sum(u!=v for u,v in zip(vals[c][0],vals[y][0]))<=spec['radius'])
    demand(actual==witness['error'],'incorrect total-decoder error')
    gates=ep['products']+dp['products']+width+k
    connections=sum(t['outputs'].bit_count() for p in (ep,dp) for t in p['terms'])
    demand(gates==witness['gates'] and gates<=spec['gate_cap'],'gate cost mismatch')
    demand(connections==witness['connections'] and connections<=spec['connection_cap'],'connection count mismatch')
    demand(ep['products']+dp['products']==witness['products'],'total products mismatch')


def frontier_check(result):
    expected=[];previous=None
    for a,g in enumerate(result['best_cost_by_error_bound']):
        if g is not None:
            demand(type(g) is int and g>=0,'bad profile cost')
            demand(previous is None or g<=previous,'nonmonotone profile')
            if previous is None or g<previous: expected.append((a,g))
            previous=g
        else:
            demand(previous is None,'feasibility disappears as error bound increases')
    demand([(w['error'],w['gates']) for w in result['frontier']]==expected,
           'incomplete or nonminimal frontier')
    return expected


def replay(spec, directory):
    cpu=time.process_time();wall=time.perf_counter()
    id=spec['id']
    result=json.loads((directory/(id+'.json')).read_text())
    demand(result['case']==spec,'specification mismatch')
    proofs=json.loads((directory/(id+'-costs.json')).read_text())
    q,n,k=(spec[t] for t in ('q','n','k'))
    vals=representations(q,n);width=n*(1 if q==2 else 2)
    domains=(tuple(range(1<<k)),tuple(v for _,v in vals))
    costs=[];connections=[];checks=0;nodes=0
    for label,domain,inwidth,outwidth in [('encoder',domains[0],k,width),('decoder',domains[1],width,k)]:
        cd={};conn={}
        for rec in proofs[label]:
            key=tuple(rec['table'])
            demand(key not in cd,'duplicate cost-table entry')
            nodes+=verify_plane(rec,domain,inwidth,outwidth)
            cd[key]=rec['products']
            conn[key]=sum(t['outputs'].bit_count() for t in rec['terms'])
            checks+=1
        costs.append(cd);connections.append(conn)
    allowed=[i for i,(w,_) in enumerate(vals) if ''.join(map(str,w)) in spec['allowed']]
    nc=1<<k;best=[None]*(k+1);candidate_count=0
    visited=[set(),set()];hist={}
    for mapping in itertools.permutations(allowed,nc):
        et=tuple(vals[c][1] for c in mapping)
        demand(et in costs[0],'encoder cost missing')
        visited[0].add(et)
        free=[y for y in range(len(vals)) if y not in mapping]
        # Independent direct minimax table. This precomputes only row-local
        # distances, not the producer's objective values or cost recursion.
        harms=[[0]*nc for _ in vals]
        for y,(received,_) in enumerate(vals):
            for z in range(nc):
                for x,c in enumerate(mapping):
                    if sum(a!=b for a,b in zip(received,vals[c][0]))<=spec['radius']:
                        harms[y][z]=max(harms[y][z],bin(x^z).count('1'))
        for completion in itertools.product(range(nc),repeat=len(free)):
            candidate_count+=1
            d=[-1]*len(vals)
            for x,c in enumerate(mapping):d[c]=x
            for y,z in zip(free,completion):d[y]=z
            dt=tuple(d)
            demand(dt in costs[1],'decoder cost missing')
            visited[1].add(dt)
            g=costs[0][et]+costs[1][dt]+width+k
            demand(connections[0][et]+connections[1][dt]<=spec['connection_cap'],'cap-relaxation gap')
            if g>spec['gate_cap']:continue
            a=max(harms[y][z] for y,z in enumerate(d))
            hist[(a,g)]=hist.get((a,g),0)+1
            for bound in range(a,k+1):
                if best[bound] is None or g<best[bound]:best[bound]=g
    demand(candidate_count==result['candidate_designs'],'candidate count mismatch')
    demand(best==result['best_cost_by_error_bound'],'frontier profile mismatch')
    demand(all(set(cd)==seen for cd,seen in zip(costs,visited)),'extraneous/missing cost certificate')
    expected=frontier_check(result)
    demand(result['histogram']==[{'error':a,'gates':g,'count':num} for (a,g),num in sorted(hist.items())],'histogram mismatch')
    for point in result['frontier']:point_check(spec,point)
    summary={'case':id,'accepted':True,'candidate_designs_replayed':candidate_count,
             'plane_minimality_certificates':checks,'bounded_cover_nodes':nodes,
             'frontier':expected,'cpu_seconds':time.process_time()-cpu,
             'wall_seconds':time.perf_counter()-wall,
             'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    return summary


def main():
    p=argparse.ArgumentParser();p.add_argument('--case',required=True)
    p.add_argument('--inputs',type=Path,default=Path('inputs/cases.json'))
    p.add_argument('--results',type=Path,default=Path('results'))
    a=p.parse_args();signal.alarm(600)
    resource.setrlimit(resource.RLIMIT_AS,(3*1024**3,3*1024**3))
    spec=next(s for s in json.loads(a.inputs.read_text()) if s['id']==a.case)
    summary=replay(spec,a.results)
    (a.results/(a.case+'-check.json')).write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
