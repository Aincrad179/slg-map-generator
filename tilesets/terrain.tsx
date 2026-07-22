<?xml version="1.0" encoding="UTF-8"?>
<tileset version="1.10" tiledversion="1.11.0" name="terrain" tilewidth="205" tileheight="84" tilecount="8" columns="0">
  <grid orientation="isometric" width="1" height="1"/>
  <tile id="0"><image source="../assets/terrain/001.png" width="205" height="84"/></tile>
  <tile id="1"><image source="../assets/terrain/002.png" width="205" height="84"/></tile>
  <tile id="2"><image source="../assets/terrain/003.png" width="205" height="84"/></tile>
  <tile id="3"><image source="../assets/terrain/004.png" width="205" height="84"/></tile>
  <tile id="4"><image source="../assets/terrain/005.png" width="205" height="84"/></tile>
  <tile id="5"><image source="../assets/terrain/006.png" width="205" height="84"/></tile>
  <tile id="6"><image source="../assets/terrain/007.png" width="205" height="84"/></tile>
  <tile id="7"><image source="../assets/terrain/008.png" width="205" height="84"/></tile>
  <wangsets>
   <wangset name="道路" type="corner" tile="-1">
    <wangcolor name="草地" color="#5fa832" tile="-1" probability="1"/>
    <wangcolor name="土路" color="#c8a064" tile="-1" probability="1"/>
    <wangtile tileid="0" wangid="0,1,0,1,0,1,0,1"/>
    <wangtile tileid="1" wangid="0,2,0,2,0,2,0,2"/>
    <wangtile tileid="2" wangid="0,2,0,2,0,1,0,2"/>
    <wangtile tileid="3" wangid="0,2,0,1,0,2,0,2"/>
    <wangtile tileid="4" wangid="0,2,0,2,0,2,0,1"/>
    <wangtile tileid="5" wangid="0,1,0,2,0,2,0,1"/>
    <wangtile tileid="6" wangid="0,2,0,1,0,1,0,2"/>
    <wangtile tileid="7" wangid="0,1,0,2,0,2,0,2"/>
   </wangset>
  </wangsets>
</tileset>