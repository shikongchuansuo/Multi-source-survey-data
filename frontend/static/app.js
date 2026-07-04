/* ============================================================
   多源勘察数据联动展示与证据链追溯系统 —— 前端主逻辑
   ============================================================ */
(function(){
'use strict';

// 全局状态
const STATE = {
  manifest: null,
  risks: [],            // [{id,...}]
  selectedRisk: null,   // 当前选中风险对象 id
  // 地图
  map: null,
  layers: { ortho:null, dem:null, route:null, bh:null, geo:null, risk:null },
  riskPolygons: {},     // id -> L.Layer
  riskMarkers: {},      // id -> marker
  // 三维
  three: { scene:null, camera:null, renderer:null, controls:null, points:null, slopeAttr:null },
  // 物探图表 (ECharts)
  geoChart: null,
};

const COLORS = {
  '高':   {fill:'rgba(255,77,94,.28)', stroke:'#ff4d5e', text:'#ff8090'},
  '中高': {fill:'rgba(255,122,61,.25)', stroke:'#ff7a3d', text:'#ff9a6b'},
  '中':   {fill:'rgba(255,205,61,.22)', stroke:'#ffcd3d', text:'#ffdb6b'},
};

// ---------- 工具 ----------
const $ = (s,el=document)=>el.querySelector(s);
const $$ = (s,el=document)=>Array.from(el.querySelectorAll(s));
const xyToLatLng = (xy) => [xy[1], xy[0]];   // 工程坐标 (X,Y) -> [lat=Y, lng=X]
async function getJSON(url){
  const r = await fetch(url);
  if(!r.ok) throw new Error(`${url} -> ${r.status}`);
  return r.json();
}
function fmt(n,d=1){return Number(n).toFixed(d)}

// ============================================================
// 初始化
// ============================================================
let _initStarted = false;
async function init(){
  if(_initStarted) return;   // 防止 DOMContentLoaded + load 重复触发
  _initStarted = true;
  try{
    STATE.manifest = await getJSON('/api/manifest');
    STATE.risks = STATE.manifest.risks;
    $('#scenario').textContent = STATE.manifest.project.scenario;
    renderDataSources(STATE.manifest.data_sources);
    initMap();
    initThree();
    initMileageAxis();
    renderReportSelect();
    bindEvents();
    $('#loading').classList.add('hide');
  }catch(e){
    $('#loading p').innerHTML = '⚠ 加载失败：'+e.message+'<br>请确认后端服务已在 <b>http://localhost:8000</b> 运行';
    console.error(e);
  }
}

// ============================================================
// 1) 地图 (Leaflet) —— 以工程坐标系 (X 米 = 经度, Y 米 = 纬度) 作为伪地理坐标
// ============================================================
function initMap(){
  const W = 1000, H = 800;
  const map = L.map('map', {
    crs: L.CRS.Simple,
    minZoom: -3, maxZoom: 3, zoomControl: true,
    attributionControl: false,
  });
  STATE.map = map;
  // bounds: 左上=[Y=H, X=0], 右下=[Y=0, X=W]   (Leaflet 用 [lat,lng]=[Y,X])
  const bounds = [[H,0],[0,W]];
  map.fitBounds(bounds);

  // 正射影像图层
  const orthoUrl = '/data/' + STATE.manifest.orthophoto.image;
  STATE.layers.ortho = L.imageOverlay(orthoUrl, bounds, {opacity:1, zIndex:10}).addTo(map);
  // DEM 图层 (默认隐藏)
  const demUrl = '/data/' + STATE.manifest.dem.image;
  STATE.layers.dem = L.imageOverlay(demUrl, bounds, {opacity:0.85, zIndex:9});

  // 线路中线 + 洞口标记 (统一放入一个图层组，便于开关)
  STATE.layers.route = L.layerGroup().addTo(map);
  const cl = STATE.manifest.route.centerline.map(p=>xyToLatLng(p.xy));
  L.polyline(cl, {color:'#3d8bff', weight:3, opacity:.9, dashArray:'8 6'}).addTo(STATE.layers.route);
  for(const portal of [STATE.manifest.route.portal_in, STATE.manifest.route.portal_out]){
    L.marker(xyToLatLng(portal.xy),{
      icon: portalIcon(portal.label.includes('进口')||portal.label.includes('洞口')?'out':'in')
    }).addTo(STATE.layers.route).bindPopup(`<b>${portal.label}</b><br>里程 ${portal.mileage}`);
  }

  // 钻孔 / 物探 / 风险图层
  STATE.layers.bh = L.layerGroup().addTo(map);
  STATE.layers.geo = L.layerGroup().addTo(map);
  STATE.layers.risk = L.layerGroup().addTo(map);

  // 一次性绘制各要素
  drawBoreholes();
  drawGeoLines();
  drawRiskZones();

  // 坐标显示
  map.on('mousemove', e=>{
    const x = e.latlng.lng, y = e.latlng.lat;
    if(x>=0&&x<=W&&y>=0&&y<=H){
      const km = 12 + x/1000;
      $('#map-coord').textContent = `坐标 X=${fmt(x,0)}m Y=${fmt(y,0)}m · 里程 K${km.toFixed(3).slice(-5)}`;
    }
  });

  // 点击空白处取消高亮（保留选中状态在右侧）
}

function portalIcon(kind){
  return L.divIcon({
    className:'portal-icon',
    html:`<div style="font-size:22px;text-align:center;filter:drop-shadow(0 2px 4px rgba(0,0,0,.6))">${kind==='out'?'🚇':'⛰️'}</div>`,
    iconSize:[28,28], iconAnchor:[14,14]
  });
}

function drawBoreholes(){
  // 从 manifest 没有钻孔，单独拉取
  fetch('/api/boreholes').then(r=>r.json()).then(d=>{
    const list = d.boreholes;
    STATE.boreholeCache = {};        // 缓存，供对话定位用
    for(const bh of list){
      STATE.boreholeCache[bh.id] = bh;
      const m = L.marker(xyToLatLng(bh.xy), {icon: bhIcon()})
        .bindPopup(`<b>${bh.id}</b> · 里程 ${bh.mileage}<br>孔深 ${bh.depth_m}m · 高程 ${bh.elevation}m`+
          (bh.water_depth_m!=null?`<br>地下水位 ${bh.water_depth_m}m`:'')+
          `<br><a href="/data/boreholes/${bh.id}.png" target="_blank">查看柱状图 ↗</a>`);
      m.addTo(STATE.layers.bh);
    }
  });
}
function bhIcon(){
  return L.divIcon({
    className:'bh-icon',
    html:`<div style="width:12px;height:12px;border-radius:50%;background:#28d1c4;border:2px solid #fff;box-shadow:0 0 6px rgba(40,209,196,.7)"></div>`,
    iconSize:[12,12], iconAnchor:[6,6]
  });
}

function drawGeoLines(){
  fetch('/api/geophysics').then(r=>r.json()).then(d=>{
    for(const line of d.lines){
      const latlngs = [xyToLatLng(line.start_xy), xyToLatLng(line.end_xy)];
      L.polyline(latlngs, {color:'#3d8bff', weight:2.5, opacity:.85, dashArray:'2 5'})
        .bindPopup(`<b>${line.name}</b><br>${line.method} · 长度 ${line.length_m}m<br>`+
          `<a href="/data/${line.image}" target="_blank">查看断面图 ↗</a>`)
        .addTo(STATE.layers.geo);
      // 端点标注
      L.marker(xyToLatLng(line.start_xy), {icon:labelIcon(line.id+"'"),iconSize:[24,16],iconAnchor:[0,8]}).addTo(STATE.layers.geo);
    }
  });
}
function labelIcon(txt){
  return L.divIcon({className:'lbl-icon',html:`<div style="font-size:11px;color:#3d8bff;font-weight:700;text-shadow:0 0 3px #000,0 0 3px #000">${txt}</div>`});
}

function drawRiskZones(){
  for(const r of STATE.risks){
    const c = COLORS[r.risk_level] || COLORS['中'];
    const latlngs = r.polygon_xy.map(xyToLatLng);
    const poly = L.polygon(latlngs, {
      color:c.stroke, weight:2.5, fillColor:c.stroke, fillOpacity:.25, dashArray:'6 4'
    });
    poly.on('click', ()=> selectRisk(r.id));
    poly.addTo(STATE.layers.risk);
    STATE.riskPolygons[r.id] = poly;
    // 中心标签
    const mk = L.marker(xyToLatLng(r.center_xy), {icon: riskLabelIcon(r), zIndexOffset:1000});
    mk.on('click', ()=> selectRisk(r.id));
    mk.addTo(STATE.layers.risk);
    STATE.riskMarkers[r.id] = mk;
  }
}
function riskLabelIcon(r){
  const c = COLORS[r.risk_level] || COLORS['中'];
  return L.divIcon({
    className:'risk-label',
    html:`<div style="background:${c.stroke};color:#fff;padding:2px 8px;border-radius:10px;
      font-size:11px;font-weight:700;white-space:nowrap;box-shadow:0 2px 8px rgba(0,0,0,.5);
      border:1.5px solid #fff;text-align:center;cursor:pointer">
      ${r.mileage}<br><span style="font-size:9px">${r.type_cn}</span></div>`,
    iconSize:[80,32], iconAnchor:[40,16]
  });
}

function highlightRisk(id, on){
  const r = STATE.risks.find(x=>x.id===id); if(!r) return;
  const c = COLORS[r.risk_level] || COLORS['中'];
  const poly = STATE.riskPolygons[id];
  if(poly){
    poly.setStyle({weight:on?4:2.5, fillOpacity:on?.45:.25, color:on?'#fff':c.stroke});
    if(on && !poly._bring) { poly.bringToFront(); poly._bring=true; }
  }
}

// ============================================================
// 2) 三维点云 (Three.js)
//    点云范围 0..1000 × 0..800；以中心为原点，Y 当作平面纵轴，Z=高程
// ============================================================
function initThree(){
  const container = $('#three-container');
  const W = container.clientWidth, H = container.clientHeight;
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0c1322);
  // 雾效：远处淡入背景，增强空间深度感
  scene.fog = new THREE.Fog(0x0c1322, 800, 2200);
  STATE.three.scene = scene;

  const camera = new THREE.PerspectiveCamera(50, W/H, 1, 5000);
  camera.position.set(750, -750, 650);
  camera.up.set(0,0,1);
  STATE.three.camera = camera;

  const renderer = new THREE.WebGLRenderer({antialias:true, alpha:false});
  renderer.setSize(W, H);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  container.appendChild(renderer.domElement);
  STATE.three.renderer = renderer;

  const controls = new THREE.OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true; controls.dampingFactor = .08;
  controls.target.set(0,0,0);
  STATE.three.controls = controls;

  // --- 光照：半球光 + 三方向光，让地形有立体感与明暗层次 ---
  const hemi = new THREE.HemisphereLight(0xb8d0ff, 0x3a2818, .55);
  scene.add(hemi);
  scene.add(new THREE.AmbientLight(0xffffff, .35));
  // 主光（太阳，西南方向，高角度）
  const sun = new THREE.DirectionalLight(0xfff4e0, .7);
  sun.position.set(-400, 400, 800); scene.add(sun);
  // 填充光（反方向，柔和）
  const fill = new THREE.DirectionalLight(0x80a0ff, .3);
  fill.position.set(500, -300, 400); scene.add(fill);

  // 加载点云 / 地形 / 地质结构
  loadPointCloud();
  loadTerrainMesh();
  loadGeoStructures();

  // --- 空间参考：两片透明网格十字交叉，把空间分8块，主展示正半轴(+X+Y+Z)区域 ---
  // 数据范围：X[-500,500] Y[-400,400] Z[-30,150]。把交叉原点放在后下角(-500,-400,-30)，
  // 这样地形/点云/隧道/钻孔全部落在 +X/+Y/+Z 的"正卦限"里展示。
  // 面1：水平 XY 面（铺在 +X +Y 方向，Z 固定=-30 底面）
  // 面2：垂直 XZ 面（沿 +X +Z 方向，Y 固定=-400 后边界）
  // 两面在 Y=-400、Z=-30 的 X 轴线上十字交叉。
  const OX=-500, OY=-400, OZ=-30;       // 交叉原点（后下左角）
  const SX=1000, SY=800, SZ=180;        // 三个正方向的网格延伸长度
  const gridGroup = new THREE.Group(); gridGroup.name = 'crossGrids';

  // 通用：创建一个带网格线+半透明填充的面
  function makeGridFace(width, height, wSeg, hSeg, lineColor, fillColor){
    const g = new THREE.Group();
    // 半透明填充（让"面"有实体感）
    const fill = new THREE.Mesh(
      new THREE.PlaneGeometry(width, height),
      new THREE.MeshBasicMaterial({color:fillColor, transparent:true, opacity:.10, side:THREE.DoubleSide, depthWrite:false})
    );
    // 网格线
    const wire = new THREE.Mesh(
      new THREE.PlaneGeometry(width, height, wSeg, hSeg),
      new THREE.MeshBasicMaterial({color:lineColor, wireframe:true, transparent:true, opacity:.45, depthWrite:false})
    );
    g.add(fill, wire);
    return g;
  }

  // 面1：水平 XY 面（底面）。PlaneGeometry 默认在 XY 平面、中心在原点。
  // 把它平移到正方向：中心在 (OX+SX/2, OY+SY/2, OZ)
  const hFace = makeGridFace(SX, SY, 20, 16, 0xffffff, 0x2a4068);
  hFace.position.set(OX+SX/2, OY+SY/2, OZ);
  gridGroup.add(hFace);

  // 面2：垂直 XZ 面（后边界，纵剖面）。PlaneGeometry 默认 XY，绕 X 轴转 90° 变 XZ。
  // 旋转后宽=SX(X方向)、高=SZ(Z方向)，中心在 (OX+SX/2, OY, OZ+SZ/2)
  const vFace = makeGridFace(SX, SZ, 20, 9, 0xffd080, 0x3a2a08);
  vFace.rotation.x = Math.PI/2;          // XY -> XZ（立起来）
  vFace.position.set(OX+SX/2, OY, OZ+SZ/2);
  gridGroup.add(vFace);

  scene.add(gridGroup);

  // --- 坐标系：带标签的 3 轴 + 高程刻度（原点与网格交叉点对齐，指向正半轴）---
  const coordGroup = new THREE.Group(); coordGroup.name = 'coordSystem';
  const origin = new THREE.Vector3(OX, OY, OZ);  // 与网格交叉原点对齐
  const axLen = 220;
  // 三轴（加粗箭头）
  const mkArrow = (dir, color)=>{
    const arr = new THREE.ArrowHelper(dir, origin, axLen, color, 18, 12);
    return arr;
  };
  coordGroup.add(mkArrow(new THREE.Vector3(1,0,0), 0xff4d5e));   // X 红
  coordGroup.add(mkArrow(new THREE.Vector3(0,1,0), 0x3dd97a));   // Y 绿
  coordGroup.add(mkArrow(new THREE.Vector3(0,0,1), 0x3d8bff));   // Z 蓝
  // 轴标签
  coordGroup.add(makeTextSprite('X (东 E) / 里程', '#ff8090', origin.x+axLen+10, origin.y, origin.z));
  coordGroup.add(makeTextSprite('Y (北 N)', '#5fe0a0', origin.x, origin.y+axLen+10, origin.z));
  coordGroup.add(makeTextSprite('Z (高程 m)', '#7db0ff', origin.x-10, origin.y, origin.z+axLen+15));
  // 高程刻度（Z 轴每 50m 一格，从 950 到 1100）
  for(let elev=950; elev<=1100; elev+=50){
    const z = elev - 950;
    const tick = new THREE.Mesh(
      new THREE.BoxGeometry(10, 2, 0.5),
      new THREE.MeshBasicMaterial({color:0x5a7aaa})
    );
    tick.position.set(origin.x-5, origin.y, z);
    coordGroup.add(tick);
    coordGroup.add(makeTextSprite(elev+'m', '#8ea0bd', origin.x-35, origin.y, z, 32));
  }
  scene.add(coordGroup);

  // --- 指北针（右上角浮于场景的 N 标记）---
  const northGroup = new THREE.Group(); northGroup.name = 'compass';
  const northArrow = new THREE.ArrowHelper(
    new THREE.Vector3(0,1,0), new THREE.Vector3(0,0,0), 80,
    0xff4d5e, 25, 15
  );
  northGroup.add(northArrow);
  northGroup.add(makeTextSprite('N', '#ff4d5e', 0, 90, 0, 48));
  northGroup.position.set(480, -380, 200);  // 场景东南角上方
  scene.add(northGroup);

  // --- 比例尺（地表上的 100m 参考线段）---
  const scaleGroup = new THREE.Group(); scaleGroup.name = 'scalebar';
  const scaleMat = new THREE.LineBasicMaterial({color:0xffffff, linewidth:2});
  const scalePts = [new THREE.Vector3(-450,-380,1), new THREE.Vector3(-350,-380,1)];
  const scaleGeom = new THREE.BufferGeometry().setFromPoints(scalePts);
  scaleGroup.add(new THREE.Line(scaleGeom, scaleMat));
  // 端点小球
  for(const p of scalePts){
    const dot = new THREE.Mesh(new THREE.SphereGeometry(3,8,6), new THREE.MeshBasicMaterial({color:0xffffff}));
    dot.position.copy(p); scaleGroup.add(dot);
  }
  scaleGroup.add(makeTextSprite('100 m', '#ffffff', -400, -395, 1, 32));
  scene.add(scaleGroup);

  // --- 区域边界框（虚线，让空间范围一目了然）---
  const bboxPts = [
    [-500,-400,-30],[500,-400,-30],[500,400,-30],[-500,400,-30],[-500,-400,-30],
  ].map(p=>new THREE.Vector3(p[0],p[1],p[2]));
  const bboxGeom = new THREE.BufferGeometry().setFromPoints(bboxPts);
  const bboxMat = new THREE.LineDashedMaterial({color:0x3a5070, dashSize:8, gapSize:6});
  const bbox = new THREE.Line(bboxGeom, bboxMat); bbox.computeLineDistances();
  scene.add(bbox);

  // 动画
  function animate(){
    requestAnimationFrame(animate);
    controls.update();
    renderer.render(scene, camera);
  }
  animate();
}

// 生成文字精灵（始终面向相机的标签）
function makeTextSprite(text, color, x, y, z, fontsize=40){
  const canvas = document.createElement('canvas');
  canvas.width = 256; canvas.height = 64;
  const ctx = canvas.getContext('2d');
  ctx.font = `bold ${fontsize}px Microsoft YaHei, sans-serif`;
  ctx.fillStyle = color; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.shadowColor = 'rgba(0,0,0,.9)'; ctx.shadowBlur = 6;
  ctx.fillText(text, 128, 32);
  const tex = new THREE.CanvasTexture(canvas);
  tex.minFilter = THREE.LinearFilter;
  const mat = new THREE.SpriteMaterial({map:tex, transparent:true, depthTest:false});
  const sp = new THREE.Sprite(mat);
  sp.position.set(x, y, z);
  sp.scale.set(60, 15, 1);
  return sp;
}

function loadPointCloud(){
  const loader = new THREE.PLYLoader();
  loader.load('/data/'+STATE.manifest.pointcloud.file, (geom)=>{
    // PLY 顶点坐标范围 0..1000, 0..800, Z=高程(~920..1075)
    // 平移到原点：X-=500, Y-=400, Z-=950
    const pos = geom.attributes.position;
    const arr = pos.array;
    for(let i=0;i<arr.length;i+=3){
      arr[i]   -= 500;
      arr[i+1] -= 400;
      arr[i+2] -= 950;
    }
    pos.needsUpdate = true;
    geom.computeBoundingBox();
    geom.center();  // 重新中心化 X/Y 但保持 Z
    // PLYLoader 已读入 color 属性，转 vertexColors
    const mat = new THREE.PointsMaterial({
      size: 2.2, vertexColors: true, sizeAttenuation: true
    });
    const points = new THREE.Points(geom, mat);
    STATE.three.points = points;
    STATE.three.scene.add(points);
    const n = geom.attributes.position.count;
    $('#three-info').textContent = `点云 ${n.toLocaleString()} 点 · 坡度着色`;
  }, undefined, (err)=>{
    $('#three-info').textContent = '⚠ 点云加载失败';
    console.error(err);
  });
}

// ============================================================
// 2a) 遥感影像 + DEM 3D 地形表面（多源融合的关键：把正射影像贴到地形上）
// ============================================================
function loadTerrainMesh(){
  fetch('/api/3d/terrain?step=5').then(r=>r.json()).then(d=>{
    const off = d.coord_offset;
    const nc = d.ncols, nr = d.nrows;
    const cell = d.cell;
    // 区域尺寸（米）
    const W = (nc-1)*cell, H = (nr-1)*cell;
    // PlaneGeometry：默认在 XY 平面，宽 W 高 H，分段 nc-1 × nr-1
    const geom = new THREE.PlaneGeometry(W, H, nc-1, nr-1);
    // 设置每个顶点的 Z = 高程（注意 PlaneGeometry 顶点顺序：从左上到右下，行=Y）
    const pos = geom.attributes.position;
    // elevations[row][col]：row=0 对应 Y=0(南)。PlaneGeometry 顶点 row=0 在顶部(Y=+H/2，北)。
    // 所以需翻转 Y 方向：顶点行 j 对应 DEM 行 (nr-1-j)
    for(let j=0; j<nr; j++){
      for(let i=0; i<nc; i++){
        const vidx = (j*nc + i) * 3;
        const demRow = nr - 1 - j;   // 翻转：顶点 j=0(北) -> DEM 最大 Y 行
        const z = d.elevations[demRow][i] - off.z;
        pos.setZ(vidx/3, z);
      }
    }
    pos.needsUpdate = true;
    geom.computeVertexNormals();
    // 正射影像作为纹理
    const tex = new THREE.TextureLoader().load('/data/'+d.texture);
    tex.wrapS = tex.wrapT = THREE.ClampToEdgeWrapping;
    // UV：PlaneGeometry 默认 UV 已是 [0..1]，影像北朝上需翻转（V 翻转）
    const uv = geom.attributes.uv;
    for(let k=0; k<uv.count; k++){
      uv.setXY(k, uv.getX(k), 1 - uv.getY(k));
    }
    uv.needsUpdate = true;
    // MeshLambertMaterial 能受光照（地形有立体感）
    const mat = new THREE.MeshLambertMaterial({
      map: tex, transparent:true, opacity:.92, side:THREE.DoubleSide,
    });
    const mesh = new THREE.Mesh(geom, mat);
    // 平移到与点云对齐：区域中心 X=0,Y=0（点云已 center()），地形中心也放原点
    // PlaneGeometry 中心在原点，区域 0..1000 -> 中心 500，减 off.x
    // 点云 center() 后中心在 0，所以地形也居中即可（已在原点）
    mesh.name = 'terrainMesh';
    mesh.rotation.x = 0;  // PlaneGeometry 已在 XY，Z=高程，正确
    STATE.three.terrainMesh = mesh;
    STATE.three.scene.add(mesh);
    // 点云改半透明，让地形纹理透出
    setTimeout(()=>{
      if(STATE.three.points){
        STATE.three.points.material.opacity = .65;
        STATE.three.points.material.transparent = true;
        STATE.three.points.material.size = 1.6;
      }
    }, 3000);
    $('#three-info').textContent = ($('#three-info').textContent || '').replace('· 坡度着色','· 影像地形融合');
  }).catch(e=> console.warn('terrain mesh load failed', e));
}

// ============================================================
// 2b) 三维地质结构（隧道/钻孔/异常体）—— 与点云同坐标系融合
// ============================================================
STATE.three.geoLayers = { tunnel:null, boreholes:[], anomalies:[], group:null };

function loadGeoStructures(){
  fetch('/api/3d/structures').then(r=>r.json()).then(d=>{
    const off = d.coord_offset;
    const scene = STATE.three.scene;
    const group = new THREE.Group();
    group.name = 'geoStructures';
    STATE.three.geoLayers.group = group;

    // --- 隧道轴线（TubeGeometry）---
    const axisPts = d.tunnel.axis.map(p=> new THREE.Vector3(p[0]-off.x, p[1]-off.y, p[2]-off.z));
    const curve = new THREE.CatmullRomCurve3(axisPts);
    const tubeGeom = new THREE.TubeGeometry(curve, 200, d.tunnel.radius, 16, false);
    const tubeMat = new THREE.MeshBasicMaterial({
      color:0xff7a3d, transparent:true, opacity:.25, side:THREE.DoubleSide,
      wireframe:false,
    });
    const tunnel = new THREE.Mesh(tubeGeom, tubeMat);
    // 隧道轮廓线（让形状可见）
    const wireMat = new THREE.MeshBasicMaterial({color:0xff9a6b, wireframe:true, transparent:true, opacity:.15});
    const tunnelWire = new THREE.Mesh(tubeGeom, wireMat);
    tunnel.add(tunnelWire);
    tunnel.name = 'tunnel';
    group.add(tunnel);
    STATE.three.geoLayers.tunnel = tunnel;

    // --- 钻孔（分层圆柱体）---
    const bhGroup = new THREE.Group(); bhGroup.name='boreholes';
    for(const b of d.boreholes){
      const bx = b.x - off.x, by = b.y - off.y;
      const bhGrp = new THREE.Group();
      bhGrp.userData = {id:b.id, name:'borehole'};
      for(const L of b.layers){
        const topZ = L.top_z - off.z, botZ = L.bottom_z - off.z;
        const h = Math.max(0.5, topZ - botZ);
        const cylGeom = new THREE.CylinderGeometry(2.5, 2.5, h, 10);
        const cylMat = new THREE.MeshBasicMaterial({color:new THREE.Color(L.color), transparent:true, opacity:.9});
        const cyl = new THREE.Mesh(cylGeom, cylMat);
        // CylinderGeometry 默认沿 Y 轴；旋转到 Z 轴，并定位到层中心
        cyl.rotation.x = Math.PI/2;
        cyl.position.set(bx, by, (topZ+botZ)/2);
        bhGrp.add(cyl);
      }
      // 地下水位线（蓝色细圆盘）
      if(b.water_z !== null){
        const wGeom = new THREE.CylinderGeometry(4, 4, 1, 12);
        const wMat = new THREE.MeshBasicMaterial({color:0x3d8bff, transparent:true, opacity:.7});
        const w = new THREE.Mesh(wGeom, wMat);
        w.rotation.x = Math.PI/2;
        w.position.set(bx, by, b.water_z - off.z);
        bhGrp.add(w);
      }
      // 孔口标记（小球）
      const capGeom = new THREE.SphereGeometry(4, 10, 8);
      const capMat = new THREE.MeshBasicMaterial({color:0x28d1c4});
      const cap = new THREE.Mesh(capGeom, capMat);
      cap.position.set(bx, by, b.surface_z - off.z);
      bhGrp.add(cap);
      bhGroup.add(bhGrp);
      STATE.three.geoLayers.boreholes.push(bhGrp);
    }
    group.add(bhGroup);

    // --- 异常体（半透明椭球）---
    const anomGroup = new THREE.Group(); anomGroup.name='anomalies';
    for(const a of d.anomalies){
      const ax = a.x - off.x, ay = a.y - off.y, az = a.center_z - off.z;
      const [sx, sy, sz] = a.size;
      // 用 SphereGeometry + 缩放做椭球
      const geom = new THREE.SphereGeometry(1, 20, 16);
      const colorStr = a.color.replace(/rgba?\(([^)]+)\)/, '$1').split(',').slice(0,3).map(Number);
      const mat = new THREE.MeshBasicMaterial({
        color:new THREE.Color(colorStr[0]/255, colorStr[1]/255, colorStr[2]/255),
        transparent:true, opacity:.4, depthWrite:false,
      });
      const sphere = new THREE.Mesh(geom, mat);
      sphere.scale.set(sx, sy, sz);
      sphere.position.set(ax, ay, az);
      sphere.userData = {risk_id:a.risk_id, name:'anomaly', label:a.label};
      anomGroup.add(sphere);
      STATE.three.geoLayers.anomalies.push(sphere);
    }
    group.add(anomGroup);

    scene.add(group);
    $('#three-info').textContent = $('#three-info').textContent + ' · 含隧道/钻孔/异常体';
  }).catch(e=> console.warn('3D structures load failed', e));
}

