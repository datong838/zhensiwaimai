"""Find distinct visual message rectangles before matching image content."""
from PIL import Image,ImageChops,ImageStat,ImageFilter
from evidence import image_distance

def find_image_in_chat(image,before,target_path):
    with Image.open(target_path) as source:target=source.convert('RGB')
    w,h=image.size;scale=4
    small=image.resize((w//scale,h//scale));sw,sh=small.size
    bg=small.getpixel((int(sw*.4),int(sh*.5)))
    mask=Image.new('L',small.size);px=small.load();mp=mask.load()
    for y in range(int(sh*.1),int(sh*.82)):
        for x in range(int(sw*.42),int(sw*.945)):
            if max(abs(a-b) for a,b in zip(px[x,y],bg))>3:mp[x,y]=255
    mask=mask.filter(ImageFilter.MaxFilter(3));mp=mask.load();seen=set();boxes=[]
    for y in range(int(sh*.1),int(sh*.82)):
        for x in range(int(sw*.42),int(sw*.945)):
            if not mp[x,y] or (x,y) in seen:continue
            todo=[(x,y)];seen.add((x,y));xs=[];ys=[]
            while todo:
                a,b=todo.pop();xs.append(a);ys.append(b)
                for u,v in ((a-1,b),(a+1,b),(a,b-1),(a,b+1)):
                    if 0<=u<sw and 0<=v<sh and (u,v) not in seen and mp[u,v]:seen.add((u,v));todo.append((u,v))
            box=((min(xs)+1)*scale,(min(ys)+1)*scale,max(xs)*scale,max(ys)*scale)
            bw,bh=box[2]-box[0],box[3]-box[1]
            if bw>=80 and bh>=60 and box[2]>w*.8 and abs(bh/bw-target.height/target.width)<.12:boxes.append(box)
    matches=[];diagnostics=[]
    for box in boxes:
        best=None
        for dx in range(-4,5):
            for dy in range(-4,5):
                for dw in range(-6,7):
                    cw=box[2]-box[0]+dw;ch=round(cw*target.height/target.width)
                    b=(box[0]+dx,box[1]+dy,box[0]+dx+cw,box[1]+dy+ch)
                    crop=image.crop(b);score=image_distance(target,crop)
                    if best is None or score<best[0]:best=(score,b)
        score,b=best
        delta=sum(ImageStat.Stat(ImageChops.difference(image.crop(b),before.crop(b))).mean)
        diagnostics.append({'score':score,'delta':delta,'box':b})
        if score<=8 and delta>8:
            # Upload spinner sits immediately left of an outgoing image.
            strip=image.crop((max(0,b[0]-60),int((b[1]+b[3])/2-25),b[0]-5,int((b[1]+b[3])/2+25))).convert('L')
            dark=sum(1 for v in strip.getdata() if v<180)
            if dark>20:continue
            matches.append({'ok':True,'distance':round(score,3),'center':[(b[0]+b[2])/2,(b[1]+b[3])/2],'box':b,'changed':delta})
    if len(matches)!=1:return {'ok':False,'reason':'image-content-not-matched' if not matches else 'image-content-ambiguous','candidates':diagnostics}
    return matches[0]
