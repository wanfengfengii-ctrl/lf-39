import http.client
import urllib.parse
import json
import sys

BASE = "127.0.0.1:8000"

def api(method, path, data=None, form=None):
    conn = http.client.HTTPConnection(BASE)
    headers = {}
    body = None
    if data is not None:
        body = json.dumps(data)
        headers["Content-Type"] = "application/json"
        headers["Accept"] = "application/json"
    if form is not None:
        body = form
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        headers["Accept"] = "application/json"
    if not headers.get("Accept"):
        headers["Accept"] = "application/json"
    conn.request(method, path, body=body, headers=headers)
    resp = conn.getresponse()
    raw = resp.read().decode()
    conn.close()
    try:
        return resp.status, json.loads(raw)
    except:
        return resp.status, raw

def create_project():
    form = urllib.parse.urlencode({"name": "Bug验证项目", "description": "test", "researcher": "test"})
    conn = http.client.HTTPConnection(BASE)
    conn.request("POST", "/api/projects", body=form, headers={"Content-Type": "application/x-www-form-urlencoded"})
    resp = conn.getresponse()
    loc = resp.getheader("Location", "")
    resp.read()
    conn.close()
    pid = loc.rstrip("/").split("/")[-1]
    return int(pid)

passed = 0
failed = 0

def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        print(f"  ❌ {name} — {detail}")

print("=" * 60)
print("  Bug 修复验证测试")
print("=" * 60)

pid = create_project()
print(f"\n项目 ID: {pid}")

# 添加两个容器
_, d1 = api("POST", f"/api/projects/{pid}/multi-vessel/vessels",
            data={"level_index": 0, "name": "上壶", "role": "top",
                  "capacity": 800, "water_inlet_type": "constant",
                  "outlet_diameter": 4, "target_duration": 60, "initial_level": 800})
top_id = d1["vessel"]["id"]

_, d2 = api("POST", f"/api/projects/{pid}/multi-vessel/vessels",
            data={"level_index": 1, "name": "下壶", "role": "bottom",
                  "capacity": 600, "water_inlet_type": "gravity",
                  "outlet_diameter": 3, "target_duration": 60, "initial_level": 0})
bottom_id = d2["vessel"]["id"]

# ── Bug 3：重复流量关系 ──
print("\n── Bug 3：重复流量关系校验 ──")

_, r1 = api("POST", f"/api/projects/{pid}/multi-vessel/relations",
            data={"upstream_vessel_id": top_id, "downstream_vessel_id": bottom_id,
                  "flow_coefficient": 0.95, "delay_seconds": 2, "relation_type": "series"})
check("首次添加流量关系", r1.get("ok") is True)

_, r2 = api("POST", f"/api/projects/{pid}/multi-vessel/relations",
            data={"upstream_vessel_id": top_id, "downstream_vessel_id": bottom_id,
                  "flow_coefficient": 0.90, "delay_seconds": 1, "relation_type": "series"})
check("重复添加流量关系被拒绝", r2.get("ok") is not True, f"返回: {r2}")
check("错误信息包含'已存在'", "已存在" in r2.get("error", ""), f"error: {r2.get('error', '')}")

# ── Bug 1：时间节点顺序 ──
print("\n── Bug 1：时间节点顺序校验 ──")

_, ed = api("POST", f"/api/projects/{pid}/multi-vessel/experiments")
exp_id = ed["experiment"]["id"]

_, rec1 = api("POST", f"/api/projects/{pid}/multi-vessel/experiments/{exp_id}/records",
              data={"time_point": 5.0, "records": [
                  {"vessel_id": top_id, "time_point": 5.0, "water_level": 750},
                  {"vessel_id": bottom_id, "time_point": 5.0, "water_level": 45}]})
check("录入 t=5 成功", rec1.get("ok") is True, f"返回: {rec1}")

_, rec2 = api("POST", f"/api/projects/{pid}/multi-vessel/experiments/{exp_id}/records",
              data={"time_point": 3.0, "records": [
                  {"vessel_id": top_id, "time_point": 3.0, "water_level": 770}]})
check("录入 t=3（倒序）被拒绝", rec2.get("ok") is not True, f"返回: {rec2}")
check("错误信息包含'递增'", "递增" in rec2.get("error", ""), f"error: {rec2.get('error', '')}")

_, rec3 = api("POST", f"/api/projects/{pid}/multi-vessel/experiments/{exp_id}/records",
              data={"time_point": 10.0, "records": [
                  {"vessel_id": top_id, "time_point": 10.0, "water_level": 700},
                  {"vessel_id": bottom_id, "time_point": 10.0, "water_level": 90}]})
check("录入 t=10（正序）成功", rec3.get("ok") is True, f"返回: {rec3}")

_, rec4 = api("POST", f"/api/projects/{pid}/multi-vessel/experiments/{exp_id}/records",
              data={"time_point": 5.0, "records": [
                  {"vessel_id": top_id, "time_point": 5.0, "water_level": 748}]})
check("录入 t=5（重复时间点）被拒绝", rec4.get("ok") is not True, f"返回: {rec4}")

# ── Bug 2：理论刻度线 ──
print("\n── Bug 2：图表理论刻度线数据 ──")

_, rec5 = api("POST", f"/api/projects/{pid}/multi-vessel/experiments/{exp_id}/records",
              data={"time_point": 20.0, "records": [
                  {"vessel_id": top_id, "time_point": 20.0, "water_level": 600},
                  {"vessel_id": bottom_id, "time_point": 20.0, "water_level": 180}]})
_, rec6 = api("POST", f"/api/projects/{pid}/multi-vessel/experiments/{exp_id}/records",
              data={"time_point": 30.0, "records": [
                  {"vessel_id": top_id, "time_point": 30.0, "water_level": 500},
                  {"vessel_id": bottom_id, "time_point": 30.0, "water_level": 270}]})

_, fd = api("POST", f"/api/projects/{pid}/multi-vessel/experiments/{exp_id}/finalize")
check("Finalize 成功", fd.get("ok") is True)

_, sd1 = api("GET", f"/api/projects/{pid}/multi-vessel/vessels/{top_id}/scale")
_, sd2 = api("GET", f"/api/projects/{pid}/multi-vessel/vessels/{bottom_id}/scale")
check("上壶刻度方案有 marks", len(sd1.get("scheme", {}).get("marks", [])) > 0,
      f"marks 数: {len(sd1.get('scheme', {}).get('marks', []))}")
check("下壶刻度方案有 marks", len(sd2.get("scheme", {}).get("marks", [])) > 0,
      f"marks 数: {len(sd2.get('scheme', {}).get('marks', []))}")

top_scheme = sd1["scheme"]
bottom_scheme = sd2["scheme"]
check("上壶刻度方案 vessel_id 匹配", top_scheme.get("vessel_id") == top_id)
check("下壶刻度方案 vessel_id 匹配", bottom_scheme.get("vessel_id") == bottom_id)

print("\n" + "=" * 60)
print(f"  结果: ✅ {passed} 通过, ❌ {failed} 失败")
print("=" * 60)
sys.exit(0 if failed == 0 else 1)