function setGeoLayerVisible(name, vis){
  const L = STATE.three.geoLayers;
  if(name==='points' && STATE.three.points) STATE.three.points.visible = vis;
  if(name==='terrain' && STATE.three.terrainMesh) STATE.three.terrainMesh.visible = vis;
  if(name==='tunnel' && L.tunnel) L.tunnel.visible = vis;
  if(name==='bh' && L.group) L.group.children.forEach(c=>{ if(c.name==='boreholes') c.visible=vis; });
  if(name==='anom' && L.group) L.group.children.forEach(c=>{ if(c.name==='anomalies') c.visible=vis; });
  // 坐标系：交叉网格面 + 三轴 + 指北针 + 比例尺 统一显隐
  if(name==='coord' && STATE.three.scene){
    ['crossGrids','coordSystem','compass','scalebar'].forEach(gn=>{
      const g = STATE.three.scene.children.find(c=>c.name===gn);
      if(g) g.visible = vis;
    });
  }
}

function flyToRisk(id){
  const r = STATE.risks.find(x=>x.id===id); if(!r) return;
  const cx = r.center_xy[0]-500, cy = r.center_xy[1]-400;
  // 飞到风险区上方
  const cam = STATE.three.camera, ctrl = STATE.three.controls;
  const target = new THREE.Vector3(cx, cy, 0);
  // 起始相机位置（基于风险等级给不同高度）
  const dist = r.risk_level==='高'? 220 : 260;
  const newPos = new THREE.Vector3(cx+dist*0.8, cy-dist*0.9, dist);
  // 简单插值动画
  animateCam(cam.position.clone(), newPos, ctrl.target.clone(), target, 60);
  // 添加风险区轮廓标记 (3D 中画一个矩形框)
  addRiskBox3D(r);
}
let riskBox3D = null;
function addRiskBox3D(r){
  if(riskBox3D){ STATE.three.scene.remove(riskBox3D); }
  const poly = r.polygon_xy;
  const pts3d = poly.map(p=> new THREE.Vector3(p[0]-500, p[1]-400, 30));
  pts3d.push(pts3d[0]);
  const g = new THREE.BufferGeometry().setFromPoints(pts3d);
  const c = COLORS[r.risk_level] || COLORS['中'];
  const m = new THREE.LineBasicMaterial({color: new THREE.Color(c.stroke)});
  riskBox3D = new THREE.Line(g, m);
  STATE.three.scene.add(riskBox3D);
}
function animateCam(p0,p1,t0,t1,steps){
  let i=0;
  function step(){
    i++; const t=i/steps; const e=t*t*(3-2*t);
    STATE.three.camera.position.lerpVectors(p0,p1,e);
    STATE.three.controls.target.lerpVectors(t0,t1,e);
    if(i<steps) requestAnimationFrame(step);
  }
  step();
}
function resetCam(){
  // 等角透视视角，能同时看到 XY 平面展开与 Z 高程层次
  animateCam(STATE.three.camera.position, new THREE.Vector3(750,-750,650),
             STATE.three.controls.target, new THREE.Vector3(0,0,40), 60);
}

