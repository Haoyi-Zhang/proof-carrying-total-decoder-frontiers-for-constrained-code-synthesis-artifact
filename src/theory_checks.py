"""Finite checks of explicit witnesses and elementary local obstructions.
The written general arguments are in proofs/derivations.md. No theorem prover
is invoked and these tests are not a mechanization of the general proofs.
"""
from __future__ import annotations
import json
from pathlib import Path
from checker import point_check, demand


def evaluate():
    # Complete two-bit payload, four binary unit vectors, total 16-row decoder.
    spec={'id':'W01','q':2,'n':4,'k':2,'allowed':['1000','0100','0010','0001'],
          'radius':1,'gate_cap':24,'connection_cap':48}
    enc=[8,4,2,1]
    dec=[((not (y&8) and not (y&4))<<1) | (not (y&8) and not (y&2)) for y in range(16)]
    witness={'error':2,'gates':12,'products':6,'connections':6,'encoder_rows':enc,
             'decoder_table':list(map(int,dec)),
             'encoder_plane':{'products':4,'terms':[
                 {'cube':'00','outputs':8},{'cube':'01','outputs':4},
                 {'cube':'10','outputs':2},{'cube':'11','outputs':1}]},
             'decoder_plane':{'products':2,'terms':[
                 {'cube':'00**','outputs':2},{'cube':'0*0*','outputs':1}]}}
    point_check(spec,witness)
    pair_checks=[]
    for x in range(4):
        for z in range(x+1,4):
            dx=(x^z).bit_count();dc=(enc[x]^enc[z]).bit_count()
            demand(dx<=dc,'binary witness violates noncontraction')
            pair_checks.append({'messages':[x,z],'message_distance':dx,'code_distance':dc})
    balls=[{z for z in range(4) if (x^z).bit_count()<=1} for x in range(4)]
    intersection=set.intersection(*balls)
    demand(not intersection,'expected empty four-way intersection')
    triples=[]
    for removed in range(4):
        common=set.intersection(*(balls[x] for x in range(4) if x!=removed))
        demand(bool(common),'obstruction is not deletion-minimal')
        triples.append({'removed_message':removed,'common_outputs':sorted(common)})
    # The ternary cross matches all four possible payloads at received 00.
    enc_t=[(0,1),(0,2),(1,0),(2,0)]
    demand(all(sum(t!=0 for t in c)==1 for c in enc_t),'cross not radius one')
    demand(all((x^z).bit_count()<=sum(a!=b for a,b in zip(enc_t[x],enc_t[z]))
               for x in range(4) for z in range(4)),'ternary noncontraction failure')
    # Pin-use is not a valid general symmetry: redundancy can be constant.
    decoder=[0,0,1,1]
    demand(all(decoder[x<<1]==x for x in range(2)),'pin fixture inverse')
    pin_error=max((x^decoder[y]).bit_count() for x in range(2) for y in range(4)
                  if ((x<<1)^y).bit_count()<=1)
    demand(pin_error==1,'pin fixture total error')
    demand(all(decoder[y]==decoder[y^1] for y in range(4)),'pin not ignored')
    support={'encoder':[[0,0],[1,0]],'decoder_truth':decoder,
             'ignored_decoder_coordinate':1,'valid_inverse':True,'total_error':1}
    return {'binary_witness':{'spec':spec,'point':witness},'binary_pair_checks':pair_checks,
            'empty_four_ball_intersection':sorted(intersection),
            'deletion_minimality':triples,'ternary_cross_noncontractive':True,
            'ternary_zero_near_all_four':True,'pin_use_counterexample':support,
            'formal_status':'Explicit finite witness checks; general minimal-length and cover arguments are handwritten proofs.'}

if __name__=='__main__':
    r=evaluate();Path('results').mkdir(exist_ok=True)
    Path('results/theory.json').write_text(json.dumps(r,indent=2)+'\n')
    print('Explicit binary/ternary witnesses and four deletion checks passed.')
