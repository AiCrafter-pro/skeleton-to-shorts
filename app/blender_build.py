"""GLB 하나를 받아 '스케치 → 골조 → 모형 → 완공' 건설 애니메이션을 9:16으로 렌더한다.
격리된 Blender에서 실행: blender -b --factory-startup --python blender_build.py -- --glb x.glb --out x.mp4 --quality final|preview
"""
import bpy, bmesh, sys, json, math, os
from mathutils import Vector
from mathutils.bvhtree import BVHTree

if "ARGS" in globals():  # 열려 있는 Blender에서 소켓으로 실행(라이브 미리보기)
    A = ARGS
else:
    argv = sys.argv[sys.argv.index("--") + 1:]
    A = dict(zip(argv[::2], argv[1::2]))
LIVE = A.get("--live") == "1"
GLB, OUT = A["--glb"], A.get("--out", "")
Q = A.get("--quality", "final")
DUR = float(A.get("--dur", 30))
FPS = 30 if Q == "final" else 24
N = int(DUR * FPS)
T = {"intro": [0, 1.5], "sketch": [1.5, 8], "frame": [8, 15], "model": [15, 21], "real": [21, DUR]}
fr = lambda s: int(round(s * FPS)) + 1
if LIVE:  # 사용자의 기존 씬은 건드리지 않고 새 씬에서만 작업
    name = A.get("--scene", "건축쇼츠")
    old_sc = bpy.data.scenes.get(name)
    if old_sc:
        for o in list(old_sc.objects): bpy.data.objects.remove(o, do_unlink=True)
        bpy.data.scenes.remove(old_sc)
    scn = bpy.data.scenes.new(name)
    bpy.context.window.scene = scn
else:
    scn = bpy.context.scene
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)

# ── 모델 가져오기·정규화 (가장 긴 변 = 10) ──
bpy.ops.import_scene.gltf(filepath=GLB)
meshes = [o for o in scn.objects if o.type == 'MESH']
bpy.ops.object.select_all(action='DESELECT')
for o in meshes:
    o.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]
if len(meshes) > 1:
    bpy.ops.object.join()
obj = bpy.context.view_layer.objects.active
bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
for o in list(scn.objects):
    if o is not obj:
        bpy.data.objects.remove(o, do_unlink=True)
vs = [v.co for v in obj.data.vertices]
mn = Vector((min(v.x for v in vs), min(v.y for v in vs), min(v.z for v in vs)))
mx = Vector((max(v.x for v in vs), max(v.y for v in vs), max(v.z for v in vs)))
s = 10.0 / max(mx - mn)
for v in obj.data.vertices:
    v.co = Vector(((v.co.x - (mn.x + mx.x) / 2) * s, (v.co.y - (mn.y + mx.y) / 2) * s, (v.co.z - mn.z) * s))
obj.data.update()
W, D, H = (mx.x - mn.x) * s, (mx.y - mn.y) * s, (mx.z - mn.z) * s
for p in obj.data.polygons:
    p.use_smooth = True
real_mat = obj.active_material

# ── 드러냄(reveal) 셰이더: 월드 Z < 문턱값인 부분만 보이고, 경계에 빛나는 띠 ──
def key_value(node, pts):
    for t, v in pts:
        node.outputs[0].default_value = v
        node.outputs[0].keyframe_insert("default_value", frame=fr(t))