// ============================================================
// 3) 里程轴
// ============================================================
function initMileageAxis(){
  const track = $('#mileage-track');
  // 里程刻度 K12+000 ~ K13+000
  for(let i=0;i<=10;i++){
    const pct = i*10;
    const major = i%1===0;
    const tick = document.createElement('div');
    tick.className = 'axis-tick' + (major?' major':'');
    tick.style.left = pct+'%';
    const km = 12 + i*0.1;
    tick.innerHTML = `<div class="tick-lbl">K${km.toFixed(1)}</div>`;
    track.appendChild(tick);
  }
  // 风险标记
  for(const r of STATE.risks){
    const x = r.center_xy[0]; // 0..1000
    const pct = x/1000*100;
    const dot = document.createElement('div');
    dot.className = 'axis-risk r-'+r.risk_level;
    dot.style.left = pct+'%';
    dot.title = `${r.mileage} ${r.type_cn} (${r.risk_level})`;
    dot.dataset.rid = r.id;
    dot.addEventListener('click', ()=> selectRisk(r.id));
    track.appendChild(dot);
  }
  // 游标
  const cursor = document.createElement('div');
  cursor.className = 'axis-cursor';
  cursor.id = 'axis-cursor';
  cursor.innerHTML = '<div class="cursor-lbl"></div>';
  track.appendChild(cursor);
  // 鼠标移动 -> 显示里程
  track.addEventListener('mousemove', e=>{
    const rect = track.getBoundingClientRect();
    const pct = (e.clientX-rect.left)/rect.width;
    const x = pct*1000;
    if(x>=0&&x<=1000){
      cursor.style.opacity = 1;
      cursor.style.left = (pct*100)+'%';
      cursor.querySelector('.cursor-lbl').textContent = 'K'+(12+x/1000).toFixed(3).slice(-6);
    } else cursor.style.opacity = 0;
  });
  track.addEventListener('mouseleave', ()=> cursor.style.opacity = 0);
}

