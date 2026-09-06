"""Shared metric coordinate conventions and terrain/camera transforms."""
from __future__ import annotations

import cv2
import numpy as np
import rasterio
from scipy.optimize import brentq

from world_core import read


class Terrain:
    def __init__(self,path,window,origin,crs):
        self.origin=np.array(origin,float)
        if self.origin.shape!=(3,) or not np.isfinite(self.origin).all():
            raise ValueError("Invalid terrain origin")
        with rasterio.open(path) as ds:
            if ds.transform.b or ds.transform.d or ds.transform.a<=0 or ds.transform.e>=0 or abs(ds.res[0]-ds.res[1])>1e-9:
                raise ValueError("Terrain must be a north-up square-cell metric raster")
            # Some IGN WMS GeoTIFFs have malformed CRS names. Configuration explicitly
            # declares the CRS and provider metadata; do not silently reproject them.
            if not rasterio.crs.CRS.from_string(crs).is_projected:
                raise ValueError("Terrain CRS must use projected metric coordinates")
            declared=rasterio.crs.CRS.from_string(crs)
            if declared.linear_units not in ("metre","meter"):
                raise ValueError("Terrain CRS units must be metres")
            if ds.crs and ds.crs.to_epsg() and ds.crs.to_epsg()!=declared.to_epsg():
                raise ValueError("Terrain raster CRS disagrees with configuration")
            r,c,h,w=window
            if any(not isinstance(v,int) for v in window) or min(r,c)<0 or min(h,w)<2 or r+h>ds.height or c+w>ds.width:
                raise ValueError("Terrain window lies outside the supplied raster")
            a=ds.read(1,window=rasterio.windows.Window(c,r,w,h),masked=True)
            self.valid=(~np.ma.getmaskarray(a)&np.isfinite(a.data)).astype(np.uint8)
            if not self.valid.any():
                raise ValueError("Terrain window contains no measured heights")
            self.heights=np.where(self.valid,a.data.astype(float)-self.origin[2],0).astype('<f4')
            self.spacing=float(ds.res[0]);self.w=w;self.h=h
            self.min_x=ds.transform.c+(c+.5)*self.spacing-self.origin[0]
            self.min_z=-(ds.transform.f-(r+.5)*self.spacing-self.origin[1])
            self.source=np.asarray(a.data)
        self.max_x=self.min_x+(w-1)*self.spacing
        self.max_z=self.min_z+(h-1)*self.spacing

    def sample(self,x,z,allow_invalid=False):
        col=(np.asarray(x)-self.min_x)/self.spacing
        row=(np.asarray(z)-self.min_z)/self.spacing
        inside=np.isfinite(col+row)&(col>=-1e-7)&(row>=-1e-7)&(col<=self.w-1+1e-7)&(row<=self.h-1+1e-7)
        i=np.clip(np.floor(np.nan_to_num(row)).astype(int),0,self.h-2)
        j=np.clip(np.floor(np.nan_to_num(col)).astype(int),0,self.w-2)
        u=col-j;v=row-i;first=u+v<=1
        h=self.heights
        valid=inside & np.where(first,self.valid[i,j]&self.valid[i,j+1]&self.valid[i+1,j],
                               self.valid[i+1,j+1]&self.valid[i,j+1]&self.valid[i+1,j])
        y=np.where(first,h[i,j]*(1-u-v)+h[i,j+1]*u+h[i+1,j]*v,
                   h[i+1,j+1]*(u+v-1)+h[i,j+1]*(1-v)+h[i+1,j]*(1-u))
        if not allow_invalid and not np.all(valid):
            raise ValueError("Position is outside measured terrain or crosses missing cells")
        return np.where(valid,y,np.nan)

    def spec(self):
        altitude=self.heights[self.valid>0].astype(float)+self.origin[2]
        return {"width":self.w,"height":self.h,"spacing":self.spacing,
                "minX":float(self.min_x),"minZ":float(self.min_z),"file":"heights.bin",
                "validFile":"valid.bin","verticalExaggeration":1,
                "minAltitude":float(altitude.min()),"maxAltitude":float(altitude.max()),
                "diagonal":"top-right to bottom-left"}