def wrap(mat, pts, glow, glow_strength=6.0, band=0.18, below_pts=None, under_color=None):
    """mat 표면 셰이더를 드러냄 효과로 감싼다. below_pts가 있으면 그 문턱값 '위'만 보인다(교체 연출)."""
    mat.use_nodes = True
    nt = mat.node_tree; N_ = nt.nodes; L = nt.links
    out = next(n for n in N_ if n.type == 'OUTPUT_MATERIAL')
    src = out.inputs['Surface'].links[0].from_socket
    geo = N_.new('ShaderNodeNewGeometry'); sep = N_.new('ShaderNodeSeparateXYZ'); L.new(geo.outputs['Position'], sep.inputs[0])
    z = sep.outputs['Z']
    thr = N_.new('ShaderNodeValue'); thr.label = 'reveal'; key_value(thr, pts)
    lt = N_.new('ShaderNodeMath'); lt.operation = 'LESS_THAN'; L.new(z, lt.inputs[0]); L.new(thr.outputs[0], lt.inputs[1])
    vis = lt.outputs[0]
    if below_pts:
        thr2 = N_.new('ShaderNodeValue'); key_value(thr2, below_pts)
        ge = N_.new('ShaderNodeMath'); ge.operation = 'GREATER_THAN'; L.new(z, ge.inputs[0]); L.new(thr2.outputs[0], ge.inputs[1])
        mul = N_.new('ShaderNodeMath'); mul.operation = 'MULTIPLY'; L.new(vis, mul.inputs[0]); L.new(ge.outputs[0], mul.inputs[1]); vis = mul.outputs[0]
    # 경계 띠: thr - band < z
    sub = N_.new('ShaderNodeMath'); sub.operation = 'SUBTRACT'; L.new(thr.outputs[0], sub.inputs[0]); sub.inputs[1].default_value = band
    gt = N_.new('ShaderNodeMath'); gt.operation = 'GREATER_THAN'; L.new(z, gt.inputs[0]); L.new(sub.outputs[0], gt.inputs[1])
    gmul = N_.new('ShaderNodeMath'); gmul.operation = 'MULTIPLY'; L.new(gt.outputs[0], gmul.inputs[0]); gmul.inputs[1].default_value = glow_strength
    em = N_.new('ShaderNodeEmission'); em.inputs['Color'].default_value = (*glow, 1); L.new(gmul.outputs[0], em.inputs['Strength'])
    add = N_.new('ShaderNodeAddShader'); L.new(src, add.inputs[0]); L.new(em.outputs[0], add.inputs[1])
    if under_color:
        tr = N_.new('ShaderNodeBsdfPrincipled'); tr.inputs['Base Color'].default_value = (*under_color, 1); tr.inputs['Roughness'].default_value = 0.7
    else:
        tr = N_.new('ShaderNodeBsdfTransparent')
    mix = N_.new('ShaderNodeMixShader'); L.new(vis, mix.inputs['Fac']); L.new(tr.outputs[0], mix.inputs[1]); L.new(add.outputs[0], mix.inputs[2])
    L.new(mix.outputs[0], out.inputs['Surface'])
    for attr, val in (("surface_render_method", "DITHERED"), ("use_transparent_shadow", True)):
        try:
            setattr(mat, attr, val)
        except Exception:
            pass


def principled(name, color, rough=0.6, metal=0.0, emit=None):
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*color, 1); b.inputs["Roughness"].default_value = rough; b.inputs["Metallic"].default_value = metal
    if emit:
        b.inputs["Emission Color"].default_value = (*emit[0], 1); b.inputs["Emission Strength"].default_value = emit[1]
    return m


def linked_copy(name, mat):
    o = obj.copy(); o.name = name; scn.collection.objects.link(o)
    o.material_slots[0].link = 'OBJECT'; o.material_slots[0].material = mat
    return o

Hn = H + 0.1
# ① 스케치: 줄인 메시의 와이어프레임, 먹선
ink = principled("ink", (0.05, 0.06, 0.08), 0.9, emit=((0.02, 0.03, 0.05), 0.3))
wire = linked_copy("wire", ink)
dec = wire.modifiers.new("dec", 'DECIMATE'); dec.ratio = min(0.05, 3500 / max(1, len(obj.data.polygons)))  # 스케치 선은 약 3,500면 수준으로
wf = wire.modifiers.new("wf", 'WIREFRAME'); wf.thickness = 0.018; wf.use_even_offset = True; wf.use_replace = True
wrap(ink, [(T["sketch"][0], -0.05), (T["sketch"][1] - 0.5, Hn), (T["model"][0], Hn), (T["model"][0] + 1.8, -0.05)], (0.2, 0.45, 1.0), 4, 0.12)