function highlightAxisRisk(id, on){
  $$('.axis-risk').forEach(d=>{
    if(d.dataset.rid===id) d.classList.toggle('active', on);
  });
}

// ============================================================
// 4) 选中风险 -> 全局联动
// ============================================================
async function selectRisk(id){
  STATE.selectedRisk = id;
  // 高亮所有视图
  $$('.risk-label').forEach(()=>{});
  for(const rid in STATE.riskPolygons){
    const r = STATE.risks.find(x=>x.id===rid);
    const c = COLORS[r.risk_level] || COLORS['中'];
    const on = rid===id;
    STATE.riskPolygons[rid].setStyle({weight:on?4:2.5, fillOpacity:on?.45:.25, color:on?'#fff':c.stroke});
  }
  highlightAxisRisk(id, true);
  $('#ev-target').textContent = '加载中…';
  // 3D 定位
  flyToRisk(id);

  // 拉取详情
  try{
    const d = await getJSON('/api/risk/'+id);
    renderEvidence(d);
    renderInterpret(d.risk);
    // 同步报告下拉
    $('#report-select').value = id;
    // 如果问答面板有内容，不强制刷新
  }catch(e){ console.error(e); $('#ev-target').textContent='加载失败'; }
}

// ============================================================
// 5b) ECharts 风险雷达图
// ============================================================
const RADAR_COLORS = {'R001':'#ff4d5e','R002':'#ff7a3d','R003':'#ffcd3d'};
let _radarChart = null;

