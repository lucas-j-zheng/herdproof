#!/usr/bin/env python3
"""Bounded calibration-only probe; never replaces the frozen model or scores."""
import hashlib
import json
import time
from pathlib import Path
from aerial_infer import BASE, nms, starts
from aerial_metrics import evaluate, aggregate
import cv2
import torch
from ultralytics import YOLO, settings


def main():
    original=BASE/'validation/runs/finetuned'
    target=BASE/'validation/runs/crowding-probe'
    target.mkdir(parents=True,exist_ok=True)
    weights=original/'training-cpu/weights/last.pt'
    partitions=json.loads((original/'partitions.json').read_text())
    manifest=json.loads((BASE/'validation/data/manifest.json').read_text())
    records=[r for r in manifest['records'] if r['flight'] in partitions['calibration_flights']]
    protocol={'trigger':'User reports missed bunched cattle and adjacent marker deletion',
              'scope':'Existing five calibration images only; source labels are incomplete',
              'weights_sha256':hashlib.sha256(weights.read_bytes()).hexdigest(),
              'variants':[{'name':'less-suppression','tile':1024,'overlap':.2,'nms_iou':.7},
                          {'name':'closer-tiles','tile':512,'overlap':.2,'nms_iou':.7}],
              'input_size':1024,'confidence':.5,
              'deployment':'Diagnostic only. No automatic promotion or modification of benchmark/review proposals.'}
    frozen=target/'protocol.json'
    if frozen.exists() and json.loads(frozen.read_text())!=protocol:raise ValueError('Probe configuration changed')
    frozen.write_text(json.dumps(protocol,indent=2)+'\n')
    settings.update({'sync':False});torch.set_num_threads(4)
    model=YOLO(str(weights)).to('mps')
    scores={}
    baseline=[]
    for r in records:
        p=json.loads((original/(r['id']+'.json')).read_text())['modes']['tiled-finetuned']['boxes']
        baseline.append(evaluate(r,p,.5))
    scores['frozen-current']=aggregate(baseline)
    for variant in protocol['variants']:
        rows=[];elapsed=0
        for index,r in enumerate(records):
            output=target/(variant['name']+'-'+r['id']+'.json')
            if output.exists():prediction=json.loads(output.read_text())
            else:
                frame=cv2.imread(str(BASE/'validation/data'/r['image']));h,w=frame.shape[:2]
                boxes=[];begin=time.perf_counter();size=variant['tile']
                for y in starts(h,size,variant['overlap']):
                    for x in starts(w,size,variant['overlap']):
                        p=model.predict(frame[y:y+size,x:x+size],classes=[0],imgsz=1024,conf=.05,iou=variant['nms_iou'],max_det=1000,device='mps',verbose=False)[0]
                        for b,c in zip(p.boxes.xyxy.cpu().tolist(),p.boxes.conf.cpu().tolist()):
                            boxes.append([(b[0]+x)/w,(b[1]+y)/h,(b[2]+x)/w,(b[3]+y)/h,c])
                prediction={'boxes':nms(boxes,variant['nms_iou']),'seconds':time.perf_counter()-begin}
                output.write_text(json.dumps(prediction,indent=2)+'\n')
            rows.append(evaluate(r,prediction['boxes'],.5));elapsed+=prediction['seconds']
            print(f"{variant['name']} {index+1}/{len(records)}",flush=True)
        scores[variant['name']]={**aggregate(rows),'mean_seconds':elapsed/len(records)}
    report={'protocol':protocol,'results':scores,'interpretation':'Provisional annotation agreement on calibration data. This small probe neither validates crowded-cow accuracy nor repairs the missing labels.'}
    (target/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(scores,indent=2))


if __name__=='__main__':main()