# ② 뼈대: 건물은 기둥·보 격자(골조), 물건은 모양을 따라 자른 단면 링 + 세로 갈빗대(골격)
KIND = A.get("--kind", "building")
bvh = BVHTree.FromObject(obj, bpy.context.evaluated_depsgraph_get())
g = max(W, D) / 8.0
heights = {}
bm = bmesh.new(); th = max(0.05, g * 0.06)
if KIND == "object":
    src = bmesh.new(); src.from_mesh(obj.data)
    rings = bmesh.new()
    def slice_edges(co, no):
        t = src.copy()
        geom = t.verts[:] + t.edges[:] + t.faces[:]
        bmesh.ops.bisect_plane(t, geom=geom, plane_co=co, plane_no=no, clear_inner=True, clear_outer=True)
        me_ = bpy.data.meshes.new("_sl"); t.to_mesh(me_); t.free()
        rings.from_mesh(me_); bpy.data.meshes.remove(me_)
    n_lv = 16
    for k in range(1, n_lv):
        slice_edges(Vector((0, 0, H * k / n_lv)), Vector((0, 0, 1)))
    for k in range(6):
        a_ = math.pi * k / 6
        slice_edges(Vector((0, 0, 0)), Vector((math.cos(a_), math.sin(a_), 0)))
    src.free()
    me_r = bpy.data.meshes.new("frame_edges"); rings.to_mesh(me_r); rings.free()
    ring_obj = bpy.data.objects.new("frame_edges", me_r); scn.collection.objects.link(ring_obj)
    for o in list(scn.objects): o.select_set(False)
    ring_obj.select_set(True); bpy.context.view_layer.objects.active = ring_obj
    bpy.ops.object.convert(target='CURVE')
    ring_obj.data.bevel_depth = 0.035; ring_obj.data.bevel_resolution = 2
    bpy.ops.object.convert(target='MESH')
    bm.from_mesh(ring_obj.data); bpy.data.objects.remove(ring_obj, do_unlink=True)
    heights = {"rings": n_lv}
else:
    nx, ny = max(2, int(W / g) + 1), max(2, int(D / g) + 1)
    for i in range(nx + 1):
        for j in range(ny + 1):
            x = -W / 2 + W * i / nx; y = -D / 2 + D * j / ny
            hit = bvh.ray_cast(Vector((x, y, H + 5)), Vector((0, 0, -1)))
            if hit[0] is not None and hit[0].z > 0.3:
                heights[(i, j)] = hit[0].z
    def beam(a, b):
        d = b - a; L_ = d.length
        if L_ < 1e-4: return
        ret = bmesh.ops.create_cube(bm, size=1.0)
        vs_ = ret["verts"]; z = d.normalized()
        x = z.cross(Vector((0, 0, 1))) if abs(z.z) < 0.99 else Vector((1, 0, 0)); x.normalize(); y = z.cross(x)
        for v in vs_:
            c = v.co; v.co = a + x * c.x * th + y * c.y * th + z * (c.z + 0.5) * L_
    pos = lambda i, j, zz: Vector((-W / 2 + W * i / nx, -D / 2 + D * j / ny, zz))
    lev = max(0.6, H / 9)
    for (i, j), h in heights.items():
        beam(pos(i, j, 0), pos(i, j, h + 0.25))
        for di, dj in ((1, 0), (0, 1)):
            k = (i + di, j + dj)
            if k in heights:
                top = min(h, heights[k]); zz = lev
                while zz < top:
                    beam(pos(i, j, zz), pos(k[0], k[1], zz)); zz += lev
    if not heights:  # 레이가 모두 빗나간 경우: 외곽 기둥만
        for i in (0, nx):
            for j in (0, ny):
                beam(pos(i, j, 0), pos(i, j, H))