function renderRiskRadar(rid, compareIds){
  const el = $('#ev-radar');
  if(!el || typeof echarts === 'undefined') return;
  if(_radarChart){ _radarChart.dispose(); _radarChart = null; }
  // 拉取评分数据
  const url = compareIds
    ? '/api/risk_scores'
    : '/api/risk_scores?rid=' + rid;
  fetch(url).then(r=>r.json()).then(data=>{
    _radarChart = echarts.init(el);
    const dims = data.dimensions;
    let series;
    if(compareIds){
      // 对比模式：多条风险叠加
      const filtered = data.risks.filter(r=>compareIds.includes(r.id));
      series = filtered.map(r=>({
        value: r.values, name: r.name,
        itemStyle:{color: RADAR_COLORS[r.id] || '#3d8bff'},
        lineStyle:{width:2}, areaStyle:{opacity:.15},
      }));
    } else {
      series = [{
        value: data.risk.values, name: data.risk.name,
        itemStyle:{color: RADAR_COLORS[rid] || '#3d8bff'},
        lineStyle:{width:2.5}, areaStyle:{opacity:.25},
      }];
    }
    // 评分总和(横向比较用):每个 series.value 是 6 维分数数组
    const seriesSums = series.map(s => (s.value||[]).reduce((a,b)=>a+(b||0),0));
    const showTitle = series.length === 1;  // 单风险才显示角标,多风险用 legend 避免遮挡
    const showLegend = series.length >= 2;  // 对比模式才显示 legend

    const option = {
      tooltip: { trigger:'item', backgroundColor:'rgba(20,29,46,.95)',
                 borderColor:'#3d8bff', textStyle:{color:'#dfe7f3',fontSize:11} },
      radar: {
        indicator: dims.map(d=>({name:d.name, max:d.max})),
        shape:'polygon',
        splitNumber:4,
        axisName:{color:'#8ea0bd',fontSize:10},
        splitLine:{lineStyle:{color:'#2c3a55'}},
        splitArea:{areaStyle:{color:['rgba(61,139,255,.02)','rgba(61,139,255,.05)']}},
        axisLine:{lineStyle:{color:'#2c3a55'}},
        // 给右上角 legend 留出空间
        ...(showLegend ? {center:['50%','54%'], radius:'62%'} : {}),
      },
      series:[{ type:'radar', data:series, symbolSize:5 }],
    };

    // 对比模式:可点击 legend,切换显示/隐藏某条风险
    if(showLegend){
      option.legend = {
        data: series.map(s=>s.name),
        bottom: 0,
        textStyle:{color:'#8ea0bd', fontSize:10},
        itemWidth: 12, itemHeight: 8, itemGap: 14,
        inactiveColor:'#445270',
      };
    }
    // 单风险:左上角角标显示 总分/均值,方便横向比较
    if(showTitle){
      const sum = seriesSums[0];
      const avg = Math.round(sum / (series[0].value||[]).length);
      option.title = {
        text: `Σ ${sum}  ·  均 ${avg}`,
        left: 6, top: 0,
        textStyle:{color:'#3d8bff', fontSize:11, fontWeight:600},
        subtextStyle:{color:'#8ea0bd', fontSize:9},
      };
    }
    _radarChart.setOption(option);
  }).catch(e=> console.warn('radar fetch failed', e));
}

// 对比雷达：在证据面板渲染多风险叠加
function renderCompareRadar(ids){
  const idsLabel = ids.map(id=> {
    const r = STATE.risks.find(x=>x.id===id);
    return r ? r.mileage + ' ' + r.type_cn : id;
  }).join(' vs ');
  $('#ev-target').textContent = '📊 多风险对比';
  // 先放占位结构
  $('#evidence-content').innerHTML = `
    <div class="ev-header">
      <div class="ev-name">风险对比分析</div>
      <div class="ev-meta">
        <span class="ev-tag">对比对象：${escapeHtml(idsLabel)}</span>
      </div>
    </div>
    <div id="ev-radar" style="width:100%;height:280px;margin-bottom:6px"></div>
    <div style="font-size:10px;color:var(--text-dim);text-align:center;margin-bottom:10px">
      📊 多风险证据强度对比（叠加雷达图，点击右下证据来源切换）
    </div>
    <div style="font-size:12px;color:var(--text-dim);padding:8px;background:var(--bg2);border-radius:6px;line-height:1.8">
      💡 对比要点：每个风险在不同维度的得分反映其<strong style="color:var(--accent2)">致险机理差异</strong>。
      边坡风险在坡度/高差维度突出，富水风险在物探/地下水维度突出。
    </div>`;
  renderRiskRadar(null, ids);
}

// 钻孔地层可视化（ECharts 横向条形，按岩性着色）
function renderBoreholeChart(b){
  const el = $('#bh-chart-' + b.id);
  if(!el || typeof echarts === 'undefined') return;
  const chart = echarts.init(el);
  // 反转地层顺序（深处在上还是下？横向条形：底部=深，故反转使深度向下递增）
  const layers = b.layers;
  chart.setOption({
    title: { text: b.id + ' 地层柱状（孔深 '+b.depth_m+'m' + (b.water_depth_m!=null?' · 水位 '+b.water_depth_m+'m':'') + '）',
             textStyle:{color:'#8ea0bd',fontSize:11}, left:'center', top:0 },
    tooltip: { trigger:'item', formatter: p=> `${p.name}<br/>深度 ${p.value[0]}~${p.value[1]}m<br/>${p.data.desc}` },
    grid: { left:70, right:30, top:25, bottom:10 },
    xAxis: { type:'value', name:'深度(m)', nameTextStyle:{color:'#8ea0bd',fontSize:10},
             min:0, max:b.depth_m, axisLabel:{color:'#8ea0bd',fontSize:9},
             splitLine:{lineStyle:{color:'#2c3a55'}} },
    yAxis: { type:'category', data:[b.id],
             axisLabel:{color:'#dfe7f3',fontSize:11}, axisLine:{lineStyle:{color:'#2c3a55'}} },
    series: layers.map(L=>({
      type:'bar', stack:b.id, name:L.lithology,
      data:[[ L.top, L.bottom, L.lithology ]],
      itemStyle:{ color:L.color || '#888' },
      // data 末尾附带 desc（tooltip 用）
      _desc: L.desc,
    })),
  });
  // 修正：series.data 需要带 desc —— 重设 tooltip
  chart.setOption({ series: layers.map(L=>({
    type:'bar', stack:b.id, name:L.lithology, barWidth:'60%',
    data:[{ value:[L.top, L.bottom], name:L.lithology, desc:L.desc }],
    itemStyle:{ color:L.color || '#888', borderColor:'#000', borderWidth:.5 },
    label:{ show:true, formatter:L.lithology, color:'#fff', fontSize:9, position:'inside' },
  })) });
}

// 物探电阻率热力图（ECharts heatmap，交互式）
function renderGeophysicsHeatmap(lid){
  const el = $('#geo-heatmap-' + lid);
  if(!el || typeof echarts === 'undefined') return;
  fetch('/api/geophysics/'+lid+'/grid').then(r=>r.json()).then(d=>{
    const chart = echarts.init(el);
    // 颜色：低阻（蓝/紫，危险）→ 高阻（红/白，正常）
    // jet_r 反转：低阻显眼
    const data = d.data.map(p=>[p[0], p[1], p[2]]);
    chart.setOption({
      tooltip: {
        backgroundColor:'rgba(20,29,46,.95)', borderColor:'#3d8bff',
        textStyle:{color:'#dfe7f3',fontSize:11},
        formatter: p => {
          const sta = d.stations[p.value[0]];
          const dep = d.depths[p.value[1]];
          const rho = p.value[2];
          return `<b>桩号 ${sta}m</b><br/>深度 ${dep}m<br/>电阻率 <b style="color:${rho<d.anomaly.rho*2.5?'#ff7a3d':'#3dd97a'}">${rho} Ω·m</b>${rho<d.anomaly.rho*2.5?'<br/>⚠️ 低阻异常区':''}`;
        }
      },
      grid: { left:55, right:20, top:15, bottom:35 },
      xAxis: { type:'category', name:'桩号(m)', nameLocation:'middle', nameGap:22,
               data: d.stations.map((s,i)=> i%5===0 ? s.toFixed(0) : ''),
               nameTextStyle:{color:'#8ea0bd',fontSize:10},
               axisLabel:{color:'#8ea0bd',fontSize:9},
               splitLine:{show:false} },
      yAxis: { type:'category', name:'深度(m)', nameTextStyle:{color:'#8ea0bd',fontSize:10},
               data: d.depths.map(dd=>dd.toFixed(1)),
               axisLabel:{color:'#8ea0bd',fontSize:9},
               inverse:false },
      visualMap: {
        min: d.rho_min, max: d.rho_max,
        calculable:true, orient:'horizontal', left:'center', bottom:0,
        textStyle:{color:'#8ea0bd',fontSize:10},
        inRange: { color: ['#2c1a6b','#3b5fbf','#5fd4d4','#a8e040','#ffe600','#ff7a3d','#d62728'] },
      },
      series: [{
        type:'heatmap', data:data,
        // ECharts heatmap: [x_idx, y_idx, value]
        emphasis:{ itemStyle:{shadowBlur:10, shadowColor:'rgba(0,0,0,.5)'} },
        // 异常区标注用 markPoint 不可用于 heatmap，改用 graphic
      }],
      // 标注异常中心
      graphic: [{
        type:'circle',
        // 把异常 x(米) -> station index
        shape:{ cx: 0, cy: 0, r:8 },
        position: [
          (d.stations.findIndex(s=>Math.abs(s-d.anomaly.x)<8) / d.stations.length) * el.clientWidth,
          15 + (d.depths.findIndex(dd=>Math.abs(dd-d.anomaly.depth)<2) / d.depths.length) * (el.clientHeight-50)
        ],
        style:{ fill:'rgba(255,77,94,.0)', stroke:'#ff4d5e', lineWidth:2.5, lineDash:[4,3]},
        invisible: d.stations.findIndex(s=>Math.abs(s-d.anomaly.x)<8) < 0,
      }],
    });
    // 异常标注文字
    chart.setOption({ title: { show:false } });
  }).catch(e=> console.warn('heatmap fetch failed', e));
}

