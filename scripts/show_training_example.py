#!/usr/bin/env python3
"""Render an actual stored training crop with its unchanged YOLO annotations."""
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

BASE=Path(__file__).resolve().parents[1]


def main():
    stem='5efc3f9db017_3276_1638'
    image_path=BASE/'validation/train-data/images/train'/f'{stem}.jpg'
    label_path=BASE/'validation/train-data/labels/train'/f'{stem}.txt'
    labels=[list(map(float,line.split())) for line in label_path.read_text().splitlines() if line.strip()]
    with Image.open(image_path) as source:
        photo=source.convert('RGB')
    w,h=photo.size;pad=24;top=128;bottom=100
    panel=Image.new('RGB',(w+2*pad,h+top+bottom),'#f3f5ef')
    panel.paste(photo,(pad,top))
    draw=ImageDraw.Draw(panel)
    title=ImageFont.load_default(size=30);body=ImageFont.load_default(size=19);small=ImageFont.load_default(size=16)
    draw.text((pad,20),f'Actual training crop | {len(labels)} annotation boxes',font=title,fill='#17352a')
    draw.text((pad,64),'Green boxes = supplied training labels. Class 0 = cattle.',font=body,fill='#17352a')
    draw.text((pad,94),'Stored 1024 x 1024 crop; resized to 640 for training, with augmentation.',font=body,fill='#526458')
    for cls,cx,cy,bw,bh in labels:
        assert cls==0
        draw.rectangle((pad+(cx-bw/2)*w,top+(cy-bh/2)*h,pad+(cx+bw/2)*w,top+(cy+bh/2)*h),outline='#31ff77',width=3)
    draw.text((pad,top+h+16),'Boxes at crop edges are clipped annotations of partially visible cows.',font=body,fill='#17352a')
    draw.text((pad,top+h+48),'ICAERUS grazing cows v2 | Helary & Lebreton / Institut de l’Elevage | CC BY 4.0',font=small,fill='#526458')
    draw.text((pad,top+h+73),'https://doi.org/10.5281/zenodo.11048412 | Source location metadata omitted.',font=small,fill='#526458')
    out=BASE/'validation/evidence/training-example.png';out.parent.mkdir(parents=True,exist_ok=True)
    panel.save(out)
    (out.with_suffix('.json')).write_text(json.dumps({'image':str(image_path.relative_to(BASE)),'labels':str(label_path.relative_to(BASE)),
        'split':'train','annotations':len(labels),'selection':'Most annotations among stored training crops, to illustrate crowded training examples',
        'display':'Unchanged source labels over actual stored crop; before training augmentation and resizing'},indent=2)+'\n')
    print(out)


if __name__=='__main__':main()
