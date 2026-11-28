"""Cross-run R3 acceptance, using unmodified pinned engine and aggregate artifact.
This deliberately simulates a partial checkpoint loss; not a runner-kill test.
"""
import hashlib,json,os,re,shutil,subprocess,sys,time
from pathlib import Path
from collections import Counter
PIN="a4e103d5e29c76636fe68c91c433455ff9c45c88"
IDENTITY="e4c5187e95ed0c27a132b3efed40062d1f51b4fd9007c7b71490bea1e4f58756"
MANIFEST="88faf02fd08c8062a9ae7e9e45bde1f108378b00ffcdbf6093951c54fe6f28b1"
def digest(x):
    return hashlib.sha256(json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(",",":"),allow_nan=False).encode()).hexdigest()
def emit(k,x):print(k+" "+json.dumps(x,ensure_ascii=False,sort_keys=True,allow_nan=False),flush=True)
def require(ok,msg):
    if not ok:raise RuntimeError(msg)
def load(path):
    rows={}
    for f in Path(path).glob("*.json"):
        row=json.loads(f.read_text(encoding="utf8"));code=row["code"];r=row["result"]
        require(re.fullmatch(r"\d{6}\.(SH|SZ)",code) and f.name==code+".json" and code not in rows,"invalid checkpoint key")
        require(row["schema"]==1 and row["identity"]==IDENTITY and re.fullmatch(r"[0-9a-f]{64}",row["source"]),"invalid original identity")
        require(digest(r)==row["digest"] and re.fullmatch(r"[0-9a-f]{64}",r["output_digest"]),"checkpoint integrity failure")
        require(r["counts"]["planned"]==r["counts"]["computed"]+r["counts"].get("not_observed",0),"invalid counts")
        rows[code]=row
    require(len(rows)==30,"expected 30 checkpoints")
    return rows
def counts(rows):
    c=Counter()
    for x in rows.values():c.update(x["result"]["counts"])
    return dict(c)
def payload(rows):
    return [[k,x["source"],x["result"]["output_digest"],x["result"]["counts"],x["result"]["paired_checks"],x["result"]["prefix_checks"]] for k,x in sorted(rows.items())]
def main():
    start=time.perf_counter()
    baseline,original,working=(Path(x).resolve() for x in sys.argv[1:4])
    require(len({baseline,original,working})==3,"paths must differ")
    actual=subprocess.check_output(["git","-C",str(baseline),"rev-parse","HEAD"],text=True).strip()
    require(actual==PIN,"wrong engine version")
    require(not subprocess.check_output(["git","-C",str(baseline),"status","--porcelain","--untracked-files=no"],text=True).strip(),"modified baseline")
    old=load(original);total=counts(old)
    require(all(total.get(k)==v for k,v in {"planned":830,"computed":825,"composite_ready":358,"context_ready":689,"label_5_clean":341,"label_20_clean":334}.items()),"original sample totals changed")
    codes=sorted(old)
    # Deterministic one-in-three removal, independent of past results or timings.
    recalc=set(codes[::3]);keep=set(codes)-recalc
    require(len(keep)==20 and len(recalc)==10,"incorrect split")
    working.mkdir(parents=True,exist_ok=True)
    require(not list(working.iterdir()),"working ledger must be empty")
    for k in sorted(keep):shutil.copy2(original/(k+".json"),working/(k+".json"))
    require(len(list(working.glob("*.json")))==20,"restore preparation failed")
    emit("TECH_E0_RESUME_PLAN",{"engine_commit":PIN,"source_run":46106077847,"retained":sorted(keep),"recompute":sorted(recalc),"original_payload_digest":digest(payload(old)),"original_counts":total,
        "retained_observations":sum(old[k]["result"]["counts"]["computed"] for k in keep),"recompute_observations":sum(old[k]["result"]["counts"]["computed"] for k in recalc)})
    # Identity legitimately refers to the checked-out engine, not the harness commit.
    env=dict(os.environ,GITHUB_SHA=actual,R3_LEDGER=str(working),PYTHONUNBUFFERED="1")
    resumed=[];fresh=[];done=[];manifest=[];t=time.perf_counter()
    with subprocess.Popen([sys.executable,"-m","technical.e0_r3_validate"],cwd=baseline,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1) as p:
        for line in p.stdout:
            print(line,end="",flush=True)
            for key,dest in (("TECH_E0_R3_RESUME ",resumed),("TECH_E0_R3_STOCK ",fresh),("TECH_E0_R3_DONE ",done),("TECH_E0_R3_MANIFEST ",manifest)):
                if line.startswith(key):dest.append(json.loads(line[len(key):]))
        require(p.wait()==0,"pinned engine failed")
    elapsed=time.perf_counter()-t
    require(len(manifest)==1 and manifest[0]["digest"]==MANIFEST,"manifest changed")
    require(len(done)==1 and done[0]["identity"]==IDENTITY,"shared source or version changed")
    d=done[0]
    require(len(resumed)==20 and {r["code"] for r in resumed}==keep,"expected 20 actual cache hits")
    require(len(fresh)==10 and {r["code"] for r in fresh}==recalc,"expected 10 actual worker completions")
    require(d["fresh"]==10 and d["resumed"]==20 and d["reopen_checks"]==30,"resume totals mismatch")
    new=load(working)
    require(set(new)==set(old),"checkpoint coverage mismatch")
    require(counts(new)==total==d["counts"],"aggregate count mismatch")
    require(payload(new)==payload(old),"source fingerprint, output hash, or per-stock counts mismatch")
    require(all(new[k]==old[k] for k in keep),"retained checkpoint mutated")
    # Runtime and RSS fields are not semantic hashes and may differ for recomputed stocks.
    old_keep=sum(old[k]["result"]["R3_compute_seconds"] for k in keep)
    old_recalc=sum(old[k]["result"]["R3_compute_seconds"] for k in recalc)
    new_recalc=sum(new[k]["result"]["R3_compute_seconds"] for k in recalc)
    out={"passed":True,"original_run":46106077847,"fresh":10,"resumed":20,"all_stock_hash_matches":30,"fresh_stock_hash_matches":10,"retained_stock_identical":20,
         "all_counts_equal":True,"counts":total,"original_payload_digest":digest(payload(old)),"restored_payload_digest":digest(payload(new)),
         "fresh_exact_pairs":sum(new[k]["result"]["paired_checks"] for k in recalc),"fresh_prefix_checks":sum(new[k]["result"]["prefix_checks"] for k in recalc),
         "retained_observations":sum(old[k]["result"]["counts"]["computed"] for k in keep),"fresh_observations":sum(new[k]["result"]["counts"]["computed"] for k in recalc),
         "old_full_worker_compute_seconds":old_keep+old_recalc,"estimated_avoided_worker_compute_seconds":old_keep,"old_recompute_subset_seconds":old_recalc,
         "actual_fresh_worker_compute_seconds":new_recalc,"actual_engine_wall_seconds":elapsed,"original_engine_wall_seconds":1278.807218441,
         "harness_wall_seconds":time.perf_counter()-start,"source_download_seconds":d["stock_download_seconds"],"api_counts":d["api_counts"],
         "raw_cache_persisted":False,"simulated_missing_checkpoints":True,"hard_kill_test":False}
    emit("TECH_E0_RESUME_ACCEPTANCE",out)
    (working.parent/"resume-acceptance.json").write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf8")
if __name__=="__main__":main()