// ============================================================
// 5c) 证据链面板渲染
// ============================================================
function renderEvidence(d){
  const r = d.risk;
  const c = COLORS[r.risk_level] || COLORS['中'];
  $('#ev-target').textContent = r.mileage + ' · ' + r.type_cn;
  const cards = d.evidence_cards.map((ev,i)=>`
    <div class="ev-card kind-${ev.kind}" data-kind="${ev.kind}">
      <div class="ev-card-head">
        <span class="ev-icon">${iconFor(ev.kind)}</span>
        <span class="ev-src">${ev.source}</span>
        <span class="ev-num">${i+1}</span>
      </div>
      <div class="ev-text">${escapeHtml(ev.content)}</div>
      ${renderCardExtra(ev)}
    </div>
  `).join('');

  const params = r.evidence.params ? Object.entries(r.evidence.params).map(([k,v])=>`
    <div class="ev-param"><div class="pk">${paramLabel(k)}</div><div class="pv">${fmtVal(v)}</div></div>
  `).join('') : '';

  $('#evidence-content').innerHTML = `
    <div class="ev-header">
      <div class="ev-name">${r.name}</div>
      <div class="ev-meta">
        <span class="ev-tag level-${r.risk_level}">风险等级 ${r.risk_level}</span>
        <span class="ev-tag">可信度 ${r.confidence}</span>
        <span class="ev-tag">里程 ${r.mileage}</span>
        <span class="ev-tag">${r.type_cn}</span>
      </div>
    </div>
    <div id="ev-radar" style="width:100%;height:220px;margin-bottom:6px"></div>
    <div style="font-size:10px;color:var(--text-dim);text-align:center;margin-bottom:10px">
      📊 多源证据强度雷达图（6 维度，越高越危险）
    </div>
    <div class="ev-chain">${cards}</div>
    ${params?`<div style="margin-top:12px;font-size:11px;color:var(--text-dim);font-weight:600">关键参数</div>
      <div class="ev-params">${params}</div>`:''}
  `;
  // 渲染雷达图
  renderRiskRadar(r.id);
}

function renderCardExtra(ev){
  if(ev.kind==='geophysics' && ev.file){
    const lid = ev.extra.id || 'L1';
    // 交互式热力图（主）+ 静态断面图（参考）
    const html = `<div id="geo-heatmap-${lid}" style="width:100%;height:240px"></div>
            <div class="ev-extra">🖱️ 悬停查看精确电阻率 · 测线：${ev.extra.name} · 最低 ${ev.extra.rho_min||'—'} Ω·m</div>
            <details style="margin-top:6px"><summary style="font-size:11px;color:var(--text-dim);cursor:pointer">📐 查看原始断面图（matplotlib 渲染）</summary>
              <img class="ev-img" src="/data/${ev.file}" alt="物探剖面" style="margin-top:6px"></details>`;
    setTimeout(()=> renderGeophysicsHeatmap(lid), 100);
    return html;
  }
  if(ev.kind==='borehole' && ev.file){
    const imgs = ev.file.map((f,i)=>`<img class="ev-img" src="/data/${f}" style="width:${100/ev.file.length-2}%;display:inline-block;margin-right:2%" alt="钻孔">`).join('');
    const chartDiv = ev.extra.map((b,i)=>`<div id="bh-chart-${b.id}" style="width:100%;height:${Math.max(80, b.depth_m*4)}px"></div>`).join('');
    // 延迟渲染地层图
    setTimeout(()=> ev.extra.forEach(b=> renderBoreholeChart(b)), 100);
    return imgs + chartDiv + `<div class="ev-extra">${ev.extra.map(b=>`${b.id}(${b.mileage})`).join('、')} · 上方为 ECharts 地层可视化</div>`;
  }
  if(ev.kind==='image' && ev.file){
    return `<div class="ev-extra">👉 对应左侧正射影像中的<span style="color:var(--warn)">高亮风险区</span></div>`;
  }
  if(ev.kind==='pointcloud' && ev.file){
    return `<div class="ev-extra">👉 对应中间三维点云视图（已自动定位）</div>`;
  }
  if(ev.kind==='text' && ev.extra && ev.extra.length){
    return ev.extra.map(s=>`<div class="ev-extra">出处：《${'勘察报告'}》${s.title}</div>`).join('');
  }
  return '';
}

function iconFor(kind){
  return {image:'🛰',pointcloud:'🏔',geophysics:'📡',borehole:'🔩',text:'📄'}[kind] || '•';
}
function paramLabel(k){
  return ({max_slope_deg:'最大坡度(°)',relief_m:'相对高差(m)',rho_min:'最低电阻率(Ω·m)',
    weathered_depth_m:'风化层厚(m)',water_depth_m:'地下水位(m)',fracture_width_m:'破碎带宽(m)',
    rqd_pct:'RQD(%)',avg_slope_deg:'平均坡度(°)',deposit_depth_m:'堆积层厚(m)'})[k]||k;
}
function fmtVal(v){ return (typeof v==='number')? (Number.isInteger(v)?v:v.toFixed(1)) : v }
function escapeHtml(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}

// ============================================================
// 6) 风险解释面板
// ============================================================
function renderInterpret(r){
  $('#pane-interpret').innerHTML = `
    <div class="interp-block">
      <h3>综合风险解释 — ${r.name}</h3>
      <p>${escapeHtml(r.interpretation)}</p>
      <div class="suggestion"><b>设计与施工建议：</b>${escapeHtml(r.design_suggestion)}</div>
      <div style="margin-top:10px;font-size:11px;color:var(--text-dim)">
        本解释由系统基于<strong style="color:var(--accent2)">多源证据链</strong>生成，
        可追溯至影像、点云、物探、钻孔、勘察报告等具体数据来源。
      </div>
    </div>`;
  switchTab('interpret');
}

// ============================================================
// 7) 智能对话 (基于 /api/chat —— NLU 引擎：意图识别+RAG+多轮+条件查询)
// ============================================================
const CHAT_SESSION = 'user_' + Math.random().toString(36).slice(2,8);
const INTENT_LABEL = {
  locate:'🗺️ 定位', query:'🔍 查询', compare:'📊 对比',
  explain:'💡 解释', report:'📑 报告', greet:'👋 问候',
};
const ACTION_LABEL = {
  locate_risk:'📍 跳转风险区', gen_report:'📑 查看报告',
};

async function loadChatSuggestions(){
  try{
    const d = await getJSON('/api/chat/suggest');
    const box = $('#qa-suggest');
    box.innerHTML = '<span class="qs-label">快捷指令：</span>' +
      d.suggestions.map(s=>`<button class="chip" data-q="${escapeAttr(s.q)}">${s.icon} ${escapeHtml(s.q.slice(0,14))}${s.q.length>14?'…':''}</button>`).join('');
    $$('.qa-suggest .chip').forEach(c=> c.addEventListener('click', ()=>{
      $('#qa-input').value = c.dataset.q; sendChat(c.dataset.q);
    }));
  }catch(e){ /* 静默失败 */ }
}