me = bpy.data.meshes.new("frame"); bm.to_mesh(me); bm.free()
frame_obj = bpy.data.objects.new("frame", me); scn.collection.objects.link(frame_obj)
steel = principled("steel", (0.55, 0.38, 0.18), 0.45, 0.6) if KIND != "object" else principled("steel", (0.18, 0.42, 0.72), 0.35, 0.7, emit=((0.1, 0.35, 0.8), 0.6))
frame_obj.data.materials.append(steel)
wrap(steel, [(T["frame"][0], -0.05), (T["frame"][0] + 5, Hn + 0.3), (T["model"][0] + 3, Hn + 0.3), (T["real"][0], -0.05)], (1.0, 0.55, 0.15), 8, 0.2)

# ③ 모형: 흰 점토, 완공 문턱값 '위'만 보임
clay = principled("clay", (0.86, 0.85, 0.82), 0.7)
clay_obj = linked_copy("clay", clay)
wrap(clay, [(T["frame"][0] + 2.5, -0.05), (T["model"][0], 0.55 * H), (T["model"][0] + 3.5, Hn)], (0.7, 0.85, 1.0), 3, 0.15)

# ④ 완공: 원래 텍스처 재질
wrap(real_mat, [(T["real"][0], -0.05), (T["real"][0] + 3.5, Hn)], (1.0, 0.8, 0.35), 10, 0.2, under_color=(0.86, 0.85, 0.82))

# 겹친 복제본이 투명해진 뒤에도 그림자를 드리우지 않도록, 각자 단계 구간에서만 렌더
def show_between(o, t0, t1):
    for t, hide in ((0, True), (t0, False), (t1, True)):
        if t < 0: continue
        o.hide_render = hide; o.keyframe_insert("hide_render", frame=max(1, fr(t)))
        o.hide_viewport = hide; o.keyframe_insert("hide_viewport", frame=max(1, fr(t)))
    for fc in (o.animation_data.action.fcurves if hasattr(o.animation_data.action, "fcurves") else []):
        for kp in fc.keyframe_points: kp.interpolation = 'CONSTANT'
show_between(wire, T["sketch"][0] - 0.1, T["model"][0] + 1.9)
show_between(frame_obj, T["frame"][0] - 0.1, T["real"][0] + 0.1)
show_between(clay_obj, T["frame"][0] + 2.4, T["real"][0])
show_between(obj, T["real"][0], DUR + 1)

# ── 바닥·배경·조명 (종이 → 야경) ──
night = [(0, 0.0), (T["real"][0] + 3, 0.0), (T["real"][0] + 6, 1.0)]
ground = bpy.data.objects.new("ground", bpy.data.meshes.new("ground")); scn.collection.objects.link(ground)
bm = bmesh.new(); bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=3000); bm.to_mesh(ground.data); bm.free()
gm = bpy.data.materials.new("ground"); gm.use_nodes = True; nt = gm.node_tree; Nn = nt.nodes; Ln = nt.links
bsdf = Nn["Principled BSDF"]; bsdf.inputs["Roughness"].default_value = 0.95
geo = Nn.new('ShaderNodeNewGeometry'); sep = Nn.new('ShaderNodeSeparateXYZ'); Ln.new(geo.outputs['Position'], sep.inputs[0])
def grid_line(axis_out):
    dv = Nn.new('ShaderNodeMath'); dv.operation = 'DIVIDE'; Ln.new(axis_out, dv.inputs[0]); dv.inputs[1].default_value = g * 0.5
    fr_ = Nn.new('ShaderNodeMath'); fr_.operation = 'FRACT'; Ln.new(dv.outputs[0], fr_.inputs[0])
    lt_ = Nn.new('ShaderNodeMath'); lt_.operation = 'LESS_THAN'; Ln.new(fr_.outputs[0], lt_.inputs[0]); lt_.inputs[1].default_value = 0.025
    return lt_.outputs[0]