class Camera:
    def __init__(self,data,terrain,image_meta):
        self.data=data;self.terrain=terrain
        self.R=np.array(data["world_to_camera_R"],float)
        self.C=np.array(data["camera_centre_enu"],float)
        self.K=np.array(data["K"],float);self.dist=np.array(data["distortion"],float)
        if self.R.shape!=(3,3) or self.C.shape!=(3,) or self.K.shape!=(3,3) or self.dist.shape!=(5,):
            raise ValueError("Invalid camera matrix dimensions")
        if not all(np.isfinite(a).all() for a in (self.R,self.C,self.K,self.dist)):
            raise ValueError("Camera parameters are nonfinite")
        if np.max(np.abs(self.R.T@self.R-np.eye(3)))>1e-6 or abs(np.linalg.det(self.R)-1)>1e-6:
            raise ValueError("Camera rotation is not a proper orthonormal matrix")
        if self.K[0,0]<=0 or self.K[1,1]<=0 or not np.allclose(self.K[2],[0,0,1]):
            raise ValueError("Invalid camera intrinsics")
        if not np.allclose(data["origin_enu"],terrain.origin,rtol=0,atol=1e-6):
            raise ValueError("Camera and terrain use different origins")
        self.to_normal=np.array(image_meta["raw_to_normalized"],float) if data.get("pixel_space","raw_image")=="raw_image" else np.eye(3)
        if data.get("pixel_space","raw_image") not in ("raw_image","normalized_image"):
            raise ValueError("Unknown camera pixel convention")
        self.to_camera=np.linalg.inv(self.to_normal)

    def project(self,points):
        points=np.asarray(points,float)
        original=points.shape[:-1]
        q=points.reshape(-1,3)[:,[0,2,1]].copy();q[:,1]*=-1
        uv=cv2.projectPoints(q,cv2.Rodrigues(self.R)[0],-self.R@self.C,self.K,self.dist)[0][:,0,:]
        p=np.einsum('nj,ij->ni',np.c_[uv,np.ones(len(uv))],self.to_normal,optimize=False)
        depth=np.einsum('nj,j->n',q-self.C,self.R[2],optimize=False)
        return p[:,:2].reshape(*original,2),depth.reshape(original)

    def hit(self,pixel,body=0):
        pixel=np.array([*pixel,1.])@self.to_camera.T
        undist=cv2.undistortPoints(pixel[:2].reshape(1,1,2),self.K,self.dist)[0,0]
        d=self.R.T@np.r_[undist,1.];d/=np.linalg.norm(d)
        if d[2]>=-1e-8:
            raise ValueError("Skyward camera ray")
        terrain=self.terrain;lo=0.;hi=10000.
        for o,v,mn,mx in ((self.C[0],d[0],terrain.min_x,terrain.max_x),(-self.C[1],-d[1],terrain.min_z,terrain.max_z)):
            if abs(v)<1e-12:
                if not mn<=o<=mx:raise ValueError("Camera ray misses terrain footprint")
            else:
                a,b=sorted(((mn-o)/v,(mx-o)/v));lo=max(lo,a);hi=min(hi,b)
        if lo>=hi:
            raise ValueError("Camera ray misses terrain footprint")
        def difference(t):
            p=self.C+t*d
            return p[2]-terrain.sample(p[0],-p[1])-body
        # First sign crossing, so a valley cannot make us choose a farther surface.
        t=np.linspace(lo+1e-7,hi-1e-7,257)
        p=self.C+t[:,None]*d
        delta=p[:,2]-terrain.sample(p[:,0],-p[:,1],True)-body
        for index in np.where((delta[:-1]>=0)&(delta[1:]<=0))[0]:
            distance=brentq(difference,t[index],t[index+1],xtol=1e-9)
            pos=self.C+distance*d
            return [float(pos[0]),float(terrain.sample(pos[0],-pos[1])),-float(pos[1])]
        raise ValueError("Observation does not intersect valid measured terrain")


def load_geometry(base,cfg,prepared):
    terrain=Terrain(base/cfg["terrain"],cfg["terrain_window"],cfg["origin_enu"],cfg["horizontal_crs"])
    data=read(base/cfg["camera"])
    if data.get("source_image_sha256") not in (None,prepared["image_sha256"]):
        raise ValueError("Camera calibration belongs to another source image")
    return terrain,Camera(data,terrain,prepared["image"])
