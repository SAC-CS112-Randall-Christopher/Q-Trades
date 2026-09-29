"""Offline, disposable-state reproductions against the unchanged uploaded source."""
from pathlib import Path
import sys, json, copy
root=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(root/'src'),str(root/'tests')]
from trading.paper_engine import PaperEngine, initial_state, REVIEW_SECONDS
from test_paper_engine import START, buy, frame, study

# F01: A four-hour review resets a 35% drawdown stop without an operator command.
s=initial_state(START)
a=s['accounts']['primary']; a['cash']='64'
e=PaperEngine(s,START+1); e.value(a,{})
before={'pause':a['drawdown_pause'],'risk_peak':a['risk_peak'],'max_drawdown':a['max_drawdown']}
e=PaperEngine(s,START+REVIEW_SECONDS); e.review()
after={'pause':a['drawdown_pause'],'risk_peak':a['risk_peak'],'max_drawdown':a['max_drawdown'],'cooldown_until':a['cooldown_until']}

# F02: A pending ETH buy can fill while an existing BTC holding has no valid quote.
s2=initial_state(START); s2['accounts']={'primary':s2['accounts']['primary']}
buy(s2); a2=s2['accounts']['primary']
f=frame(START+3,sequence=3); f['base']='ETH'; f['instrument']={'symbol':'ETHUSD'}
e=PaperEngine(s2,START+3); e.value(a2,{'BTCUSD':frame(START+3,sequence=3),'ETHUSD':f})
intent_reason=e.enter('primary',a2,'ETHUSD',f,study()['BTCUSD']['breakout-v1'])
before_positions=list(a2['positions'])
f2=frame(START+5,sequence=4); f2['base']='ETH'; f2['instrument']={'symbol':'ETHUSD'}
e=PaperEngine(s2,START+5); e.tick({'ETHUSD':f2},{})
fills=[{'side':ev['body']['side'],'symbol':ev['body']['symbol']} for ev in e.events if ev['kind']=='fill']

# F03: Consumed holdout protection is optional to the numerical function, not a durable service.
from test_research import quote_rows
from trading.research_experiment import run_experiment
rows=quote_rows(600)
one=run_experiment(rows,'momentum_5',5)
two=run_experiment(rows,'momentum_1',5)
protected=run_experiment(rows,'momentum_1',5,prior_test_end=one['test_end'])
result={
'drawdown_review_rearm':{'before':before,'after':after},
'buy_with_unvalued_existing_inventory':{'intent_reason':intent_reason,'before_positions':before_positions,'after_positions':list(a2['positions']),'valuation_fresh':a2['valuation_fresh'],'fills':fills},
'holdout_guard_requires_caller_state':{'first_status':one['status'],'different_feature_same_data_default_status':two['status'],'explicit_consumed_boundary_status':protected['status']},
'qualification':'Synthetic fixtures establish program behavior only, not trading performance.'}
print(json.dumps(result,indent=2))