async function sendChat(text){
  text = (text ?? '').trim();
  if(!text) return;
  const input = $('#qa-input');
  if(input) input.value = '';
  const out = $('#qa-output');
  // 用户气泡
  const uMsg = document.createElement('div');
  uMsg.className = 'qa-msg user';
  uMsg.innerHTML = `<b>🙋</b> ${escapeHtml(text)}`;
  out.appendChild(uMsg);
  switchTab('qa');
  // bot 占位
  const bot = document.createElement('div');
  bot.className = 'qa-msg bot';
  bot.innerHTML = '<div class="thinking">正在理解意图并检索证据链</div>';
  out.appendChild(bot);
  out.scrollTop = out.scrollHeight;
  try{
    const r = await fetch('/api/chat',{
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({message:text, session_id:CHAT_SESSION})
    });
    if(!r.ok) throw new Error('HTTP '+r.status);
    const d = await r.json();
    $('#qa-session').textContent = '会话：' + (d.session_id||CHAT_SESSION).slice(0,12);
    const html = marked.parse(d.answer||'');
    const badge = d.intent ? `<span class="intent-badge intent-${d.intent}">${INTENT_LABEL[d.intent]||d.intent}</span>` : '';
    // 动作按钮（可点击执行）
    const actions = (d.actions||[]).map(a=>{
      const lbl = ACTION_LABEL[a.type] || a.type;
      const payload = encodeURIComponent(JSON.stringify(a));
      return `<span class="act-chip" data-act="${payload}">${lbl}</span>`;
    }).join('');
    // 证据来源卡片
    const refs = (d.evidence_refs||[]).filter(x=>x.risk_id).map(ref=>
      `<span class="ref-chip" data-rid="${ref.risk_id}">🔗 ${escapeHtml(ref.title)}</span>`).join('');
    bot.innerHTML = `
      <div class="msg-meta">${badge}<span>NLU 引擎</span></div>
      ${html}
      ${actions?`<div class="qa-actions">${actions}
        <span style="font-size:10px;color:var(--text-dim);align-self:center">↑ 点击执行联动</span></div>`:''}
      ${refs?`<div class="qa-refs"><b>证据来源：</b>${refs}</div>`:''}
    `;
    // 绑定动作按钮
    $$('.act-chip', bot).forEach(btn=> btn.addEventListener('click', ()=>{
      const a = JSON.parse(decodeURIComponent(btn.dataset.act));
      executeAction(a);
    }));
    // 绑定证据卡片
    $$('.ref-chip', bot).forEach(ch=> ch.addEventListener('click', ()=> ch.dataset.rid && selectRisk(ch.dataset.rid)));
    // 对比意图：在证据面板渲染多风险叠加雷达图
    if(d.intent === 'compare' && (d.evidence_refs||[]).length >= 2){
      const cmpIds = d.evidence_refs.filter(x=>x.risk_id).map(x=>x.risk_id).slice(0,3);
      if(cmpIds.length >= 2) renderCompareRadar(cmpIds);
    } else if(d.actions && d.actions.length){
      // 自动执行第一个动作（让对话直接驱动地图，体验更顺）
      setTimeout(()=> executeAction(d.actions[0]), 400);
    }
  }catch(e){
    bot.innerHTML = `<div style="color:var(--danger)">⚠ 请求失败：${escapeHtml(e.message)}<br>请确认后端服务正在运行。</div>`;
  }
  out.scrollTop = out.scrollHeight;
}

// 执行 NLU 返回的动作（Function Calling 的本地实现）
function executeAction(a){
  if(a.type === 'locate_risk' && a.risk_id){
    selectRisk(a.risk_id);                  // 联动地图 + 3D + 证据链
  } else if(a.type === 'locate_borehole' && a.borehole_id){
    // 定位钻孔：在地图上打开 popup
    const bh = STATE.boreholeCache && STATE.boreholeCache[a.borehole_id];
    if(bh && STATE.map){
      STATE.map.setView(xyToLatLng(bh.xy), Math.max(STATE.map.getZoom(), 1));
    }
  } else if(a.type === 'gen_report' && a.risk_id){
    $('#report-scope').value = 'risk';
    $('#report-select').value = a.risk_id;
    $('#report-select').style.display = '';
    switchTab('report');
    genReport();
  }
}

