"""Finite owned process/real scheduler; synthetic reviews are not provider qualification."""

import json
import os
import subprocess
import sys
from pathlib import Path


def test_closed_browser_background_process_retains_two_clocked_occurrences(tmp_path):
    script = tmp_path / "owned-review-background.py"
    tests = Path(__file__).resolve().parent
    script.write_text(
        """import asyncio,json,os,sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[2])
from test_persistent_research import note,task,policy,response
from test_research_storage import plan_at
from trading.experiment_registry import ExperimentRegistry
from trading.research_knowledge import ResearchKnowledge
from trading.research_reviews import ResearchReviews
from trading.research_storage import ResearchStorage
from trading.role_worker import RoleWorker
root=Path(sys.argv[1])
clock=[time.time()]
time.time=lambda:clock[0]
storage=ResearchStorage(plan_at(root))
knowledge=ResearchKnowledge(storage)
knowledge.ingest(note())
registry=ExperimentRegistry(root/'registry.sqlite')
worker=RoleWorker(registry,None)
task(worker)
class Transport:
 def __init__(self):self.calls=[]
 def configured(self):return True
 async def review(self,run,cfg):
  self.calls.append(run['occurrence'])
  return response(run)
transport=Transport()
reviews=ResearchReviews(worker,knowledge,transport)
reviews.configure(policy(enabled=True,external_data_approved=True,spending_approved=True,
 schedule_owner_approved=True,supported_profile_verified=True),0)
async def main():
 running=asyncio.create_task(reviews.run())
 advanced=False
 try:
  async with asyncio.timeout(48):
   while (len(transport.calls)<2 or
          any(r['state']!='completed' for r in reviews.snapshot()['reviews'])):
    if (len(transport.calls)==1 and not advanced and
        reviews.snapshot()['reviews'][0]['state']=='completed'):
     clock[0]+=86401
     knowledge.ingest(note('second-occurrence-evidence'))
     advanced=True
    await asyncio.sleep(.05)
 finally:
  running.cancel()
  try:await running
  except asyncio.CancelledError:pass
 result={'pid':os.getpid(),'calls':transport.calls,'reviews':reviews.snapshot()['reviews'],
  'scope':'Owned background process; two synthetic-clock occurrences; no browser/model/network'}
 (root/'background-receipt.json').write_text(json.dumps(result),encoding='utf-8')
asyncio.run(main())
registry.close()
storage.close()
""",
        encoding="utf-8",
    )
    # subprocess.run owns and kills only this direct child on the finite deadline.
    subprocess.run(
        [sys.executable, "-B", str(script), str(tmp_path), str(tests)],
        timeout=55,
        check=True,
        capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    receipt = json.loads((tmp_path / "background-receipt.json").read_text(encoding="utf-8"))
    assert receipt["pid"] != os.getpid()
    assert len(receipt["calls"]) == len(set(receipt["calls"])) == 2
    assert all(row["state"] == "completed" for row in receipt["reviews"])
