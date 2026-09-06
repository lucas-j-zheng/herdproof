"""Independent predictors prevent accidentally reusing a CPU predictor for MPS."""
import json
from pathlib import Path
from aerial_infer import BASE
import cv2
import torch
from ultralytics import YOLO

r=json.loads((BASE/"validation/calibration-sanity.json").read_text())
frame=cv2.imread(str(BASE/"validation/data"/r["image"]))
h,w=frame.shape[:2];b=r["boxes"][0]
x=max(0,min(w-1024,int((b[0]+b[2])/2*w)-512))
y=max(0,min(h-1024,int((b[1]+b[3])/2*h)-512))
tile=frame[y:y+1024,x:x+1024]
torch.set_num_threads(4)
output={"calibration_image_id":r["id"],"devices":{},"predictions":{}}
for device in ("cpu","mps"):
    model=YOLO(str(BASE/"validation/models/yolov8n.pt")).to(device)
    p=model.predict(tile,imgsz=1024,conf=.1,device=device,verbose=False)[0]
    output["devices"][device]=str(model.predictor.device)
    assert output["devices"][device]==device
    output["predictions"][device]=sorted(p.boxes.data.cpu().tolist(),key=lambda b:-b[4])
    del model
left,right=output["predictions"]["cpu"],output["predictions"]["mps"]
output["same_count"]=len(left)==len(right)
output["maximum_delta"]=max((abs(a-b) for l,r in zip(left,right) for a,b in zip(l,r)),default=0)
(BASE/"validation/baseline-backend-check.json").write_text(json.dumps(output,indent=2)+"\n")
print(json.dumps({k:v for k,v in output.items() if k!='predictions'},indent=2))