function escapeAttr(s){return escapeHtml(s).replace(/"/g,'&quot;')}

// ============================================================
// 8) 报告生成引擎 (Word/Markdown/HTML × 单风险/全线)
// ============================================================
function renderReportSelect(){
  $('#report-select').innerHTML = STATE.risks.map(r=>
    `<option value="${r.id}">${r.mileage} ${r.type_cn} (${r.risk_level})</option>`).join('');
}

function getReportParams(){
  const scope = $('#report-scope').value;
  const fmt = $('#report-fmt').value;
  const rid = scope==='risk' ? $('#report-select').value : null;
  return { scope, fmt, rid };
}

function reportDownloadUrl(){
  const {scope, fmt, rid} = getReportParams();
  let url = `/api/report/download?scope=${scope}&fmt=${fmt}`;
  if(rid) url += `&rid=${rid}`;
  return url;
}

async function genReport(){
  const {scope, fmt, rid} = getReportParams();
  const out = $('#report-output');
  out.innerHTML = '<div class="report-empty">⏳ 正在生成报告…</div>';
  try{
    const params = new URLSearchParams();
    params.set('scope', scope);
    if(rid) params.set('rid', rid);
    const d = await getJSON('/api/report/preview?'+params.toString());
    // 预览用 Markdown 渲染
    out.innerHTML = marked.parse(d.markdown);
    // 更新下载链接
    $('#report-download').href = reportDownloadUrl();
    // 格式提示
    const fmtName = {docx:'Word(.docx)',md:'Markdown(.md)',html:'HTML(.html)'}[fmt];
    const note = document.createElement('div');
    note.style.cssText = 'margin-top:10px;padding:8px 12px;background:rgba(61,217,122,.08);border:1px solid rgba(61,217,122,.3);border-radius:6px;font-size:11px;color:var(--safe)';
    note.innerHTML = `✓ 报告已生成（预览为 Markdown 渲染）。点击上方「⬇ 下载文件」可获取 <b>${fmtName}</b> 原文件${
      fmt==='docx'?'（含内嵌物探剖面图与钻孔柱状图）':''}。`;
    out.appendChild(note);
  }catch(e){
    out.innerHTML = `<div class="report-empty" style="color:var(--danger)">⚠ 生成失败：${escapeHtml(e.message)}</div>`;
  }
}

// ============================================================
// 9) 数据源浮窗
// ============================================================
function renderDataSources(sources){
  $('#ds-list').innerHTML = sources.map(s=>`
    <div class="ds-item">
      <div class="ds-icon">${iconForSource(s.icon)}</div>
      <div class="ds-body">
        <div class="ds-type">${s.type}</div>
        <div class="ds-purpose">${s.purpose}</div>
      </div>
    </div>`).join('');
}
function iconForSource(i){
  return {image:'🛰',mountain:'🏔',route:'🛤',wave:'📡',drill:'🔩',doc:'📄',warning:'⚠'}[i]||'📊';
}

// ============================================================
// 10) 事件绑定
// ============================================================
function bindEvents(){
  // 图层开关
  const toggle = (id, layer)=> $('#'+id).addEventListener('change', e=>{
    if(e.target.checked) layer.addTo(STATE.map);
    else STATE.map.removeLayer(layer);
  });
  toggle('lyr-dem', STATE.layers.dem);
  toggle('lyr-route', STATE.layers.route);
  toggle('lyr-bh', STATE.layers.bh);
  toggle('lyr-geo', STATE.layers.geo);
  toggle('lyr-risk', STATE.layers.risk);
  $('#lyr-ortho').addEventListener('change', e=> STATE.layers.ortho.setOpacity(e.target.checked?1:0));

  // 风险等级筛选
  $('#risk-filter').addEventListener('change', e=>{
    const lv = e.target.value;
    STATE.risks.forEach(r=>{
      const show = !lv || r.risk_level===lv;
      const poly = STATE.riskPolygons[r.id], mk = STATE.riskMarkers[r.id];
      if(show){
        if(poly && !STATE.map.hasLayer(poly)) poly.addTo(STATE.map);
        if(mk && !STATE.map.hasLayer(mk)) mk.addTo(STATE.map);
      } else {
        if(poly && STATE.map.hasLayer(poly)) STATE.map.removeLayer(poly);
        if(mk && STATE.map.hasLayer(mk)) STATE.map.removeLayer(mk);
      }
    });
  });

  // 三维工具按钮
  $('#btn-flyto').addEventListener('click', ()=>{ if(STATE.selectedRisk) flyToRisk(STATE.selectedRisk); });
  $('#btn-reset').addEventListener('click', resetCam);
  $('#btn-slope').addEventListener('click', ()=>{
    if(STATE.three.points){
      const m = STATE.three.points.material;
      m.size = m.size > 3 ? 2.2 : 4;
    }
  });
  // 3D 图层开关
  $('#tlyr-points').addEventListener('change', e=> setGeoLayerVisible('points', e.target.checked));
  $('#tlyr-terrain').addEventListener('change', e=> setGeoLayerVisible('terrain', e.target.checked));
  $('#tlyr-tunnel').addEventListener('change', e=> setGeoLayerVisible('tunnel', e.target.checked));
  $('#tlyr-bh').addEventListener('change', e=> setGeoLayerVisible('bh', e.target.checked));
  $('#tlyr-anom').addEventListener('change', e=> setGeoLayerVisible('anom', e.target.checked));
  $('#tlyr-coord').addEventListener('change', e=> setGeoLayerVisible('coord', e.target.checked));

  // 底部 tab
  $$('.bottom-tabs .tab').forEach(t=> t.addEventListener('click', ()=> switchTab(t.dataset.tab)));

  // 智能对话
  $('#qa-send').addEventListener('click', ()=> sendChat($('#qa-input').value));
  $('#qa-input').addEventListener('keydown', e=>{ if(e.key==='Enter') sendChat(e.target.value); });
  loadChatSuggestions();   // 异步加载快捷指令

  // 报告
  $('#report-gen').addEventListener('click', genReport);
  // 范围切换：单风险时显示风险下拉
  $('#report-scope').addEventListener('change', e=>{
    $('#report-select').style.display = e.target.value==='risk' ? '' : 'none';
  });
  // 下载按钮初始链接
  $('#report-download').addEventListener('click', e=>{
    if(!$('#report-output').querySelector('h1,h2,h3,table,p')){
      e.preventDefault();
      // 还未生成，直接触发下载
    }
  });

  // 数据源浮窗
  $('#ds-fab').addEventListener('click', ()=> $('#ds-panel').classList.toggle('show'));
  $('#ds-close').addEventListener('click', ()=> $('#ds-panel').classList.remove('show'));

  // 全屏（最大化）切换
  $$('.ph-fs').forEach(btn=>{
    btn.addEventListener('click', ()=>{
      const sel = btn.dataset.target;
      const target = document.querySelector(sel);
      if(!target) return;
      const on = target.classList.toggle('fs-active');
      btn.classList.toggle('fs-on', on);
      btn.textContent = on ? '⤡' : '⤢';
      // 关闭其它已最大化的面板
      $$('.fs-active').forEach(el=>{ if(el!==target){
        el.classList.remove('fs-active');
        const key = Array.from(el.classList).find(c=>c.endsWith('-panel')||c==='bottombar');
        const b = key && document.querySelector('.ph-fs[data-target=".'+key+'"]');
        if(b){ b.classList.remove('fs-on'); b.textContent='⤢'; }
      }});
      // 等 CSS 过渡后重排
      setTimeout(relayout, 60);
    });
  });

  // ESC 退出全屏
  document.addEventListener('keydown', e=>{
    if(e.key==='Escape'){
      const act = document.querySelector('.fs-active');
      if(act){
        act.classList.remove('fs-active');
        document.querySelectorAll('.ph-fs.fs-on').forEach(b=>{ b.classList.remove('fs-on'); b.textContent='⤢'; });
        setTimeout(relayout, 60);
      }
    }
  });

  // 窗口自适应：集中重排地图 / 3D / 图表
  let _rzT = null;
  window.addEventListener('resize', ()=>{
    clearTimeout(_rzT);
    _rzT = setTimeout(relayout, 80);
  });
}

// 重排所有可视化（窗口缩放 / 全屏切换后调用）
function relayout(){
  if(STATE.map){
    try { STATE.map.invalidateSize({animate:false}); } catch(e){}
  }
  if(STATE.three.renderer && STATE.three.camera){
    const c = STATE.three.renderer.domElement.parentElement;
    const w = c.clientWidth, h = c.clientHeight;
    if(w>0 && h>0){
      STATE.three.camera.aspect = w/h;
      STATE.three.camera.updateProjectionMatrix();
      STATE.three.renderer.setSize(w, h);
    }
  }
  // ECharts 实例
  try {
    if(typeof _radarChart!=='undefined' && _radarChart) _radarChart.resize();
  } catch(e){}
  document.querySelectorAll('[_echarts_instance_]').forEach(el=>{
    const inst = echarts.getInstanceByDom(el);
    if(inst) inst.resize();
  });
}

function switchTab(name){
  $$('.bottom-tabs .tab').forEach(t=> t.classList.toggle('active', t.dataset.tab===name));
  $$('.tab-pane').forEach(p=> p.classList.toggle('active', p.id==='pane-'+name));
  if(name === 'profile' && !STATE._profileLoaded){
    renderRouteProfile();
  }
}

// ============================================================
// 9b) 沿线地质纵剖面 (ECharts)
// ============================================================
async function renderRouteProfile(){
  const out = $('#profile-output');
  if(!out) return;
  out.innerHTML = '<div class="report-empty">⏳ 正在计算沿线地质剖面…</div>';
  try{
    const d = await getJSON('/api/profile/route');
    STATE._profileLoaded = true;
    const xs = d.mileage_x;
    // 风险区段 markArea
    const markAreas = d.risk_zones.map(z=>{
      const c = z.level==='高' ? 'rgba(255,77,94,.15)' : (z.level==='中高' ? 'rgba(255,122,61,.12)' : 'rgba(255,205,61,.1)');
      return [{xAxis: z.start_x}, {xAxis: z.end_x, itemStyle:{color:c}, label:{show:true, formatter: z.mileage+'\n'+z.type_cn, color:'#dfe7f3', fontSize:9, position:'insideTop'}}];
    });
    // 钻孔标点
    const bhMarks = d.boreholes.map(b=>({
      name: b.id, coord: [b.profile_x, b.elevation],
      label:{ show:true, formatter:b.id, color:'#28d1c4', fontSize:9, position:'top' },
      itemStyle:{ color:'#28d1c4' }, symbol:'triangle', symbolSize:8,
    }));
    out.innerHTML = `
      <div id="profile-chart" style="width:100%;height:100%;min-height:180px"></div>
      <div style="display:flex;gap:12px;font-size:11px;color:var(--text-dim);padding:6px 0;flex-wrap:wrap">
        <span>🏔️ 地表高程：${d.stats.surface_range[0]}~${d.stats.surface_range[1]}m</span>
        <span>⛏️ 隧道埋深：${d.stats.min_cover}~${d.stats.max_cover}m</span>
        <span>📏 纵坡：${d.stats.tunnel_grade_pct}%</span>
        <span style="color:#28d1c4">🔩 钻孔投影：${d.boreholes.length} 个</span>
      </div>`;
    const chart = echarts.init($('#profile-chart'));
    chart.setOption({
      tooltip: { trigger:'axis', backgroundColor:'rgba(20,29,46,.95)', borderColor:'#3d8bff',
                 textStyle:{color:'#dfe7f3',fontSize:11},
                 formatter: params => {
                   const i = params[0].dataIndex;
                   return `<b>${d.mileage_labels[i]}</b><br/>` + params.map(p=>
                     `${p.marker} ${p.seriesName}: <b>${p.value}m</b>`).join('<br/>')
                     + `<br/>埋深: <b>${d.cover_depth[i]}m</b>`;
                 }},
      legend: { data:['地表高程','隧道设计高程'], textStyle:{color:'#8ea0bd'}, top:0 },
      grid: { left:55, right:20, top:30, bottom:30 },
      xAxis: { type:'value', name:'里程(m)', min:0, max:1000,
               nameTextStyle:{color:'#8ea0bd',fontSize:10},
               axisLabel:{ color:'#8ea0bd',fontSize:9, formatter:v=>'K+'+v },
               splitLine:{lineStyle:{color:'#2c3a55'}} },
      yAxis: { type:'value', name:'高程(m)', scale:true,
               nameTextStyle:{color:'#8ea0bd',fontSize:10},
               axisLabel:{color:'#8ea0bd',fontSize:9},
               splitLine:{lineStyle:{color:'#2c3a55'}} },
      series: [
        { name:'地表高程', type:'line', data: d.surface_elev, smooth:true,
          symbol:'none', lineStyle:{width:2, color:'#3dd97a'},
          areaStyle:{ color:new echarts.graphic.LinearGradient(0,0,0,1,[
            {offset:0,color:'rgba(61,217,122,.35)'},{offset:1,color:'rgba(61,217,122,.02)'}]) },
          markArea:{ data: markAreas, silent:true },
          markPoint:{ data: bhMarks, symbolSize:8 },
        },
        { name:'隧道设计高程', type:'line', data: d.tunnel_elev,
          symbol:'none', lineStyle:{width:2, color:'#ff7a3d', type:'dashed'} },
      ],
    });
  }catch(e){
    out.innerHTML = `<div class="report-empty" style="color:var(--danger)">⚠ 加载失败：${escapeHtml(e.message)}</div>`;
  }
}

// 启动
if(document.readyState === 'loading'){
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}

})();