mxl = Nn.new('ShaderNodeMath'); mxl.operation = 'MAXIMUM'; Ln.new(grid_line(sep.outputs['X']), mxl.inputs[0]); Ln.new(grid_line(sep.outputs['Y']), mxl.inputs[1])
nv = Nn.new('ShaderNodeValue'); key_value(nv, night)
day = Nn.new('ShaderNodeMix'); day.data_type = 'RGBA'; day.inputs['A'].default_value = (0.90, 0.89, 0.85, 1); day.inputs['B'].default_value = (0.62, 0.66, 0.74, 1); Ln.new(mxl.outputs[0], day.inputs['Factor'])
nit = Nn.new('ShaderNodeMix'); nit.data_type = 'RGBA'; nit.inputs['A'].default_value = (0.035, 0.04, 0.06, 1); nit.inputs['B'].default_value = (0.08, 0.12, 0.2, 1); Ln.new(mxl.outputs[0], nit.inputs['Factor'])
fin = Nn.new('ShaderNodeMix'); fin.data_type = 'RGBA'; Ln.new(nv.outputs[0], fin.inputs['Factor']); Ln.new(day.outputs['Result'], fin.inputs['A']); Ln.new(nit.outputs['Result'], fin.inputs['B'])
Ln.new(fin.outputs['Result'], bsdf.inputs['Base Color'])
ground.data.materials.append(gm)

world = bpy.data.worlds.new("w"); scn.world = world; world.use_nodes = True
bg = world.node_tree.nodes["Background"]
for t, c, st in ((0, (0.93, 0.92, 0.89), 1.0), (T["real"][0] + 3, (0.93, 0.92, 0.89), 1.0), (T["real"][0] + 6, (0.012, 0.018, 0.045), 1.0)):
    bg.inputs[0].default_value = (*c, 1); bg.inputs[0].keyframe_insert("default_value", frame=fr(t))
    bg.inputs[1].default_value = st; bg.inputs[1].keyframe_insert("default_value", frame=fr(t))

sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", 'SUN')); scn.collection.objects.link(sun)
sun.rotation_euler = (math.radians(50), 0, math.radians(35)); sun.data.angle = math.radians(3)
for t, e, c in ((0, 3.2, (1, 0.97, 0.92)), (T["real"][0] + 3, 3.2, (1, 0.97, 0.92)), (T["real"][0] + 6, 0.35, (0.55, 0.65, 1.0))):
    sun.data.energy = e; sun.data.keyframe_insert("energy", frame=fr(t))
    sun.data.color = c; sun.data.keyframe_insert("color", frame=fr(t))
R = max(W, D) * 0.9 + 2
for k in range(4):
    a = math.pi / 4 + k * math.pi / 2
    L_ = bpy.data.objects.new(f"up{k}", bpy.data.lights.new(f"up{k}", 'SPOT')); scn.collection.objects.link(L_)
    L_.location = (math.cos(a) * R, math.sin(a) * R, 0.3)
    d = Vector((0, 0, H * 0.45)) - L_.location
    L_.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    L_.data.spot_size = math.radians(55); L_.data.color = (1.0, 0.82, 0.55)
    for t, e in ((0, 0.0), (T["real"][0] + 4, 0.0), (T["real"][0] + 6.5, 3500 * (H / 10) ** 2)):
        L_.data.energy = e; L_.data.keyframe_insert("energy", frame=fr(t))

# ── 카메라: 세로 9:16, 천천히 돌며 살짝 다가감 ──
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); scn.collection.objects.link(cam); scn.camera = cam
cam.data.sensor_fit = 'VERTICAL'; cam.data.sensor_height = 24; cam.data.lens = 26; cam.data.clip_end = 1000
tgt = bpy.data.objects.new("tgt", None); tgt.location = (0, 0, H * 0.54); scn.collection.objects.link(tgt)
tc = cam.constraints.new('TRACK_TO'); tc.target = tgt; tc.track_axis = 'TRACK_NEGATIVE_Z'; tc.up_axis = 'UP_Y'
dist = max(2.05 * H, 2.7 * max(W, D))
for k in range(0, N + 1, max(1, FPS // 3)):
    t = k / FPS; u = t / DUR; e = u * u * (3 - 2 * u)
    az = math.radians(-40 + 135 * e); el = math.radians(34 - 18 * min(1, t / 9))
    dd = dist * (1.08 - 0.16 * e)
    cam.location = (math.sin(az) * math.cos(el) * dd, -math.cos(az) * math.cos(el) * dd, H * 0.54 + math.sin(el) * dd)
    cam.keyframe_insert("location", frame=k + 1)

# ── 렌더 설정 ──
r = scn.render
r.engine = 'BLENDER_EEVEE'
r.resolution_x, r.resolution_y = (1080, 1920) if Q == "final" else (720, 1280)
r.resolution_percentage = 100
r.fps = FPS; scn.frame_start = 1; scn.frame_end = N
ee = scn.eevee
for attr, val in (("taa_render_samples", 64 if Q == "final" else 16), ("use_raytracing", Q == "final"),
                  ("shadow_resolution_scale", 1.0), ("use_shadows", True)):
    try:
        setattr(ee, attr, val)
    except Exception:
        pass
r.filter_size = 1.2  # 기본 1.5보다 선명하게
scn.view_settings.view_transform = 'AgX'
try:
    scn.view_settings.look = 'AgX - Medium High Contrast'
except Exception:
    pass
im = r.image_settings
im.media_type = 'VIDEO'
im.file_format = 'FFMPEG'
r.ffmpeg.format = 'MPEG4'; r.ffmpeg.codec = 'H264'; r.ffmpeg.constant_rate_factor = 'PERC_LOSSLESS'; r.ffmpeg.ffmpeg_preset = 'GOOD'; r.ffmpeg.audio_codec = 'NONE'
r.filepath = OUT
if LIVE:
    scn.render.fps = FPS; scn.frame_start = 1; scn.frame_end = N; scn.frame_set(1)
    try: scn.sync_mode = 'FRAME_DROP'
    except Exception: pass
    for area in bpy.context.window.screen.areas:
        if area.type == 'VIEW_3D':
            sp = area.spaces.active
            sp.shading.type = A.get("--shading", 'MATERIAL')
            sp.region_3d.view_perspective = 'CAMERA'
            sp.overlay.show_overlays = False
            with bpy.context.temp_override(window=bpy.context.window, area=area):
                try: bpy.ops.view3d.view_center_camera()
                except Exception: pass
            break
    if A.get("--play") == "1" and not bpy.context.screen.is_animation_playing:
        for area in bpy.context.window.screen.areas:
            if area.type == 'VIEW_3D':
                with bpy.context.temp_override(window=bpy.context.window, area=area):
                    bpy.ops.screen.animation_play()
                break
    result = {"scene": scn.name, "frames": N, "fps": FPS, "dims": [W, D, H]}

# ── 파일 렌더(배치 모드) ──
if not LIVE:
    meta = {"stages": T, "fps": FPS, "frames": N, "dur": DUR, "size": [r.resolution_x, r.resolution_y], "dims": [W, D, H], "frame_columns": len(heights), "kind": KIND}
    json.dump(meta, open(os.path.splitext(OUT)[0] + "_meta.json", "w"), indent=1)
    print("BUILD_READY", json.dumps(meta), flush=True)
    if A.get("--still"):
        scn.frame_set(int(float(A["--still"]) * FPS) + 1)
        im.media_type = 'IMAGE'; im.file_format = 'PNG'; r.filepath = A["--still_out"]
        bpy.ops.render.render(write_still=True)
    else:
        def _progress(scene, *_):
            print(f"PROGRESS {scene.frame_current} {scene.frame_end}", flush=True)
        bpy.app.handlers.render_post.append(_progress)
        bpy.ops.render.render(animation=True)
    print("BUILD_DONE", flush=True)
